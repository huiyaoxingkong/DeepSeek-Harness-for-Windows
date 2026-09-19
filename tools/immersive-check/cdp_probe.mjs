/**
 * Headless regression driver for the desktop shell UI fullscreen (immersive)
 * layout. Drives a real Chromium (Edge, the same engine family as the
 * WebView2 runtime the app ships against) over CDP, clicks the real buttons in
 * app/ui/app.js, and reports the measured geometry of the workspace frame plus
 * screenshots.
 *
 * Usage:
 *   node tools/immersive-check/cdp_probe.mjs --shell-port 34567 --core-port 34568 \
 *        --out .tmp-ui-test/report.json
 *
 * Exit code is non-zero when a scenario's geometry assertion fails, so this
 * doubles as the CI-style regression gate for the exit-fullscreen bug.
 */

import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i].replace(/^--/, ''), process.argv[i + 1])
}
const shellPort = Number(args.get('shell-port'))
const corePort = Number(args.get('core-port'))
const outFile = args.get('out') || path.join(os.tmpdir(), 'dsh-ui-probe.json')
const shotDir = args.get('shots') || path.dirname(outFile)
const debugPort = Number(args.get('debug-port') || 9333)
const keepEdge = args.get('keep-edge') === '1'
// --attach 1 connects to a browser that is already listening (useful when the
// browser must outlive this process, e.g. launched as a managed background job).
const attach = args.get('attach') === '1'
const windowSize = args.get('window-size') || '1280,820'

const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
]

function findBrowser() {
  for (const candidate of EDGE_CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate
  }
  throw new Error('no Edge/Chrome binary found')
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

async function waitFor(fn, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      const value = await fn()
      if (value) return value
    } catch (error) {
      lastError = error
    }
    await sleep(150)
  }
  throw new Error(`timeout waiting for ${label}${lastError ? `: ${lastError.message}` : ''}`)
}

/** Minimal CDP client over the browser's page websocket. */
class Cdp {
  constructor(ws) {
    this.ws = ws
    this.nextId = 1
    this.pending = new Map()
    this.events = []
    ws.addEventListener('message', event => {
      const msg = JSON.parse(event.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        if (msg.error) reject(new Error(`${msg.error.message} (${JSON.stringify(msg.error.data ?? '')})`))
        else resolve(msg.result)
        return
      }
      if (msg.method) this.events.push(msg)
    })
  }

  send(method, params = {}) {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }

  async eval(expression, awaitPromise = false, contextId = undefined) {
    const res = await this.send('Runtime.evaluate', {
      expression, awaitPromise, returnByValue: true,
      ...(contextId === undefined ? {} : { contextId }),
    })
    if (res.exceptionDetails) {
      throw new Error(`evaluate failed: ${res.exceptionDetails.text} ${res.exceptionDetails.exception?.description ?? ''}`)
    }
    return res.result.value
  }
}

const PROBE = `(() => {
  const rect = el => { const b = el.getBoundingClientRect();
    return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) }; };
  const f = document.getElementById('dsh-frame');
  const fw = document.querySelector('.frame-wrap');
  const content = document.querySelector('.content');
  const page = document.getElementById('page-workspace');
  const empty = document.getElementById('frame-empty');
  const cs = el => getComputedStyle(el);
  return {
    bodyClass: document.body.className,
    viewport: { w: innerWidth, h: innerHeight },
    frameHidden: f.classList.contains('hidden'),
    emptyHidden: empty.classList.contains('hidden'),
    frame: rect(f), frameWrap: rect(fw), page: rect(page), content: rect(content),
    empty: rect(empty),
    contentScroll: { sw: content.scrollWidth, cw: content.clientWidth, sh: content.scrollHeight, ch: content.clientHeight },
    docScroll: { sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
                 sh: document.documentElement.scrollHeight, ch: document.documentElement.clientHeight },
    styles: {
      frame: { h: cs(f).height, w: cs(f).width, display: cs(f).display },
      wrap: { h: cs(fw).height, w: cs(fw).width, minH: cs(fw).minHeight, flex: cs(fw).flex,
              display: cs(fw).display, position: cs(fw).position, overflow: cs(fw).overflow },
      page: { h: cs(page).height, minH: cs(page).minHeight, display: cs(page).display, maxW: cs(page).maxWidth },
      content: { h: cs(content).height, padding: cs(content).padding, overflow: cs(content).overflow },
    },
    coreSize: window.__coreSize || null,
    footer: (() => {
      const c = document.querySelector('.content');
      return { scrollableY: c.scrollHeight > c.clientHeight + 1 };
    })(),
  };
})()`

async function main() {
  const browser = attach ? null : findBrowser()
  const profileDir = path.join(process.cwd(), '.tmp-ui-test', `edge-profile-${debugPort}`)
  fs.mkdirSync(profileDir, { recursive: true })
  fs.mkdirSync(shotDir, { recursive: true })

  let child = null
  if (!attach) {
    fs.rmSync(profileDir, { recursive: true, force: true })
    fs.mkdirSync(profileDir, { recursive: true })
    const edgeLog = path.join(profileDir, 'edge.log')
    const logFd = fs.openSync(edgeLog, 'a')
    child = spawn(browser, [
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-extensions',
      '--disable-crash-reporter',
      '--enable-logging=stderr',
      '--disable-features=Translate,BackForwardCache',
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profileDir}`,
      `--window-size=${windowSize}`,
      'about:blank',
    ], { stdio: ['ignore', logFd, logFd], detached: false })
    console.error(`launched ${browser} pid=${child.pid} (log: ${edgeLog})`)
  }

  const cleanup = () => {
    if (keepEdge || attach || !child) return
    try {
      spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    } catch { /* already gone */ }
  }
  process.on('exit', cleanup)

  const version = await waitFor(async () => {
    const res = await fetch(`http://127.0.0.1:${debugPort}/json/version`)
    return res.ok ? await res.json() : null
  }, 90000, 'edge devtools endpoint')

  const target = await waitFor(async () => {
    const res = await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: 'PUT' })
    if (res.ok) return await res.json()
    const list = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json()
    return list.find(t => t.type === 'page') || null
  }, 15000, 'page target')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', () => reject(new Error('websocket failed')), { once: true })
  })
  const cdp = new Cdp(ws)

  await cdp.send('Page.enable')
  await cdp.send('Runtime.enable')
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `window.__coreSize = null;
      window.addEventListener('message', e => {
        if (e.data && e.data.type === 'dsh-size') window.__coreSize = e.data;
      });`,
  })
  const consoleErrors = []
  ws.addEventListener('message', event => {
    const msg = JSON.parse(event.data)
    if (msg.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(msg.params.exceptionDetails.text ?? 'exception')
    }
  })

  const shellUrl = `http://127.0.0.1:${shellPort}/`
  const report = { browser: version.Browser, shellUrl, scenarios: [], consoleErrors, failures: [] }

  const probe = () => cdp.eval(PROBE)
  const shot = async name => {
    const res = await cdp.send('Page.captureScreenshot', { format: 'png' })
    const file = path.join(shotDir, `${name}.png`)
    fs.writeFileSync(file, Buffer.from(res.data, 'base64'))
    return file
  }
  const control = async query => {
    await fetch(`http://127.0.0.1:${shellPort}/api/control?${query}`)
  }
  const load = async () => {
    await cdp.send('Page.navigate', { url: shellUrl })
    await sleep(2500)   // async init(): bridge polls, state, theme, plugins
  }

  /** Geometry assertions shared by every scenario. */
  const check = (label, m, { expectImmersive, expectFrame = true, expectEmpty = false }) => {
    const problems = []
    if (m.viewport.h < 120) problems.push(`viewport too small: ${JSON.stringify(m.viewport)}`)
    if (expectFrame) {
      if (m.frameHidden) problems.push('iframe hidden although a server is running')
      // The inner-size probe only exists on the built-in fake core page.
      if (!args.get('real-core-url') && m.coreSize === null) {
        problems.push('iframe never reported its inner size')
      }
      if (m.frame.h < 200) problems.push(`iframe height collapsed: ${m.frame.h}px`)
      if (m.frame.w < 400) problems.push(`iframe width collapsed: ${m.frame.w}px`)
    }
    if (m.frameWrap.h < 200) problems.push(`frame-wrap height collapsed: ${m.frameWrap.h}px`)
    if (expectEmpty) {
      if (!m.emptyHidden) {
        if (m.empty.h < m.frameWrap.h - 8) {
          problems.push(`empty state does not fill the frame: ${m.empty.h} < ${m.frameWrap.h}`)
        }
      } else {
        problems.push('empty state hidden while no server runs')
      }
    }
    if (!expectImmersive && document2Scrollable(m)) problems.push(`double scrollbar: content ${m.contentScroll.sh} > ${m.contentScroll.ch}`)
    for (const p of problems) report.failures.push(`${label}: ${p}`)
    return problems
  }
  const document2Scrollable = m => m.contentScroll.sh > m.contentScroll.ch + 2

  // ---------------------------------------------------------------- scenarios

  // 1) Boot with the server already running and immersive stored as true:
  //    the real-world case the user hits after a restart while fullscreen.
  await control('running=1&immersive=1')
  await load()
  let m = await probe()
  report.scenarios.push({ name: 'boot-immersive', measured: m, screenshot: await shot('01-boot-immersive'),
    problems: check('boot-immersive', m, { expectImmersive: true }) })

  // 2) Exit fullscreen with the exit button -> the reported bug.
  await cdp.eval(`document.getElementById('btn-exit-immersive').click()`)
  await sleep(900)
  m = await probe()
  report.scenarios.push({ name: 'after-exit-fullscreen', measured: m, screenshot: await shot('02-after-exit'),
    problems: check('after-exit-fullscreen', m, { expectImmersive: false }) })

  // 3) Re-enter and exit again (repeat switching must stay stable).
  await cdp.eval(`document.getElementById('btn-immersive').click()`)
  await sleep(700)
  const m3a = await probe()
  await cdp.eval(`document.getElementById('btn-exit-immersive').click()`)
  await sleep(700)
  m = await probe()
  report.scenarios.push({ name: 'toggle-round-trip', measured: m, screenshots: [await shot('03-toggle-exit')],
    immersivePhase: m3a,
    problems: check('toggle-round-trip', m, { expectImmersive: false }) })

  // 4) Navigate to another shell page and back: the frame must not be lost.
  await cdp.eval(`document.querySelector('.nav-item[data-page="settings"]').click()`)
  await sleep(600)
  await cdp.eval(`document.querySelector('.nav-item[data-page="workspace"]').click()`)
  await sleep(600)
  m = await probe()
  report.scenarios.push({ name: 'page-round-trip', measured: m, screenshot: await shot('04-page-round-trip'),
    problems: check('page-round-trip', m, { expectImmersive: false }) })

  // 5) Start-server flow from a stopped shell: openFrame auto-enters immersive.
  await control('running=0&immersive=0')
  await load()
  await cdp.eval(`document.getElementById('btn-start').click()`)
  await sleep(1200)
  const m5 = await probe()
  report.scenarios.push({ name: 'start-server-auto-immersive', measured: m5, screenshot: await shot('05-start-immersive'),
    problems: check('start-server-auto-immersive', m5, { expectImmersive: true }) })
  await cdp.eval(`document.getElementById('btn-exit-immersive').click()`)
  await sleep(900)
  m = await probe()
  report.scenarios.push({ name: 'start-then-exit', measured: m, screenshot: await shot('06-start-then-exit'),
    problems: check('start-then-exit', m, { expectImmersive: false }) })

  // 6) Narrow window: the frame must stay usable at min_size-ish widths.
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1000, height: 640, deviceScaleFactor: 1, mobile: false,
  })
  await sleep(700)
  m = await probe()
  report.scenarios.push({ name: 'narrow-window-after-exit', measured: m,
    screenshot: await shot('07-narrow'),
    problems: check('narrow-window-after-exit', m, { expectImmersive: false }) })
  await cdp.send('Emulation.clearDeviceMetricsOverride')

  // 7) Stop the server while immersive: the empty state must fill the frame
  //    box (it used to be height:100% against an auto-height wrapper too).
  await cdp.eval(`document.getElementById('btn-start').click()`)
  await sleep(1200)
  await cdp.eval(`document.getElementById('btn-stop').click()`)
  await sleep(900)
  m = await probe()
  const emptyProblems = [...check('stop-server-empty-state', m,
    { expectImmersive: false, expectFrame: false, expectEmpty: true })]
  if (!m.frameHidden) emptyProblems.push('iframe still visible after stop_server')
  report.failures.push(...emptyProblems)
  report.scenarios.push({ name: 'stop-server-empty-state', measured: m,
    screenshot: await shot('08-stopped'), problems: emptyProblems })

  // 8) Real core in the iframe: load the running dsh core's printed URL and
  //    verify the web UI actually renders (dsh >= 0.1.6 answers a bare URL
  //    with "authentication required" -> 401).
  const coreUrl = args.get('real-core-url')
  if (coreUrl) {
    console.error(`real core scenario against ${coreUrl.replace(/token=.*/, 'token=***')}`)
    await control('running=0&immersive=0')
    await load()
    await cdp.eval(`document.getElementById('btn-start').click()`)
    await sleep(4000)
    const m8 = await probe()
    const coreOrigin = new URL(coreUrl).origin
    const problems = [...check('real-core-workspace', m8, { expectImmersive: true })]
    const frameTree = await cdp.send('Page.getFrameTree')
    const child = (frameTree.frameTree.childFrames ?? [])
      .map(f => f.frame)
      .find(f => (f.url ?? '').startsWith(coreOrigin))
    if (!child) {
      problems.push(`no iframe loaded from ${coreOrigin}`)
    } else {
      const { executionContextId } = await cdp.send('Page.createIsolatedWorld', {
        frameId: child.id, grantUniveralAccess: false, worldName: 'dsh-probe',
      })
      const inner = await cdp.eval(`(() => {
        const root = document.querySelector('#root');
        const text = (document.body.innerText || '').trim();
        return {
          title: document.title,
          rootChildren: root ? root.children.length : -1,
          textLen: text.length,
          head: text.slice(0, 160),
          authError: /authentication required|unauthorized/i.test(text),
        };
      })()`, false, executionContextId)
      report.scenarios.push({ name: 'real-core-inner-page', measured: inner,
        screenshot: await shot('09-real-core') })
      if (inner.authError) problems.push(`core refused the UI: ${inner.head}`)
      if (inner.rootChildren <= 0) problems.push(`core UI did not mount: rootChildren=${inner.rootChildren}`)
      if (inner.textLen <= 0) problems.push('core UI rendered no text')
      console.error(`real core inner page: ${JSON.stringify(inner)}`)
    }
    report.failures.push(...problems)
    report.scenarios.push({ name: 'real-core-workspace', measured: m8, problems })
  }

  report.ok = report.failures.length === 0 && report.consoleErrors.length === 0
  fs.mkdirSync(path.dirname(outFile), { recursive: true })
  fs.writeFileSync(outFile, JSON.stringify(report, null, 2))
  console.log(JSON.stringify({
    ok: report.ok,
    failures: report.failures,
    consoleErrors: report.consoleErrors,
    summary: report.scenarios.map(s => ({
      name: s.name,
      bodyClass: s.measured.bodyClass,
      frame: s.measured.frame,
      frameWrap: s.measured.frameWrap,
      coreSize: s.measured.coreSize,
      problems: s.problems,
    })),
    out: outFile,
    shots: shotDir,
  }, null, 2))

  ws.close()
  cleanup()
  process.exit(report.ok ? 0 : 1)
}

main().catch(error => {
  console.error(`probe failed: ${error.stack || error.message}`)
  process.exit(2)
})
