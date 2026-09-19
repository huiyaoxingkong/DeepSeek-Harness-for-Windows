/**
 * Upload the v<version> release to GitHub — Node implementation.
 *
 * `scripts/upload-release.ps1` is the default path, but it needs PowerShell 7
 * and a working schannel TLS stack. Some build machines cannot reach
 * api.github.com through schannel at all (`CRYPT_E_REVOCATION_OFFLINE`, e.g. an
 * offline CRL/OCSP responder), while Node's bundled OpenSSL works fine. This
 * script performs the same steps with the same inputs:
 *
 *   1. commit + tag + push the source (skippable with --skip-push)
 *   2. create (or reuse) the GitHub Release for the tag
 *   3. upload the Setup/Update exes and the SHA256 files
 *
 * Auth, in order: `--token`, `$GITHUB_TOKEN`, `$GH_TOKEN`, then git's own
 * credential helper (`git credential fill`) — the same credential `git push`
 * uses.
 *
 * Usage:
 *   node scripts/upload-release.mjs --version 1.0.5
 *   node scripts/upload-release.mjs --version 1.0.5 --skip-push
 *   node scripts/upload-release.mjs --version 1.0.5 --dry-run
 */

import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const REPO = 'huiyaoxingkong/DeepSeek-Harness-for-Windows'
const API = `https://api.github.com/repos/${REPO}`
const ROOT = path.resolve(import.meta.dirname, '..')
const RELEASE_DIR = path.join(ROOT, 'release')

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i].replace(/^--/, '')
  const value = process.argv[i + 1]
  if (value === undefined || value.startsWith('--')) {
    args.set(key, '1')
    i -= 1
  } else {
    args.set(key, value)
  }
}
const version = args.get('version') || '1.0.5'
const tag = args.get('tag') || `v${version}`
const skipPush = args.has('skip-push')
const dryRun = args.has('dry-run')

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

function log(message) {
  console.log(message)
}

/** git with the bundled CA / OpenSSL backend, which works where schannel fails. */
function git(gitArgs, options = {}) {
  const env = { ...process.env, GIT_TERMINAL_PROMPT: '0' }
  const caFile = path.join(ROOT, 'app', 'assets', 'cacert.pem')
  const common = ['-c', 'http.sslBackend=openssl']
  if (fs.existsSync(caFile)) common.push('-c', `http.sslCAInfo=${caFile}`)
  // Credential helper chain: the global helper-selector (Git Credential
  // Manager) blocks waiting for a GUI here, while the plain wincred helper
  // reads the token already stored in Windows Credential Manager. Resetting
  // the chain first (`credential.helper=`) is what skips the selector.
  common.push('-c', 'credential.helper=', '-c', 'credential.helper=wincred')
  const out = execFileSync('git', [...common, ...gitArgs], {
    cwd: ROOT, env, encoding: 'utf-8', stdio: options.stdio || ['ignore', 'pipe', 'pipe'],
  })
  return (out || '').trim()
}

function resolveToken() {
  if (args.get('token')) return args.get('token')
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN
  if (process.env.GH_TOKEN) return process.env.GH_TOKEN
  // Ask git for the stored credential (wincred helper, chain reset above).
  for (const helperArgs of [
    ['-c', 'credential.helper=', '-c', 'credential.helper=wincred', 'credential', 'fill'],
    ['credential', 'fill'],
  ]) {
    try {
      const out = execFileSync('git', helperArgs, {
        cwd: ROOT,
        input: 'protocol=https\nhost=github.com\n\n',
        encoding: 'utf-8',
        timeout: 15000,
        stdio: ['pipe', 'pipe', 'ignore'],
      })
      const match = /^password=(.+)$/m.exec(out)
      if (match) return match[1].trim()
    } catch { /* try the next helper form */ }
  }
  return ''
}

async function api(token, method, url, body, extraHeaders = {}) {
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      const res = await fetch(url.startsWith('http') ? url : `${API}${url}`, {
        method,
        headers: {
          'User-Agent': 'dsh-desktop-release',
          Accept: 'application/vnd.github+json',
          Authorization: `Bearer ${token}`,
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...extraHeaders,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const text = await res.text()
      const data = text ? JSON.parse(text) : null
      if (!res.ok) {
        const message = data?.message || text || res.statusText
        const error = new Error(`HTTP ${res.status} ${method} ${url}: ${message}`)
        error.status = res.status
        error.data = data
        throw error
      }
      return data
    } catch (error) {
      // A 4xx is a definitive answer (404 = no such release yet); only
      // transport/5xx failures are worth retrying.
      if (attempt === 5 || (error.status >= 400 && error.status < 500)) throw error
      const delay = Math.min(3 * 2 ** (attempt - 1), 30)
      log(`  attempt ${attempt}/5 failed (${error.message}); retrying in ${delay}s…`)
      await sleep(delay * 1000)
    }
  }
  return null
}

async function uploadAsset(token, releaseId, file, existing) {
  const name = path.basename(file)
  const size = fs.statSync(file).size
  const previous = existing.find(a => a.name === name)
  if (previous) {
    log(`  removing existing asset ${name}`)
    await api(token, 'DELETE', `/releases/assets/${previous.id}`)
  }
  log(`  uploading ${name} (${(size / 1048576).toFixed(1)} MB)`)
  const data = fs.readFileSync(file)
  let uploaded
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const res = await fetch(
        `https://uploads.github.com/repos/${REPO}/releases/${releaseId}/assets?name=${encodeURIComponent(name)}`,
        {
          method: 'POST',
          headers: {
            'User-Agent': 'dsh-desktop-release',
            Accept: 'application/vnd.github+json',
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/octet-stream',
            'Content-Length': String(data.length),
          },
          body: data,
        },
      )
      const text = await res.text()
      uploaded = text ? JSON.parse(text) : null
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${uploaded?.message || text}`)
      break
    } catch (error) {
      if (attempt === 3) throw error
      log(`  upload attempt ${attempt}/3 failed (${error.message}); retrying…`)
      await sleep(attempt * 5000)
    }
  }
  return uploaded
}

async function main() {
  log(`=== DeepSeek Harness for Windows ${version} release upload ===`)
  const notes = path.join(ROOT, 'RELEASE_NOTES.md')
  const body = fs.existsSync(notes) ? fs.readFileSync(notes, 'utf-8') : `DeepSeek Harness for Windows ${version}`

  if (!skipPush) {
    log('=== 1. source: commit + tag + push ===')
    const status = git(['status', '--porcelain'])
    if (status) {
      git(['add', '-A'])
      git(['-c', 'user.name=huiyaoxingkong',
           '-c', 'user.email=lihaoyang20041201@outlook.com',
           'commit', '-m', `v${version}: release`])
    } else {
      log('  working tree clean; nothing to commit')
    }
    const existingTag = git(['tag', '--list', tag])
    if (existingTag) {
      log(`  tag ${tag} already exists`)
    } else {
      git(['tag', '-a', tag, '-m', `DeepSeek Harness for Windows ${version}`])
    }
    if (dryRun) {
      log('  [dry-run] skipping push')
    } else {
      git(['push', 'origin', 'HEAD'], { stdio: ['ignore', 'inherit', 'inherit'] })
      git(['push', 'origin', tag], { stdio: ['ignore', 'inherit', 'inherit'] })
      log(`  pushed branch and tag ${tag}`)
    }
  } else {
    log('=== 1. source: skipped (--skip-push) ===')
  }

  const token = resolveToken()
  if (!token) {
    console.error('ERROR: no GitHub token. Set GITHUB_TOKEN, pass --token, or log in with git.')
    return 2
  }

  log('=== 2. release ===')
  let release = null
  try {
    release = await api(token, 'GET', `/releases/tags/${tag}`)
    log(`  release ${tag} exists (id ${release.id})`)
  } catch (error) {
    if (error.status !== 404) throw error
  }
  if (!release) {
    if (dryRun) {
      log(`  [dry-run] would create release ${tag}`)
    } else {
      release = await api(token, 'POST', '/releases', {
        tag_name: tag,
        name: `DeepSeek Harness for Windows ${version}`,
        body,
        draft: false,
        prerelease: false,
      })
      log(`  created release ${tag} (id ${release.id})`)
    }
  }

  log('=== 3. assets ===')
  const files = fs.existsSync(RELEASE_DIR)
    ? fs.readdirSync(RELEASE_DIR)
        .filter(name => name.includes(version) && (name.endsWith('.exe') || name.endsWith('.sha256') || name.endsWith('.txt')))
        .map(name => path.join(RELEASE_DIR, name))
        .sort()
    : []
  if (files.length === 0) {
    console.error(`ERROR: no release artifacts for ${version} under ${RELEASE_DIR}`)
    return 3
  }
  const existing = release ? await api(token, 'GET', `/releases/${release.id}/assets`) : []
  for (const file of files) {
    if (dryRun) {
      log(`  [dry-run] would upload ${path.basename(file)}`)
      continue
    }
    await uploadAsset(token, release.id, file, existing)
  }

  log('')
  log(dryRun ? 'DRY RUN complete — nothing was uploaded.' : `Done: https://github.com/${REPO}/releases/tag/${tag}`)
  return 0
}

main()
  .then(code => process.exit(code))
  .catch(error => {
    console.error(`upload failed: ${error.message}`)
    process.exit(1)
  })
