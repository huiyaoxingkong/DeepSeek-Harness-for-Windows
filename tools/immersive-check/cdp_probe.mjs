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
      const details = msg.params.exceptionDetails ?? {}
      const text = [details.text, details.exception?.description ?? '']
        .filter(Boolean).join(' ').replace(/\s+/g, ' ').slice(0, 300)
      consoleErrors.push(text || 'exception')
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
    // Headless pages have nobody to answer window.confirm/prompt: an unhandled
    // dialog blocks the page forever (the preset buttons ask for confirmation).
    await cdp.eval(`window.confirm = () => true;
      window.alert = () => {};
      window.prompt = (question, fallback) => (fallback === undefined ? '' : fallback);`)
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

  // 9) Appearance (theme) system: the settings page must list the built-in
  //    themes and clicking one must actually restyle the shell.
  await control('running=0&immersive=0&onboarding=1&ui_theme=&ui_lang=zh')
  await load()
  await cdp.eval(`document.querySelector('.nav-item[data-page="settings"]').click()`)
  await sleep(1200)
  const themesBefore = await cdp.eval(`(() => {
    const box = document.getElementById('themes-list');
    const style = document.getElementById('shell-theme');
    return {
      chips: box ? box.querySelectorAll('[data-theme]').length : -1,
      empty: !!document.querySelector('#themes-list .plugin-empty'),
      bg: getComputedStyle(document.body).backgroundColor,
      styleText: style ? style.textContent.slice(0, 60) : null,
    };
  })()`)
  await cdp.eval(`(() => {
    const chip = document.querySelector('#themes-list [data-theme="builtin-light"]');
    if (chip) chip.click();
  })()`)
  await sleep(1200)
  const themesAfter = await cdp.eval(`(() => {
    const style = document.getElementById('shell-theme');
    return {
      bg: getComputedStyle(document.body).backgroundColor,
      fg: getComputedStyle(document.body).color,
      styleText: style ? style.textContent.slice(0, 80) : null,
      styleLen: style ? style.textContent.length : 0,
      active: (document.querySelector('#themes-list .theme-chip.on') || {}).dataset?.theme || '',
    };
  })()`)
  const themeProblems = []
  if (themesBefore.chips <= 0) themeProblems.push('no theme chips rendered on the settings page')
  if (themesBefore.empty) themeProblems.push('theme list still shows the loading placeholder')
  if (!themesAfter.styleText || themesAfter.styleLen < 20) {
    themeProblems.push(`theme style element has no CSS: ${JSON.stringify(themesAfter.styleText)}`)
  }
  if (!themesAfter.styleText || !themesAfter.styleText.includes('--bg')) {
    themeProblems.push('injected theme does not define CSS variables (bare path injected?)')
  }
  if (themesAfter.bg === themesBefore.bg) {
    themeProblems.push(`body background unchanged after switching theme (${themesAfter.bg})`)
  }
  if (themesAfter.active !== 'builtin-light') {
    themeProblems.push(`clicked theme not marked active: ${themesAfter.active}`)
  }
  report.scenarios.push({ name: 'appearance-themes', measured: { before: themesBefore, after: themesAfter },
    screenshot: await shot('10-theme-light'), problems: themeProblems })
  report.failures.push(...themeProblems)

  // 10) Feature click-through: walk every shell page and press every visible,
  //     enabled control, then check that the bridge methods those controls are
  //     supposed to call were actually called (and that nothing threw).
  if (args.get('feature-audit') === '1') {
    await control('running=0&immersive=0&reset_calls=1')
    await load()
    const pages = ['workspace', 'plugins', 'settings', 'update', 'logs', 'about']
    // Destructive/irreversible controls are deliberately not pressed:
    //   btn-install-app-update spawns the upgrade bootstrap
    //   btn-open-browser opens an external window (target churn)
    const skip = new Set(['btn-install-app-update', 'btn-open-browser', 'btn-quit-for-update'])
    const expected = {
      workspace: ['start_server', 'set_ui_state', 'poll_tray'],
      plugins: ['list_plugins', 'store_list', 'store_catalog', 'plugin_state', 'install_plugin'],
      settings: ['get_state', 'save_settings', 'list_providers', 'list_instances', 'set_ui_state', 'get_api_key'],
      update: ['list_core_releases', 'check_update', 'download_update', 'update_core',
               'pick_core_archive', 'import_core'],
      logs: ['read_log'],
      about: ['check_app_update', 'download_app_update', 'app_update_state', 'list_plugins'],
    }
    const clicked = {}
    const disabledControls = {}
    // Fill the form-driven controls first: pressing them with empty inputs only
    // exercises the validation branch, never the feature behind it.
    const formValues = {
      'store-name': 'audit-market',
      'store-catalog-url': 'https://example.invalid/plugins.json',
      'store-spec': '@audit/market',
      'plugin-spec': '@audit/plugin',
      'plugin-idea': 'audit idea',
      'store-search': 'audit',
    }
    for (const page of pages) {
      await cdp.eval(`document.querySelector('.nav-item[data-page="${page}"]').click()`)
      await sleep(900)
      await cdp.eval(`(() => {
        const values = ${JSON.stringify(formValues)};
        for (const [id, value] of Object.entries(values)) {
          const el = document.getElementById(id);
          if (el && 'value' in el) {
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }
        return true;
      })()`)
      const ids = await cdp.eval(`Array.from(document.querySelectorAll('#page-${page} button'))
        .map(b => b.id).filter(Boolean)`)
      clicked[page] = []
      disabledControls[page] = []
      for (const id of ids) {
        if (skip.has(id)) continue
        const state = await cdp.eval(`(() => {
          const b = document.getElementById(${JSON.stringify(id)});
          if (!b) return 'absent';
          if (b.disabled) return 'disabled';
          if (b.closest('.hidden')) return 'hidden';
          b.click();
          return 'clicked';
        })()`)
        if (state === 'clicked') clicked[page].push(id)
        else disabledControls[page].push(`${id}:${state}`)
        await sleep(220)
      }
    }
    await sleep(1500)
    const journal = await (await fetch(`http://127.0.0.1:${shellPort}/api/control/calls`)).json()
    const called = new Set(journal.calls.map(c => c.method))
    const problems = []
    // A method is only required when its control was actually pressable: some
    // controls are gated on state (btn-update needs an available update,
    // btn-import-core needs a picked file, btn-toggle-key needs a stored key),
    // and a disabled control that never fires is correct behaviour, not a gap.
    const conditional = {
      'get_api_key': ['btn-toggle-key'],
      'download_update': ['btn-update'],
      'import_core': ['btn-import-core'],
      'import_plugin': ['btn-import-plugin'],
      'import_shell_plugin': ['btn-import-shell-plugin'],
      'install_app_update': ['btn-install-app-update'],
    }
    const skippedMethods = []
    for (const page of pages) {
      for (const method of expected[page] || []) {
        if (called.has(method)) continue
        const owners = conditional[method] || []
        const wasPressed = owners.some(id => (clicked[page] || []).includes(id))
        const wasDisabled = owners.some(id => (disabledControls[page] || []).some(entry => entry.startsWith(id + ':')))
        if (owners.length > 0 && wasDisabled && !wasPressed) {
          skippedMethods.push(`${method} (control disabled by state: ${owners.join('/')})`)
          continue
        }
        problems.push(`${page}: bridge method never called: ${method}`)
      }
      if ((clicked[page] || []).length === 0) problems.push(`${page}: no control could be pressed`)
    }
    const errorScenarios = report.consoleErrors
    report.scenarios.push({
      name: 'feature-clickthrough',
      measured: { clicked, disabledControls, skippedMethods,
                  calledMethods: [...called].sort(), bridgeCalls: journal.calls.length },
      screenshot: await shot('11-feature-audit'),
      problems,
    })
    report.failures.push(...problems)
    if (errorScenarios.length > 0) {
      report.failures.push(`console errors during click-through: ${errorScenarios.slice(0, 3).join(' | ')}`)
    }

    // Cancel control: while a core update is running the progress card must
    // offer cancellation (the bridge implemented cancel_update long before the
    // UI exposed it — an unreachable feature).
    await control('update_phase=building&update_progress=0.42&update_message=audit-building&reset_calls=1')
    await load()
    await cdp.eval(`document.querySelector('.nav-item[data-page="update"]').click()`)
    await sleep(900)
    const cancelState = await cdp.eval(`(() => {
      const btn = document.getElementById('btn-cancel-update');
      const prog = document.getElementById('update-progress');
      return {
        buttonExists: !!btn,
        buttonHidden: btn ? btn.classList.contains('hidden') : null,
        buttonDisabled: btn ? btn.disabled : null,
        progressVisible: prog ? !prog.classList.contains('hidden') : null,
        message: (document.getElementById('progress-message') || {}).textContent || '',
      };
    })()`)
    await cdp.eval(`(() => { const b = document.getElementById('btn-cancel-update'); if (b && !b.disabled) b.click(); })()`)
    await sleep(900)
    const cancelJournal = await (await fetch(`http://127.0.0.1:${shellPort}/api/control/calls`)).json()
    const cancelCalled = cancelJournal.calls.some(c => c.method === 'cancel_update')
    const cancelProblems = []
    if (!cancelState.buttonExists) cancelProblems.push('no cancel control on the update page')
    if (cancelState.buttonHidden) cancelProblems.push('cancel control hidden while an update runs')
    if (cancelState.progressVisible === false) cancelProblems.push('progress card hidden while an update runs')
    if (!cancelCalled) cancelProblems.push('cancel_update was never called by the cancel control')
    report.failures.push(...cancelProblems)
    report.scenarios.push({ name: 'update-cancel-control', measured: { ...cancelState, cancelCalled },
      screenshot: await shot('12-update-cancel'), problems: cancelProblems })
    await control('update_idle=1')

    // First-run onboarding: shown when the instance is not onboarded, steps
    // forward, and completing it persists the flag.
    await control('onboarding=0&reset_calls=1')
    await load()
    const onbStart = await cdp.eval(`(() => {
      const box = document.getElementById('onboarding');
      const active = document.querySelector('.onb-step.active');
      return { visible: box ? !box.classList.contains('hidden') : null,
               step: active ? Number(active.dataset.step) : -1,
               next: (document.getElementById('onb-next') || {}).textContent || '' };
    })()`)
    await cdp.eval(`document.getElementById('onb-next').click()`)
    await sleep(400)
    await cdp.eval(`document.getElementById('onb-next').click()`)
    await sleep(400)
    const onbMid = await cdp.eval(`(() => {
      const active = document.querySelector('.onb-step.active');
      return { step: active ? Number(active.dataset.step) : -1 };
    })()`)
    await cdp.eval(`document.getElementById('onb-skip').click()`)
    await sleep(700)
    const onbEnd = await cdp.eval(`(() => {
      const box = document.getElementById('onboarding');
      return { hidden: box ? box.classList.contains('hidden') : null };
    })()`)
    const onbJournal = await (await fetch(`http://127.0.0.1:${shellPort}/api/control/calls`)).json()
    const onbProblems = []
    if (onbStart.visible !== true) onbProblems.push('onboarding overlay not shown on a fresh instance')
    if (onbStart.step !== 0) onbProblems.push(`onboarding did not start at step 0 (${onbStart.step})`)
    if (!(onbMid.step > onbStart.step)) onbProblems.push(`next did not advance the step (${onbMid.step})`)
    if (onbEnd.hidden !== true) onbProblems.push('onboarding overlay not dismissed')
    if (!onbJournal.calls.some(c => c.method === 'set_onboarding_done')) {
      onbProblems.push('finishing onboarding did not persist via set_onboarding_done')
    }
    report.failures.push(...onbProblems)
    report.scenarios.push({ name: 'onboarding-flow', measured: { onbStart, onbMid, onbEnd },
      screenshot: await shot('13-onboarding'), problems: onbProblems })

    // Language switch: picking English must translate the shell and persist.
    await control('onboarding=1&ui_lang=zh&reset_calls=1')
    await load()
    const beforeLang = await cdp.eval(`document.querySelector('.nav-item[data-page="plugins"]').textContent.trim()`)
    await cdp.eval(`(() => {
      const sel = document.getElementById('lang-select');
      sel.value = 'en';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    })()`)
    await sleep(900)
    const afterLang = await cdp.eval(`document.querySelector('.nav-item[data-page="plugins"]').textContent.trim()`)
    const langDiag = await cdp.eval(`({
      applyI18n: typeof applyI18n,
      t: typeof window.t,
      lang: window.__i18nLang,
      prevLang: window.__i18nPrevLang,
      zhKeys: Object.keys(window.__i18nKeys && window.__i18nKeys.zh || {}).slice(0, 4),
      hasPluginsKey: !!(window.__i18nKeys && window.__i18nKeys.zh && window.__i18nKeys.zh['插件']),
      selectValue: (document.getElementById('lang-select') || {}).value,
      i18nScriptLoaded: Array.from(document.scripts).map(s => s.src.split('/').pop()),
    })`)
    const langJournal = await (await fetch(`http://127.0.0.1:${shellPort}/api/control/calls`)).json()
    const langProblems = []
    if (beforeLang === afterLang) langProblems.push(`nav label unchanged after switching to English: ${afterLang}`)
    if (!afterLang.match(/Plugins/i)) langProblems.push(`nav label not translated: ${afterLang}`)
    if (!langJournal.calls.some(c => c.method === 'set_ui_state'
        && (c.payload || {}).lang === 'en')) {
      langProblems.push('language choice was not persisted (set_ui_state lang=en)')
    }
    report.failures.push(...langProblems)
    report.scenarios.push({ name: 'language-switch', measured: { beforeLang, afterLang, langDiag },
      screenshot: await shot('14-language'), problems: langProblems })
    await cdp.eval(`(() => {
      const sel = document.getElementById('lang-select');
      sel.value = 'zh';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    })()`)
    await sleep(600)
    await control('ui_lang=zh')
  }

  // 11) Switching tabs while the server is starting: the shell must not force
  //     fullscreen over whatever page the user moved to (that stretched the
  //     page to 100vh, hid the sidebar and took the exit-fullscreen button
  //     with the hidden workspace page, leaving no way back).
  await control('running=0&immersive=0&onboarding=1&ui_lang=zh&start_delay=3')
  await load()
  await cdp.eval(`document.getElementById('btn-start').click()`)
  await sleep(600)
  await cdp.eval(`document.querySelector('.nav-item[data-page="settings"]').click()`)
  await sleep(4200)   // let start_server answer and openFrame run
  const startupTab = await cdp.eval(`(() => {
    const rect = el => { const b = el.getBoundingClientRect();
      return { w: Math.round(b.width), h: Math.round(b.height) }; };
    const page = document.getElementById('page-settings');
    const sidebar = document.querySelector('.sidebar');
    const exit = document.getElementById('btn-exit-immersive');
    const content = document.querySelector('.content');
    return {
      bodyClass: document.body.className,
      immersivePersisted: null,
      settingsVisible: !page.classList.contains('hidden'),
      workspaceVisible: !document.getElementById('page-workspace').classList.contains('hidden'),
      navActive: (document.querySelector('.nav-item.active') || {}).dataset?.page || '',
      sidebarDisplay: getComputedStyle(sidebar).display,
      settingsHeight: rect(page).h,
      viewportHeight: innerHeight,
      contentPadding: getComputedStyle(content).padding,
      contentOverflowY: getComputedStyle(content).overflowY,
      pageHeadVisible: (() => {
        const head = page.querySelector('.page-head');
        return head ? head.getClientRects().length > 0 : false;
      })(),
      exitVisible: exit ? exit.getClientRects().length > 0 : false,
      frameHidden: document.getElementById('dsh-frame').classList.contains('hidden'),
    };
  })()`)
  const startTabProblems = []
  if (startupTab.bodyClass.includes('immersive')) {
    startTabProblems.push('still forced into fullscreen after switching tabs during start')
  }
  if (!startupTab.settingsVisible) startTabProblems.push('the page the user switched to is not shown')
  if (startupTab.workspaceVisible) startTabProblems.push('workspace page shown although the user switched away')
  if (startupTab.sidebarDisplay === 'none') startTabProblems.push('sidebar hidden: no way back to other pages')
  if (startupTab.sidebarDisplay === 'none' && !startupTab.exitVisible) {
    startTabProblems.push('no visible control returns to the shell (sidebar hidden, no exit button)')
  }
  if (startupTab.frameHidden) startTabProblems.push('iframe not loaded although start_server succeeded')
  // "异常放大" = full-bleed rendering: padding stripped, content pane locked
  // (not scrollable) and the page header hidden while not in fullscreen.
  if (startupTab.contentPadding === '0px') {
    startTabProblems.push('content padding removed (page rendered full-bleed / "enlarged")')
  }
  if (startupTab.contentOverflowY !== 'auto') {
    startTabProblems.push(`content pane not scrollable (overflow-y: ${startupTab.contentOverflowY})`)
  }
  if (!startupTab.pageHeadVisible) {
    startTabProblems.push('page header hidden although the shell is not in fullscreen')
  }
  report.failures.push(...startTabProblems)
  report.scenarios.push({ name: 'startup-tab-switch', measured: startupTab,
    screenshot: await shot('15-startup-tab-switch'), problems: startTabProblems })

  // 11b) The mirror case: leaving the workspace while fullscreen must restore
  //      the shell chrome (the sidebar is hidden in fullscreen, so a page
  //      change must drop fullscreen or the user is stranded there).
  await control('start_delay=0&running=1&immersive=1&onboarding=1')
  await load()
  const immersiveBefore = await cdp.eval(`document.body.classList.contains('immersive')`)
  await cdp.eval(`showPage('plugins')`)
  await sleep(500)
  const afterPageChange = await cdp.eval(`(() => {
    const sidebar = document.querySelector('.sidebar');
    return {
      immersive: document.body.classList.contains('immersive'),
      sidebarDisplay: getComputedStyle(sidebar).display,
      pluginsVisible: !document.getElementById('page-plugins').classList.contains('hidden'),
    };
  })()`)
  const leaveProblems = []
  if (!immersiveBefore) leaveProblems.push('scenario precondition failed: not in fullscreen')
  if (afterPageChange.immersive) leaveProblems.push('page change while fullscreen kept fullscreen on')
  if (afterPageChange.sidebarDisplay === 'none') {
    leaveProblems.push('sidebar still hidden after leaving the workspace page')
  }
  if (!afterPageChange.pluginsVisible) leaveProblems.push('target page not shown')
  report.failures.push(...leaveProblems)
  report.scenarios.push({ name: 'leave-workspace-while-fullscreen',
    measured: { immersiveBefore, ...afterPageChange }, problems: leaveProblems })
  await control('start_delay=0&running=0&immersive=0&ui_theme=&ui_lang=zh')

  // 12) Close confirmation: pressing the window X (the bridge reports it via
  //     poll_tray) must open a dialog offering cancel / minimize to tray /
  //     close app, and the chosen action must reach the bridge.
  await control('running=1&immersive=0&onboarding=1&ui_lang=zh&reset_calls=1&close_request=1')
  await load()
  await sleep(1400)   // poll interval is 800 ms
  const closeDialog = await cdp.eval(`(() => {
    const box = document.getElementById('close-confirm-dialog');
    return {
      visible: box ? !box.classList.contains('hidden') : null,
      buttons: ['btn-close-cancel', 'btn-close-tray', 'btn-close-quit']
        .map(id => !!document.getElementById(id)),
      title: (box || {}).querySelector ? (box.querySelector('h2') || {}).textContent : '',
      settingCheckbox: !!document.getElementById('close-confirm'),
    };
  })()`)
  const closeProblems = []
  if (closeDialog.visible !== true) closeProblems.push('close confirmation dialog not shown for a close request')
  if (closeDialog.buttons.some(v => !v)) closeProblems.push('close dialog is missing one of its actions')
  if (!closeDialog.settingCheckbox) closeProblems.push('no "confirm before closing" setting in the settings page')

  // Cancel keeps the app open and tells the bridge.
  await cdp.eval(`document.getElementById('btn-close-cancel').click()`)
  await sleep(700)
  const afterCancel = await cdp.eval(`document.getElementById('close-confirm-dialog').classList.contains('hidden')`)
  let journal = await (await fetch(`http://127.0.0.1:${shellPort}/api/control/calls`)).json()
  if (afterCancel !== true) closeProblems.push('cancel did not close the dialog')
  if (!journal.calls.some(c => c.method === 'cancel_close')) {
    closeProblems.push('cancel did not reach cancel_close')
  }

  // Minimize to tray keeps the core running.
  await control('close_request=1&reset_calls=1')
  await sleep(1400)
  await cdp.eval(`document.getElementById('btn-close-tray').click()`)
  await sleep(700)
  journal = await (await fetch(`http://127.0.0.1:${shellPort}/api/control/calls`)).json()
  if (!journal.calls.some(c => c.method === 'hide_to_tray')) {
    closeProblems.push('minimize-to-tray did not reach hide_to_tray')
  }

  // Close app must go through quit_app (which saves settings and stops the core).
  await control('close_request=1&reset_calls=1')
  await sleep(1400)
  await cdp.eval(`document.getElementById('btn-close-quit').click()`)
  await sleep(700)
  journal = await (await fetch(`http://127.0.0.1:${shellPort}/api/control/calls`)).json()
  if (!journal.calls.some(c => c.method === 'quit_app')) {
    closeProblems.push('close-app did not reach quit_app')
  }
  report.failures.push(...closeProblems)
  report.scenarios.push({ name: 'close-confirmation', measured: { closeDialog, afterCancel },
    screenshot: await shot('16-close-confirm'), problems: closeProblems })
  await control('close_request=0&running=0&immersive=0&ui_theme=&ui_lang=zh')

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
