/*
  DeepSeek Harness Desktop — 外壳 UI 逻辑
  与 Python 桥的通信方式：
    1) pywebview 环境: window.pywebview.api.<方法>(...)  (异步 Promise)
    2) 普通浏览器环境: GET /api/bridge/<方法> 或 POST /api/bridge/<方法> (JSON body)
  两种方式在此统一为 callApi()，您可以自由扩展界面与功能。
*/
"use strict";

function callApi(method, payload) {
  payload = payload || {};
  if (window.pywebview && window.pywebview.api && window.pywebview.api[method]) {
    const hasArgs = Object.keys(payload).length > 0;
    return Promise.resolve(
      hasArgs ? window.pywebview.api[method](payload) : window.pywebview.api[method]());
  }
  return fetch(`/api/bridge/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(j => j.data);
}

/* pywebview 注入 js_api 是异步的；启动早期的调用要等桥就绪，否则
   会落到 HTTP 回退路径。浏览器调试模式（无 pywebview）直接走 fetch。 */
function waitBridgeReady(timeoutMs) {
  if (!window.pywebview) return Promise.resolve();
  const deadline = Date.now() + (timeoutMs || 8000);
  return new Promise(resolve => {
    (function poll() {
      if (window.pywebview.api || Date.now() >= deadline) return resolve();
      setTimeout(poll, 100);
    })();
  });
}

const $ = id => document.getElementById(id);

/* ---------------- navigation ---------------- */

const uiPages = ["workspace", "plugins", "settings", "update", "logs", "about"];

function showPage(name) {
  uiPages.forEach(p => {
    $("page-" + p).classList.toggle("hidden", p !== name);
  });
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.page === name);
  });
  if (name === "logs") refreshLog();
  if (name === "update") renderLocalUpdate();   // 仅显示本地版本，不自动检查
  if (name === "plugins") { refreshPlugins(); refreshShellPlugins(); }
  if (name === "settings") loadSettings();      // 进入设置页时重新加载（含 API Key 掩码）
  if (name === "about") checkAppUpdate(false);  // 进入关于页时静默检查（带缓存）
  if (shellPageHooks[name]) { try { shellPageHooks[name](); } catch (e) { console.error("[ShellPlugin] onShow 失败", e); } }
}

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});

/* ---------------- server control ---------------- */

async function refreshState() {
  const state = await callApi("get_state");
  const { app, server, update } = state;
  const dot = $("sidebar-status");
  const running = server.running;
  dot.classList.toggle("on", running);
  dot.classList.toggle("err", !server.coreReady);
  $("sidebar-status-text").textContent = running
    ? `${t("status.running")} :${server.port}` : (server.coreReady ? t("status.stopped") : t("status.noCore"));

  $("btn-start").hidden = running;
  $("btn-stop").hidden = !running;
  $("btn-restart").hidden = !running;
  $("btn-open-browser").hidden = !running;

  $("about-app-version").textContent = app.version || "-";
  $("about-port").textContent = String(server.port);
  $("about-data-dir").textContent = app.dataDir || "-";
  $("about-data-dir").title = app.dshHome || "";
  renderHealth(app.health);
  return state;
}

function renderHealth(h) {
  const view = $("health-view");
  if (!view || !h) return;
  if (h.skipped) {
    view.textContent = "跳过：未检测到 web profile（首次启动或数据为空）";
  } else if (h.ok) {
    view.textContent = `✅ ${h.ts || ""} 插件层与数据目录验证通过（dump-config 退出码 0）`;
  } else {
    view.textContent = `⚠️ ${h.ts || ""} 验证异常：${h.error || ("退出码 " + h.exit)}${h.tail ? " · " + h.tail : ""}`;
  }
}

function showBanner(type, text) {
  const b = $("server-banner");
  b.className = "banner " + type;
  b.textContent = text;
  b.classList.remove("hidden");
  setTimeout(() => b.classList.add("hidden"), 6000);
}

function setFrameLoading(on, text) {
  const empty = $("frame-empty");
  const title = empty.querySelector(".empty-title");
  const sub = empty.querySelector(".empty-sub");
  if (on) {
    title.textContent = t("loading.title");
    sub.textContent = text || t("loading.hint");
    if (!empty.querySelector(".spinner")) {
      const sp = document.createElement("div");
      sp.className = "spinner";
      empty.insertBefore(sp, title);
    }
  } else {
    title.textContent = t("empty.title");
    sub.textContent = t("empty.sub");
    const sp = empty.querySelector(".spinner");
    if (sp) sp.remove();
  }
}

async function startServer() {
  setFrameLoading(true);
  try {
    const res = await callApi("start_server");
    if (res.ok) {
      showBanner("ok", res.message || "服务已启动");
      await refreshState();
      openFrame($("dsh-frame"), `http://127.0.0.1:${res.port || await getPort()}`);
    } else {
      showBanner("err", res.message || "启动失败");
    }
  } finally {
    setFrameLoading(false);
  }
}

async function getPort() {
  const state = await refreshState();
  return state.server.port;
}

function stopServer() {
  return callApi("stop_server").then(r => {
    showBanner(r.ok ? "ok" : "err", r.message);
    $("dsh-frame").classList.add("hidden");
    $("frame-empty").classList.remove("hidden");
    exitImmersive();
    return refreshState();
  });
}

function restartServer() {
  return callApi("restart_server").then(r => {
    showBanner(r.ok ? "ok" : "err", r.message);
    if (r.ok) return startServer();
    return refreshState();
  });
}

function openFrame(iframe, url) {
  iframe.src = url;
  iframe.classList.remove("hidden");
  $("frame-empty").classList.add("hidden");
  setImmersive(true, false);
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
}

/* 沉浸模式：记住上次状态（config.json -> ui_state.immersive），
   退出时回到工作台页；切换不再重载 iframe。 */
function setImmersive(on, persist) {
  document.body.classList.toggle("immersive", on);
  if (persist !== false) {
    callApi("set_ui_state", { immersive: on }).catch(() => {});
  }
}

function exitImmersive() {
  setImmersive(false);
  document.querySelectorAll(".nav-item").forEach(b => {
    b.classList.toggle("active", b.dataset.page === "workspace");
  });
}

$("btn-immersive").addEventListener("click", () => {
  setImmersive(!document.body.classList.contains("immersive"));
});

$("btn-exit-immersive").addEventListener("click", exitImmersive);

$("btn-start").addEventListener("click", startServer);
$("btn-stop").addEventListener("click", stopServer);
$("btn-restart").addEventListener("click", restartServer);
$("btn-open-browser").addEventListener("click", () => {
  refreshState().then(s => window.open(s.server.url, "_blank"));
});

/* ---------------- settings ---------------- */

let apiKeyMasked = "";
let apiKeyRevealed = false;   // 明文可见状态
let apiKeyEditing = false;    // 更换密钥编辑模式

function setKeyMode(mode) {
  const input = $("api-key");
  if (mode === "masked") {
    apiKeyEditing = false;
    apiKeyRevealed = false;
    input.value = apiKeyMasked;
    input.type = "password";
    input.readOnly = true;
    $("btn-toggle-key").disabled = !apiKeyMasked;
    $("btn-toggle-key").textContent = "显示";
    $("btn-change-key").textContent = "更换";
  } else {
    apiKeyEditing = true;
    apiKeyRevealed = false;
    input.value = "";
    input.type = "password";
    input.readOnly = false;
    $("btn-toggle-key").disabled = false;
    $("btn-toggle-key").textContent = "显示";
    $("btn-change-key").textContent = "取消";
    input.focus();
  }
}

async function loadSettings() {
  const state = await refreshState();
  apiKeyMasked = state.app.apiKeyMasked || "";
  setKeyMode("masked");
  $("base-url").value = state.app.baseUrl || "";
  $("port").value = String(state.app.port);
  $("auto-start").checked = state.app.autoStart;
  $("open-browser").checked = state.app.openBrowser;
  $("close-to-tray").checked = state.app.closeToTray;
  $("auto-launch").checked = state.app.autoLaunch;
  $("proxy-url").value = state.app.proxyUrl || "";
  $("npm-registry").value = state.app.npmRegistry || "";
  $("github-mirror").value = state.app.githubMirror || "";
  refreshProviders();
  renderTools(state.tools);
  renderThemeList();
  refreshInstances();
  if ($("lang-select")) $("lang-select").value = window.__i18nLang || "zh";
}

/* E4: 本机实例面板 */
async function refreshInstances() {
  const box = $("instances-list");
  if (!box) return;
  const data = await callApi("list_instances").catch(() => null);
  const list = (data && data.instances) || [];
  box.innerHTML = list.length
    ? list.map(i => `
      <div class="plugin-row"><div class="plugin-info">
        <div class="plugin-name">PID ${esc(i.pid)}
          ${i.isSelf ? '<span class="tag bundle">本实例</span>' : ""}
          ${i.port ? `<span class="tag plain">端口 ${esc(i.port)}</span>` : ""}
        </div>
        <div class="plugin-meta">${esc(i.path)}</div>
      </div></div>`).join("")
    : '<div class="plugin-empty">未检测到运行中的实例</div>';
}

async function setLang(lang, persist) {
  window.__i18nLang = lang === "en" ? "en" : "zh";
  if (typeof applyI18n === "function") applyI18n();
  if (persist !== false) {
    await callApi("set_ui_state", { lang: window.__i18nLang }).catch(() => {});
  }
  await loadSettings();
  renderThemeList();
}

$("lang-select") && $("lang-select").addEventListener("change", () => {
  setLang($("lang-select").value);
});

function renderTools(tools) {
  const box = $("tools-list");
  if (!box || !tools) return;
  const flavor = tools.flavor === "lazy" ? t("tools.lazy") : t("tools.minimal");
  const rows = [
    { key: "node", label: "Node.js", note: "dsh 核心与插件安装必需" },
    { key: "git", label: "Git", note: "git 图形插件 / 插件 git 源安装" },
    { key: "bash", label: "Git Bash", note: "dsh-liangshen 的 bash 工具" },
  ];
  const labels = { bundled: t("tools.bundled"), system: t("tools.system"), missing: t("tools.missing") };
  const cls = { bundled: "bundle", system: "builtin", missing: "miss" };
  box.innerHTML = `<div class="plugin-row"><div class="plugin-info">
      <div class="plugin-name">${esc(flavor)}</div></div></div>` +
    rows.map(r => {
      const t = tools[r.key] || { mode: "missing", path: "" };
      return `<div class="plugin-row"><div class="plugin-info">
        <div class="plugin-name">${esc(r.label)}
          <span class="tag ${cls[t.mode]}">${labels[t.mode]}</span></div>
        <div class="plugin-meta">${esc(t.path || "未检测到")} · ${esc(r.note)}</div>
      </div></div>`;
    }).join("");
}

async function refreshProviders() {
  const data = await callApi("list_providers");
  const box = $("providers-list");
  const list = data && data.providers ? data.providers : [];
  const note = data && data.appKeySet
    ? '<span class="tag bundle">应用 API Key 已注入（环境变量）</span>' : "";
  if (!list.length) {
    box.innerHTML = `<div class="plugin-empty">未配置提供方（${note || "可先在 Web 界面「设置 → 模型」中添加，或使用上方 API Key 字段"}）</div>`;
    return;
  }
  box.innerHTML = list.map(p => `
    <div class="plugin-row">
      <div class="plugin-info">
        <div class="plugin-name">${esc(p.id)}
          <span class="tag ${p.credentialSet ? "bundle" : "plain"}">${p.credentialSet ? "凭据已配置" : "凭据缺失"}</span>
        </div>
        <div class="plugin-meta">${esc(p.baseURL || "(默认地址)")} · ${esc(p.api || "")} · ${p.modelCount} 个模型</div>
        ${p.models.length ? `<div class="plugin-meta">${p.models.map(esc).join("、")}</div>` : ""}
      </div>
    </div>`).join("") + (note ? `<div style="margin-top:8px;">${note}</div>` : "");
}

$("btn-refresh-providers").addEventListener("click", refreshProviders);

/* C3: 一键填入 dsh-web 全家桶聚合包 */
$("preset-web-all").addEventListener("click", () => {
  $("plugin-spec").value = "@linxin666/dsh-web-all";
  $("plugin-spec").focus();
});

$("btn-change-key").addEventListener("click", () => {
  setKeyMode(apiKeyEditing ? "masked" : "editing");
});

$("auto-launch").addEventListener("change", async () => {
  const res = await callApi("set_auto_launch", { enabled: $("auto-launch").checked });
  if (!res.ok) {
    $("auto-launch").checked = !$("auto-launch").checked;
    alert(res.message || "设置开机自启失败");
  }
});

$("btn-toggle-key").addEventListener("click", async () => {
  const input = $("api-key");
  if (apiKeyRevealed) {
    input.type = "password";
    $("btn-toggle-key").textContent = "显示";
    apiKeyRevealed = false;
    if (!apiKeyEditing) input.value = apiKeyMasked;
    return;
  }
  if (!apiKeyEditing) {
    const plain = await callApi("get_api_key").catch(() => "");
    if (plain) input.value = plain;
  }
  input.type = "text";
  $("btn-toggle-key").textContent = "隐藏";
  apiKeyRevealed = true;
  setTimeout(() => input.setSelectionRange(0, 0), 0);
});

/* 密钥防复制：禁止复制/剪切/拖拽出去与右键菜单；保留粘贴（更换密钥时
   可从别处粘贴新值）。 */
(function protectKeyInput() {
  const input = $("api-key");
  input.addEventListener("copy", e => e.preventDefault());
  input.addEventListener("cut", e => e.preventDefault());
  input.addEventListener("contextmenu", e => e.preventDefault());
  input.addEventListener("selectstart", e => e.preventDefault());
  input.addEventListener("select", () => input.setSelectionRange(0, 0));
  input.addEventListener("focus", () => setTimeout(() => input.setSelectionRange(0, 0), 0));
  input.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && ["c", "x", "a"].includes(e.key.toLowerCase())) {
      e.preventDefault();
    }
  });
  input.addEventListener("dragstart", e => e.preventDefault());
  input.addEventListener("drop", e => e.preventDefault());
})();

$("btn-save-settings").addEventListener("click", async () => {
  const keyValue = $("api-key").value;
  // 编辑模式：输入内容即新密钥（空串 = 清除）；掩码模式：未修改（值=掩码）→ null 保留
  let api_key;
  if (apiKeyEditing) {
    api_key = keyValue;
  } else {
    api_key = keyValue === apiKeyMasked ? null : keyValue;
  }
  await callApi("save_settings", {
    api_key: api_key,
    base_url: $("base-url").value,
    port: parseInt($("port").value, 10) || 3080,
    auto_start: $("auto-start").checked,
    open_browser: $("open-browser").checked,
    close_to_tray: $("close-to-tray").checked,
    proxy_url: $("proxy-url").value,
    npm_registry: $("npm-registry").value,
    github_mirror: $("github-mirror").value,
  });
  const toast = $("save-toast");
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1600);
  await loadSettings();
});

/* ---------------- plugins ---------------- */

function showBannerEl(el, type, text) {
  el.className = "banner " + type;
  el.textContent = text;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 6000);
}

let pluginPollTimer = null;

async function refreshPlugins() {
  const [data, storeData, catalog] = await Promise.all([
    callApi("list_plugins"),
    callApi("store_list"),
    callApi("store_catalog"),
  ]);
  renderPlugins(data);
  renderStore(storeData);
  storeState.data = catalog;
  renderCatalog();
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderPlugins(data) {
  const list = $("plugin-list");
  const snapshot = JSON.stringify(data || {});
  if (list.dataset.snapshot === snapshot) return;  // 数据未变化，不重建 DOM
  list.dataset.snapshot = snapshot;
  if (!data || !data.plugins || !data.plugins.length) {
    list.innerHTML = '<div class="plugin-empty">暂无插件，使用上方输入框安装。</div>';
    $("plugin-count").textContent = "";
    return;
  }
  $("plugin-count").textContent = `(${data.plugins.length})`;
  list.innerHTML = "";
  for (const p of data.plugins) {
    const row = document.createElement("div");
    row.className = "plugin-row";
    const tag = p.builtin ? "内置" : (p.enabled ? "已启用" : "已停用");
    const tagCls = p.builtin ? "builtin" : (p.enabled ? "bundle" : "plain");
    const actions = [];
    if (!p.builtin) {
      if (p.enabled) {
        actions.push(`<button class="btn small" data-act="disable" data-name="${esc(p.name)}">停用</button>`);
      } else {
        actions.push(`<button class="btn small" data-act="enable" data-name="${esc(p.name)}">启用</button>`);
      }
      actions.push(`<button class="btn small danger" data-act="remove" data-name="${esc(p.name)}">卸载</button>`);
    }
    row.innerHTML = `
      <div class="plugin-info">
        <div class="plugin-name">${esc(p.name)}<span class="tag ${tagCls}">${tag}</span></div>
        <div class="plugin-meta">版本 ${esc(p.version || "-")}${p.spec ? " · " + esc(p.spec) : ""}</div>
      </div>
      <div class="plugin-actions">${actions.join("")}</div>`;
    list.appendChild(row);
  }
  list.querySelectorAll("[data-act]").forEach(btn => {
    btn.addEventListener("click", () => {
      const act = btn.dataset.act;
      const name = btn.dataset.name;
      if (act === "remove" && !confirm(`确认卸载插件 ${name}？`)) return;
      callApi({
        remove: "remove_plugin", enable: "set_plugin_enabled",
        disable: "set_plugin_enabled",
      }[act], {
        name: name,
        enabled: act === "enable",
      }).then(res => {
        showBannerEl($("plugin-banner"), res.ok ? "ok" : "err",
          res.message || (res.ok ? "操作已开始" : "操作失败"));
        if (act !== "remove") refreshPlugins();
      });
    });
  });
}

/* ---------------- store catalog (shell store) ---------------- */

const storeState = { data: null, query: "", cat: "", source: "", visible: 50 };

function renderCatalog() {
  const box = $("store-catalog");
  const st = storeState;
  const data = st.data;

  const srcsBox = $("store-srcs");
  const srcKey = data && data.ok ? JSON.stringify((data.sources || []).map(s => s.name)) : "";
  if (srcKey && srcsBox.dataset.src !== srcKey) {
    srcsBox.dataset.src = srcKey;
    const chips = [["", "全部"]].concat((data.sources || []).map(s => [s.name, s.label]));
    srcsBox.innerHTML = chips.map(([id, label]) =>
      `<button class="cat ${st.source === id ? "on" : ""}" data-src="${esc(id)}">${esc(label)}</button>`).join("");
    srcsBox.querySelectorAll("[data-src]").forEach(b => {
      b.addEventListener("click", () => {
        storeState.source = b.dataset.src;
        storeState.visible = 50;
        renderCatalog();
      });
    });
  }

  const catsBox = $("store-cats");
  const catKey = data && data.ok ? (data.updated || "") : "";
  if (catKey && catsBox.dataset.src !== catKey) {
    catsBox.dataset.src = catKey;
    const cats = data.categories || {};
    const chips = [["", "全部"]].concat(Object.keys(cats).map(id => {
      const c = cats[id] || {};
      return [id, c.zh || c.en || id];
    }));
    catsBox.innerHTML = chips.map(([id, label]) =>
      `<button class="cat ${st.cat === id ? "on" : ""}" data-cat="${esc(id)}">${esc(label)}</button>`).join("");
    catsBox.querySelectorAll("[data-cat]").forEach(b => {
      b.addEventListener("click", () => {
        storeState.cat = b.dataset.cat;
        storeState.visible = 50;
        renderCatalog();
      });
    });
  }

  if (!data) {
    box.innerHTML = '<div class="plugin-empty">目录加载中…</div>';
    $("btn-store-more").hidden = true;
    return;
  }
  if (!data.ok) {
    box.innerHTML = `<div class="plugin-empty">${esc(data.message || "目录加载失败")}</div>`;
    $("btn-store-more").hidden = true;
    return;
  }
  const merged = !st.source;
  const q = st.query.trim().toLowerCase();
  const filtered = (data.plugins || []).filter(p => {
    if (st.source && p.sourceName !== st.source) return false;
    if (st.cat && p.category !== st.cat) return false;
    if (!q) return true;
    return (p.name + " " + p.owner + " " + p.description + " " + p.npm)
      .toLowerCase().includes(q);
  });
  const shown = filtered.slice(0, st.visible);
  if (!shown.length) {
    box.innerHTML = '<div class="plugin-empty">没有匹配的插件。</div>';
    $("btn-store-more").hidden = true;
    return;
  }
  box.innerHTML = "";
  for (const p of shown) {
    const card = document.createElement("div");
    card.className = "plugin-card";
    const pill = p.installed
      ? (p.enabled ? '<span class="store-pill on">已启用</span>'
                   : '<span class="store-pill off">已停用</span>')
      : '<span class="store-pill miss">未安装</span>';
    const ver = p.version ? `<span class="store-ver">v${esc(p.version)}</span>` : "";
    const srcTag = merged && p.sourceLabel
      ? (p.sourceHomepage
         ? `<a class="pc-src" href="${esc(p.sourceHomepage)}" target="_blank" title="来源 ${esc(p.sourceLabel)}">${esc(p.sourceLabel)}</a>`
         : `<span class="pc-src">${esc(p.sourceLabel)}</span>`)
      : "";
    const actions = [];
    if (p.installed) {
      actions.push(`<button class="btn small" data-act="update" data-name="${esc(p.name)}">更新</button>`);
      actions.push(`<button class="btn small danger" data-act="uninstall" data-name="${esc(p.name)}">卸载</button>`);
    } else {
      actions.push(`<button class="btn small primary" data-act="install" data-name="${esc(p.name)}">安装</button>`);
    }
    const byline = [esc(p.owner || "?")];
    if (p.stars) byline.push(`⭐ ${p.stars}`);
    if (p.downloads) byline.push(`下载 ${p.downloads}`);
    if (p.added) byline.push(p.added);
    card.innerHTML = `
      <div class="pc-head">
        <div class="pc-av">${esc((p.name || "?").charAt(0).toUpperCase())}</div>
        <div class="pc-id">
          <div class="pc-name">${esc(p.name)}
            ${p.repo ? `<a class="pc-repo" href="${esc(p.repo)}" target="_blank" title="${esc(p.repo)}">↗</a>` : ""}
            ${srcTag}${pill}${ver}</div>
          <div class="pc-byline">${byline.join(" · ")}</div>
        </div>
        <div class="pc-actions">${actions.join("")}</div>
      </div>
      ${p.description ? `<div class="pc-desc">${esc(p.description)}</div>` : ""}`;
    box.appendChild(card);
  }
  const errs = data.errors || [];
  box.querySelector(".store-src-warn")?.remove();
  if (errs.length) {
    const warn = document.createElement("div");
    warn.className = "banner err store-src-warn";
    warn.style.marginBottom = "10px";
    warn.textContent = "部分目录加载失败：" + errs.join("；");
    box.prepend(warn);
  }
  $("btn-store-more").hidden = shown.length >= filtered.length;
}

$("store-search").addEventListener("input", e => {
  storeState.query = e.target.value;
  storeState.visible = 50;
  renderCatalog();
});

$("btn-store-more").addEventListener("click", () => {
  storeState.visible += 50;
  renderCatalog();
});

$("store-catalog").addEventListener("click", e => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  const name = btn.dataset.name;
  if (act === "uninstall" && !confirm(`确认卸载插件 ${name}？`)) return;
  callApi({
    install: "store_install",
    update: "store_update",
    uninstall: "store_uninstall",
  }[act], { name: name }).then(res => {
    showBannerEl($("plugin-banner"), res.ok ? "ok" : "err",
      res.message || (res.ok ? "操作已开始" : "操作失败"));
    if (res.ok) {
      $("plugin-output-card").classList.remove("hidden");
      startPluginPoll();
    }
  });
});

/* ---------------- store sources ---------------- */

function renderStore(data) {
  const list = $("store-list");
  const snapshot = JSON.stringify(data || {});
  if (list.dataset.snapshot === snapshot) return;  // 数据未变化，不重建 DOM
  list.dataset.snapshot = snapshot;

  const preseed = (data && data.preseed) || {};
  const banner = $("store-preseed-banner");
  if (preseed.phase === "running") {
    banner.className = "banner info";
    banner.textContent = preseed.message || "内置商店正在后台预装…";
    banner.classList.remove("hidden");
    startPluginPoll();  // 预装走插件操作通道，轮询其进度输出
  } else if (preseed.phase === "failed") {
    banner.className = "banner err";
    banner.textContent = preseed.message || "内置商店预装失败。";
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }

  const sources = (data && data.sources) || [];
  if (!sources.length) {
    list.innerHTML = '<div class="plugin-empty">暂无商店源，可在下方添加。</div>';
    return;
  }
  list.innerHTML = "";
  for (const s of sources) {
    const row = document.createElement("div");
    row.className = "store-row";
    const pill = s.enabled
      ? '<span class="store-pill on">已启用</span>'
      : (s.installed ? '<span class="store-pill off">已停用</span>'
                     : '<span class="store-pill miss">未安装</span>');
    const builtinTag = s.builtin ? '<span class="tag builtin">内置</span>' : "";
    const ver = s.version ? `<span class="store-ver">v${esc(s.version)}</span>` : "";
    const bylineParts = [];
    if (s.homepage) {
      bylineParts.push(`<a class="store-src" href="${esc(s.homepage)}" target="_blank" title="来源主页">来源 ${esc(s.homepage)}</a>`);
    } else if (s.spec) {
      bylineParts.push(`<span>来源 ${esc(s.spec)}</span>`);
    }
    if (s.catalog) {
      bylineParts.push(`<span>目录 ${esc(s.catalog)}</span>`);
    }
    bylineParts.push(`<span>插件包 ${esc(s.name)}</span>`);
    const desc = s.builtin
      ? "内置商店源：启用后重启服务器，在 dsh Web 界面「设置 → 插件市场」浏览与安装社区插件。"
      : (s.spec ? `安装来源：${esc(s.spec)}` : "仅提供插件目录（已并入上方商店）。");
    const actions = [];
    if (s.enabled) {
      actions.push(`<button class="btn small" data-act="disable" data-name="${esc(s.name)}">停用</button>`);
    } else if (s.hasPackage) {
      actions.push(`<button class="btn small primary" data-act="enable" data-name="${esc(s.name)}">启用</button>`);
    }
    if (!s.builtin) {
      actions.push(`<button class="btn small danger" data-act="remove" data-name="${esc(s.name)}">移除</button>`);
    }
    row.innerHTML = `
      <div class="store-av">${esc((s.label || s.name || "?").charAt(0).toUpperCase())}</div>
      <div class="store-info">
        <div class="store-name">${esc(s.label)}${builtinTag}${pill}${ver}</div>
        <div class="store-byline">${bylineParts.join(" · ")}</div>
        ${desc ? `<div class="store-desc">${desc}</div>` : ""}
      </div>
      <div class="store-actions">${actions.join("")}</div>`;
    list.appendChild(row);
  }
  list.querySelectorAll("[data-act]").forEach(btn => {
    btn.addEventListener("click", () => {
      const act = btn.dataset.act;
      const name = btn.dataset.name;
      if (act === "remove" && !confirm(`确认移除商店源 ${name}？`)) return;
      callApi({
        remove: "store_remove",
        enable: "store_set_enabled",
        disable: "store_set_enabled",
      }[act], {
        name: name,
        enabled: act === "enable",
      }).then(res => {
        showBannerEl($("plugin-banner"), res.ok ? "ok" : "err",
          res.message || (res.ok ? "操作已开始" : "操作失败"));
        if (res.ok && act === "enable") {
          const src = sources.find(x => x.name === name);
          if (src && !src.installed) {
            $("plugin-output-card").classList.remove("hidden");
            startPluginPoll();
          } else {
            refreshPlugins();
          }
        } else {
          refreshPlugins();
        }
      });
    });
  });
}

function startPluginPoll() {
  if (pluginPollTimer) return;
  pluginPollTimer = setInterval(pollPluginState, 1500);
}

function stopPluginPoll() {
  if (pluginPollTimer) { clearInterval(pluginPollTimer); pluginPollTimer = null; }
}

async function pollPluginState() {
  const st = await callApi("plugin_state");
  if (!st) return stopPluginPoll();
  const busy = st.phase !== "idle";
  const output = $("plugin-output");
  const joined = (st.output || []).join("\n");
  $("plugin-output-card").classList.toggle("hidden", !busy && !joined);
  if (joined !== output.textContent) {
    output.textContent = joined;
    output.scrollTop = output.scrollHeight;
  }
  $("btn-install-plugin").disabled = busy;
  $("btn-install-plugin").textContent = busy ? "进行中…" : "安装";
  $("btn-import-plugin").disabled = busy;
  $("btn-import-plugin").textContent = busy ? "进行中…" : "导入安装";
  if (!busy) {
    stopPluginPoll();
    if (st.message) {
      showBannerEl($("plugin-banner"), st.error ? "err" : "ok", st.message);
    }
    refreshPlugins();
  }
}

$("btn-install-plugin").addEventListener("click", async () => {
  const spec = $("plugin-spec").value.trim();
  if (!spec) return;
  const res = await callApi("install_plugin", { spec });
  showBannerEl($("plugin-banner"), res.ok ? "ok" : "err", res.message);
  $("plugin-spec").value = "";
  if (res.ok) { $("plugin-output-card").classList.remove("hidden"); startPluginPoll(); }
});

$("btn-refresh-plugins").addEventListener("click", refreshPlugins);

/* ---------------- plugin local import ---------------- */

async function pickPluginFile() {
  const res = await callApi("pick_plugin_file");
  const path = (res && res.path) || "";
  $("plugin-file-label").textContent = path ? path : "未选择文件";
  $("plugin-file-label").dataset.path = path;
  $("btn-import-plugin").disabled = !path || !!pluginPollTimer;
}

$("btn-pick-plugin").addEventListener("click", pickPluginFile);

$("btn-import-plugin").addEventListener("click", async () => {
  const path = $("plugin-file-label").dataset.path || "";
  if (!path) return;
  const res = await callApi("import_plugin", { path });
  showBannerEl($("plugin-banner"), res.ok ? "ok" : "err", res.message);
  if (res.ok) {
    $("plugin-output-card").classList.remove("hidden");
    startPluginPoll();
  }
});

/* ---------------- store ---------------- */

$("btn-refresh-store").addEventListener("click", refreshPlugins);

$("btn-add-store").addEventListener("click", async () => {
  const name = $("store-name").value.trim();
  const spec = $("store-spec").value.trim();
  const catalog = $("store-catalog").value.trim();
  if (!name || (!spec && !catalog)) {
    showBannerEl($("plugin-banner"), "err", "请填写商店名称，并至少填写安装来源或目录地址。");
    return;
  }
  const res = await callApi("store_add", { name, spec, catalog });
  showBannerEl($("plugin-banner"), res.ok ? "ok" : "err", res.message);
  if (res.ok) {
    $("store-name").value = "";
    $("store-spec").value = "";
    $("store-catalog").value = "";
    refreshPlugins();
  }
});

/* ---------------- update ---------------- */

let updatePollTimer = null;
let lastUpdateRender = "";

function isUpdateBusy(phase) {
  return ["checking", "downloading", "installing", "building", "swapping"].includes(phase);
}

function stopUpdatePoll() {
  if (updatePollTimer) { clearInterval(updatePollTimer); updatePollTimer = null; }
}

/* 进入更新页时仅显示本地版本信息，不做网络检查 */
async function renderLocalUpdate() {
  const state = await refreshState();
  const upd = state.update || {};
  renderUpdate({ data: upd }, true);
}

/* 幂等渲染：内容未变化时不做任何 DOM 写入 */
function renderUpdate(res, silent) {
  const data = res.data || res || {};
  const remote = data.remote || null;
  const local = data.local || null;
  const busy = isUpdateBusy(data.phase);
  const fingerprint = JSON.stringify([local, remote, data.phase,
    Math.round((data.progress || 0) * 100), data.message || ""]);
  const changed = fingerprint !== lastUpdateRender;
  lastUpdateRender = fingerprint;
  if (changed) {
    $("local-version").textContent = local ? (local.commit || "-") : "（未记录）";
    $("local-commit").textContent = local ? (local.commit || "-") : "-";
    $("local-date").textContent = local ? (local.updatedAt || "-") : "-";
    $("remote-commit").textContent = remote ? remote.commit : "-";
    $("remote-date").textContent = remote ? (remote.date || "").replace("T", " ").slice(0, 16) : "-";
    $("remote-message").textContent = remote ? remote.message : "-";
    const prog = $("update-progress");
    if (busy || data.phase === "done") {
      prog.classList.remove("hidden");
      $("progress-fill").style.width = `${Math.round((data.progress || 0) * 100)}%`;
      $("progress-message").textContent = data.message || "";
    } else {
      prog.classList.add("hidden");
    }
  }
  $("btn-check").disabled = busy;
  $("btn-update").disabled = busy || !data.canUpdate;
  $("btn-import-core").disabled = busy || !($("core-file-label").dataset.path);
  $("btn-import-core").textContent = busy ? "导入中…" : "开始导入";
  $("btn-pick-core").disabled = busy;
}

async function pollUpdate() {
  const state = await refreshState();
  const upd = state.update || {};
  renderUpdate({ data: upd }, true);
  if (!isUpdateBusy(upd.phase)) {
    stopUpdatePoll();
    if (upd.error && upd.message) {
      showBannerEl($("update-banner"), "err", upd.message);
    }
  }
}

$("btn-check").addEventListener("click", async () => {
  $("btn-check").disabled = true;
  const res = await callApi("check_update");
  renderUpdate(res, false);
  $("btn-check").disabled = false;
  if (isUpdateBusy((res.data || res).phase)) {
    stopUpdatePoll();
    updatePollTimer = setInterval(pollUpdate, 1500);
  }
});

$("btn-update").addEventListener("click", async () => {
  if (!confirm("将下载 GitHub 上的最新源码并重新构建核心。\n构建期间请勿关闭应用。继续？")) return;
  await callApi("download_update");
  stopUpdatePoll();
  updatePollTimer = setInterval(pollUpdate, 1500);
});

/* ---------------- core release tag update (B2) ---------------- */

async function loadCoreReleases() {
  const select = $("core-release-select");
  const res = await callApi("list_core_releases").catch(() => ({ ok: false }));
  const list = (res && res.releases) || [];
  select.innerHTML = '<option value="">跟随 master（最新开发版）</option>' +
    list.map(r => `<option value="${esc(r.tag)}">${esc(r.tag)} · ${esc(r.name || "")} · ${esc(r.published)}</option>`).join("");
  select.dataset.loaded = "1";
}

$("btn-refresh-releases").addEventListener("click", () => {
  $("core-release-select").innerHTML = '<option value="">加载中…</option>';
  loadCoreReleases();
});

$("btn-update-tag").addEventListener("click", async () => {
  const select = $("core-release-select");
  if (!select.dataset.loaded) await loadCoreReleases();
  const tag = select.value || "";
  const label = tag || "master（最新开发版）";
  if (!confirm(`将从 ${label} 的源码重新构建并切换核心（失败自动回退）。\n构建期间请勿关闭应用。继续？`)) return;
  const res = await callApi("update_core", { tag });
  showBannerEl($("update-banner"), res.ok ? "ok" : "err", res.message);
  if (res.ok) {
    stopUpdatePoll();
    updatePollTimer = setInterval(pollUpdate, 1500);
  }
});

loadCoreReleases();

/* ---------------- core local import ---------------- */

async function pickCoreArchive() {
  const res = await callApi("pick_core_archive");
  const path = (res && res.path) || "";
  $("core-file-label").textContent = path ? path : "未选择文件";
  $("core-file-label").dataset.path = path;
  $("btn-import-core").disabled = !path;
}

$("btn-pick-core").addEventListener("click", pickCoreArchive);

$("btn-import-core").addEventListener("click", async () => {
  const path = $("core-file-label").dataset.path || "";
  if (!path) return;
  if (!confirm("将从本地源码压缩包构建并切换核心。\n构建期间请勿关闭应用。继续？")) return;
  const res = await callApi("import_core", { path });
  showBannerEl($("update-banner"), res.ok ? "ok" : "err", res.message);
  if (res.ok) {
    stopUpdatePoll();
    updatePollTimer = setInterval(pollUpdate, 1500);
  }
});

/* ---------------- app update (about) ---------------- */

let latestRelease = null;      // 最近一次检查结果
let appUpdateTimer = null;     // 下载进度轮询

function renderAppUpdateControls() {
  const dl = $("btn-download-app-update");
  const inst = $("btn-install-app-update");
  const link = $("app-update-link");
  const hasUpdateAsset = latestRelease && latestRelease.latest
    && (latestRelease.latest.assets || []).some(a => a.kind === "update");
  dl.hidden = !(latestRelease && latestRelease.hasUpdate && hasUpdateAsset);
  link.hidden = !(latestRelease && latestRelease.hasUpdate && !hasUpdateAsset);
  if (latestRelease && latestRelease.hasUpdate && hasUpdateAsset) {
    dl.disabled = false;
    dl.textContent = "下载升级包";
  }
}

async function checkAppUpdate(silent) {
  const btn = $("btn-check-app-update");
  const status = $("about-app-update");
  if (btn.disabled) return;  // 已在进行中
  btn.disabled = true;
  btn.textContent = "检查中…";
  const res = await callApi("check_app_update").catch(err => {
    return { ok: false, message: String(err && err.message || err) };
  });
  btn.disabled = false;
  btn.textContent = "检查应用更新";
  latestRelease = res;
  if (res.ok) {
    const latest = res.latest || {};
    if (res.hasUpdate) {
      status.textContent = `发现新版本 v${latest.version}（当前 v${res.current}）`;
      status.style.color = "";
    } else {
      status.textContent = `已是最新版本 v${res.current}`;
      status.style.color = "";
    }
  } else if (!silent) {
    status.textContent = res.message ? `检查失败：${res.message}` : "检查失败（网络不可用）";
    status.style.color = "";
  }
  renderAppUpdateControls();
  await refreshAppUpdateState();
}

function stopAppUpdatePoll() {
  if (appUpdateTimer) { clearInterval(appUpdateTimer); appUpdateTimer = null; }
}

async function refreshAppUpdateState() {
  const st = await callApi("app_update_state").catch(() => null);
  if (!st) return;
  const inst = $("btn-install-app-update");
  const progress = $("about-app-update-progress");
  if (st.phase === "downloading") {
    progress.hidden = false;
    progress.textContent = `${st.message || "下载中"}${st.progress ? " " + Math.round(st.progress * 100) + "%" : ""}`;
    inst.hidden = true;
    $("btn-download-app-update").disabled = true;
    stopAppUpdatePoll();
    appUpdateTimer = setInterval(refreshAppUpdateState, 1000);
  } else if (st.phase === "ready") {
    progress.hidden = false;
    progress.textContent = `升级包已就绪（${st.sha256 ? "SHA256 校验通过" : "已下载"}）`;
    $("btn-download-app-update").disabled = false;
    inst.hidden = false;
    stopAppUpdatePoll();
  } else if (st.phase === "failed") {
    progress.hidden = false;
    progress.textContent = st.message || "下载失败";
    $("btn-download-app-update").disabled = false;
    inst.hidden = true;
    stopAppUpdatePoll();
  } else if (st.phase === "installing") {
    progress.hidden = false;
    progress.textContent = st.message || "准备安装…";
    inst.hidden = true;
    stopAppUpdatePoll();
  }
}

$("btn-check-app-update").addEventListener("click", () => checkAppUpdate(false));

$("btn-download-app-update").addEventListener("click", async () => {
  const progress = $("about-app-update-progress");
  const res = await callApi("download_app_update");
  if (!res.ok) {
    progress.hidden = false;
    progress.textContent = res.message || "下载启动失败";
    return;
  }
  await refreshAppUpdateState();
});

$("btn-install-app-update").addEventListener("click", async () => {
  const progress = $("about-app-update-progress");
  const st = await callApi("app_update_state");
  if (!st || st.phase !== "ready") { await refreshAppUpdateState(); return; }
  if (!confirm("将退出应用并安装更新，安装完成后自动重新启动。\n继续？")) return;
  const res = await callApi("install_app_update");
  if (!res.ok) {
    progress.hidden = false;
    progress.textContent = res.message || "安装启动失败";
    return;
  }
  setTimeout(() => callApi("quit_for_update").catch(() => {}), 800);
});

/* ---------------- logs ---------------- */

let logLinesRaw = "";

function renderLog() {
  const view = $("log-view");
  const filter = ($("log-filter").value || "").toLowerCase();
  const lines = logLinesRaw.split("\n").filter(l => !filter || l.toLowerCase().includes(filter));
  const render = lines.map(l => {
    let cls = "";
    if (/error|failed|exception|traceback|错误|失败|异常/i.test(l)) cls = "log-err";
    else if (/warn|deprecat|警告/i.test(l)) cls = "log-warn";
    return `<div class="log-line ${cls}">${esc(l) || "&nbsp;"}</div>`;
  }).join("");
  view.innerHTML = render || '<div class="log-line">(无匹配日志)</div>';
  view.scrollTop = view.scrollHeight;
}

function refreshLog() {
  callApi("read_log").then(res => {
    logLinesRaw = res || "";
    renderLog();
  }).catch(() => {
    logLinesRaw = "(读取日志失败)";
    renderLog();
  });
}

$("btn-refresh-log").addEventListener("click", refreshLog);
$("log-filter").addEventListener("input", renderLog);
$("btn-copy-log").addEventListener("click", async () => {
  if (!logLinesRaw) return;
  try { await navigator.clipboard.writeText(logLinesRaw); } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = logLinesRaw;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e2) {}
    ta.remove();
  }
  $("btn-copy-log").textContent = "已复制";
  setTimeout(() => { $("btn-copy-log").textContent = "复制"; }, 1200);
});
$("btn-download-log").addEventListener("click", () => {
  const blob = new Blob([logLinesRaw || ""], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "core.log";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 3000);
});

/* ---------------- onboarding ---------------- */

let onbStep = 0;
const ONB_TOTAL = 4;

function renderOnb() {
  document.querySelectorAll(".onb-step").forEach(s => {
    s.classList.toggle("active", Number(s.dataset.step) === onbStep);
  });
  $("onb-dots").innerHTML = Array.from({ length: ONB_TOTAL }, (_, i) =>
    `<span class="dot ${i === onbStep ? "active" : ""}"></span>`).join("");
  $("onb-prev").disabled = onbStep === 0;
  $("onb-next").textContent = onbStep === ONB_TOTAL - 1 ? "开始使用" : "下一步";
}

function showOnboarding(show) {
  $("onboarding").classList.toggle("hidden", !show);
  if (show) renderOnb();
}

async function finishOnboarding() {
  showOnboarding(false);
  try { await callApi("set_onboarding_done"); } catch (e) { /* 非致命 */ }
}

$("onb-skip").addEventListener("click", finishOnboarding);
$("onb-prev").addEventListener("click", () => { if (onbStep > 0) { onbStep--; renderOnb(); } });
$("onb-next").addEventListener("click", () => {
  if (onbStep < ONB_TOTAL - 1) { onbStep++; renderOnb(); }
  else finishOnboarding();
});

/* ---------------- shell plugins (外壳插件) ---------------- */

const shellPageHooks = {};

/* ShellPlugin API：外壳插件在 main.js 中调用这些接口挂载
   页面 / 卡片 / 按钮，参考核心的插件模式。 */
window.ShellPlugin = {
  version: 1,

  registerPage(cfg) {
    if (!cfg || !cfg.id || typeof cfg.html !== "string") {
      return console.error("[ShellPlugin] registerPage 参数不完整", cfg);
    }
    const id = String(cfg.id);
    if (uiPages.includes(id)) return console.error("[ShellPlugin] 页面 id 冲突: " + id);
    const btn = document.createElement("button");
    btn.className = "nav-item";
    btn.dataset.page = id;
    btn.innerHTML = `<span class="nav-icon">${esc(cfg.icon || "◇")}</span>${esc(cfg.title || id)}`;
    document.querySelector(".nav").appendChild(btn);
    btn.addEventListener("click", () => showPage(id));
    const sec = document.createElement("section");
    sec.className = "page hidden";
    sec.id = "page-" + id;
    sec.innerHTML = `<div class="page-head"><h1>${esc(cfg.title || id)}</h1></div>` + cfg.html;
    document.querySelector(".content").appendChild(sec);
    uiPages.push(id);
    if (typeof cfg.onShow === "function") shellPageHooks[id] = cfg.onShow;
    ShellPlugin.log("已注册页面: " + id);
    return sec;
  },

  registerCard(cfg) {
    if (!cfg || !cfg.pageId) return console.error("[ShellPlugin] registerCard 需要 pageId");
    const page = document.getElementById("page-" + cfg.pageId);
    if (!page) return console.error("[ShellPlugin] 页面不存在: " + cfg.pageId);
    const card = document.createElement("div");
    card.className = "card shell-plugin-card";
    if (cfg.id) card.id = "shell-card-" + cfg.id;
    card.innerHTML = (cfg.title ? `<h2>${esc(cfg.title)}</h2>` : "") + (cfg.html || "");
    page.appendChild(card);
    if (typeof cfg.onMount === "function") {
      try { cfg.onMount(card); } catch (e) { console.error("[ShellPlugin] onMount 失败", e); }
    }
    ShellPlugin.log(`已注册卡片: ${cfg.pageId} / ${cfg.id || ""}`);
    return card;
  },

  registerAction(cfg) {
    if (!cfg || !cfg.pageId) return console.error("[ShellPlugin] registerAction 需要 pageId");
    const head = document.querySelector("#page-" + cfg.pageId + " .head-actions");
    if (!head) return console.error("[ShellPlugin] 页面无按钮区: " + cfg.pageId);
    const b = document.createElement("button");
    b.className = "btn ghost";
    if (cfg.id) b.id = "shell-action-" + cfg.id;
    b.textContent = cfg.label || cfg.id || "插件按钮";
    b.addEventListener("click", ev => {
      try { cfg.onClick(ev); } catch (e) { console.error("[ShellPlugin] onClick 失败", e); }
    });
    head.appendChild(b);
    return b;
  },

  on(evt, fn) {
    if (typeof fn !== "function") return;
    (window.__shellHandlers = window.__shellHandlers || {});
    (window.__shellHandlers[evt] = window.__shellHandlers[evt] || []).push(fn);
  },

  emit(evt, data) {
    const list = (window.__shellHandlers || {})[evt] || [];
    list.forEach(fn => { try { fn(data); } catch (e) { console.error(e); } });
  },

  callApi(method, payload) { return callApi(method, payload); },
  log(...args) { console.log("[ShellPlugin]", ...args); },

  registerTheme(cfg) {
    if (!cfg || !cfg.id || !cfg.name || !cfg.css) {
      return console.error("[ShellPlugin] registerTheme 参数不完整（需要 id/name/css）");
    }
    if (shellThemes.some(t => t.id === cfg.id)) {
      return console.error("[ShellPlugin] 主题 id 冲突: " + cfg.id);
    }
    shellThemes.push({ id: String(cfg.id), name: String(cfg.name), builtin: false, css: String(cfg.css) });
    ShellPlugin.log("已注册外观: " + cfg.id);
  },
};

/* ---------------- shell plugins: 桌宠接口（预留） ---------------- */

const shellPets = {};

function makeDraggable(el) {
  let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
  el.addEventListener("mousedown", e => {
    dragging = true;
    sx = e.clientX; sy = e.clientY;
    const r = el.getBoundingClientRect();
    ox = r.left; oy = r.top;
    e.preventDefault();
  });
  window.addEventListener("mousemove", e => {
    if (!dragging || !el.parentElement) return;
    const layer = el.parentElement.getBoundingClientRect();
    el.style.left = Math.max(0, Math.min(layer.width - 60, ox + e.clientX - sx - layer.left)) + "px";
    el.style.top = Math.max(0, Math.min(layer.height - 60, oy + e.clientY - sy - layer.top)) + "px";
  });
  window.addEventListener("mouseup", () => { dragging = false; });
}

/* 桌宠插件接口：全窗口透明挂载层（#shell-pet-layer，pointer-events:none），
   宠物元素自身 pointer-events:auto；支持拖拽与生命周期回调。 */
window.ShellPlugin.registerPet = function (cfg) {
  if (!cfg || !cfg.id) return console.error("[ShellPlugin] registerPet 需要 id");
  const layer = document.getElementById("shell-pet-layer");
  if (!layer) return console.error("[ShellPlugin] 桌宠挂载层缺失");
  if (shellPets[cfg.id]) return shellPets[cfg.id].el;
  const el = document.createElement("div");
  el.className = "shell-pet";
  el.style.left = cfg.x || "auto";
  el.style.top = cfg.y || "auto";
  el.innerHTML = cfg.html || "";
  layer.appendChild(el);
  if (cfg.draggable) makeDraggable(el);
  if (typeof cfg.onMount === "function") {
    try { cfg.onMount(el); } catch (e) { console.error("[ShellPlugin] 桌宠 onMount 失败", e); }
  }
  shellPets[cfg.id] = { el, cfg };
  ShellPlugin.log("桌宠已挂载: " + cfg.id);
  return el;
};

window.ShellPlugin.unregisterPet = function (id) {
  const p = shellPets[id];
  if (!p) return;
  try { if (typeof p.cfg.onDestroy === "function") p.cfg.onDestroy(); } catch (e) { console.error(e); }
  p.el.remove();
  delete shellPets[id];
};

window.ShellPlugin.getPetLayer = function () {
  return document.getElementById("shell-pet-layer");
};

/* ---------------- 外观系统（主题） ---------------- */

const shellThemes = [
  { id: "builtin-midnight", name: "深邃黑（默认）", builtin: true, css: "" },
  { id: "builtin-ocean", name: "深海蓝青", builtin: true, css: "themes/ocean.css" },
  { id: "builtin-sunset", name: "暖橙霞光", builtin: true, css: "themes/sunset.css" },
  { id: "builtin-forest", name: "森林绿", builtin: true, css: "themes/forest.css" },
  { id: "builtin-light", name: "浅色", builtin: true, css: "themes/light.css" },
];
let currentTheme = "builtin-midnight";

async function applyTheme(id, persist) {
  const theme = shellThemes.find(t => t.id === id) || shellThemes[0];
  let styleEl = document.getElementById("shell-theme");
  if (theme.css) {
    let text = theme.css;
    if (/^(https?:)?\/\//.test(text) || text.startsWith("/")) {
      try {
        const resp = await fetch(text);
        if (resp.ok) text = await resp.text();
        else throw new Error("HTTP " + resp.status);
      } catch (e) {
        console.error("[Theme] 加载失败: " + theme.css, e);
        text = "";
      }
    }
    if (text) {
      if (!styleEl) {
        styleEl = document.createElement("style");
        styleEl.id = "shell-theme";
        document.head.appendChild(styleEl);
      }
      styleEl.textContent = text;
    }
  } else if (styleEl) {
    styleEl.remove();
  }
  currentTheme = theme.id;
  if (persist !== false) {
    callApi("set_ui_state", { theme: theme.id }).catch(() => {});
  }
  renderThemeList();
}

function renderThemeList() {
  const box = $("themes-list");
  if (!box) return;
  box.innerHTML = shellThemes.map(t => `
    <button type="button" class="theme-chip ${t.id === currentTheme ? "on" : ""}" data-theme="${esc(t.id)}"
            title="${esc(t.name)}${t.builtin ? "" : "（插件外观）"}">
      <span class="theme-swatch" data-theme-id="${esc(t.id)}"></span>
      <span class="theme-name">${esc(t.name)}</span>
    </button>`).join("");
  box.querySelectorAll("[data-theme]").forEach(b =>
    b.addEventListener("click", () => applyTheme(b.dataset.theme)));
}

/* 启动时拉取已启用插件清单并注入脚本；插件脚本随后自行 register*。 */
async function loadShellPlugins() {
  try {
    const manifest = await callApi("get_shell_plugin_manifest");
    const list = (manifest && manifest.plugins) || [];
    for (const p of list) {
      await new Promise(resolve => {
        const s = document.createElement("script");
        s.src = p.entry;
        s.onload = resolve;
        s.onerror = () => { console.error("[ShellPlugin] 加载失败: " + p.id); resolve(); };
        document.head.appendChild(s);
      });
    }
    if (list.length) {
      ShellPlugin.log(`已加载 ${list.length} 个外壳插件: ${list.map(p => p.id).join(", ")}`);
    }
  } catch (e) {
    console.error("[ShellPlugin] 清单加载失败", e);
  }
}

/* ---------------- shell plugins: 管理界面 ---------------- */

let shellPluginPicked = "";

async function refreshShellPlugins() {
  const box = $("shell-plugin-list");
  if (!box) return;
  const data = await callApi("list_shell_plugins");
  const list = (data && data.plugins) || [];
  if (!list.length) {
    box.innerHTML = `<div class="plugin-empty">暂无外壳插件（随应用内置或从 zip 导入）</div>`;
    return;
  }
  box.innerHTML = list.map(p => `
    <div class="plugin-row">
      <div class="plugin-info">
        <div class="plugin-name">${esc(p.name)}
          <span class="tag ${p.builtin ? "builtin" : "plain"}">${p.builtin ? "内置" : "用户"}</span>
          ${p.valid ? "" : '<span class="tag miss">无效</span>'}
          ${p.enabled ? '<span class="tag bundle">已启用</span>' : '<span class="tag miss">已停用</span>'}
        </div>
        <div class="plugin-meta">${esc(p.id)}${p.version ? " · v" + esc(p.version) : ""} · ${esc(p.description)}</div>
      </div>
      <div class="plugin-actions">
        <button class="btn small" data-sp="${esc(p.id)}" data-enable="${p.enabled ? "0" : "1"}">${p.enabled ? "停用" : "启用"}</button>
        ${p.builtin ? "" : `<button class="btn small danger" data-sp-remove="${esc(p.id)}">卸载</button>`}
      </div>
    </div>`).join("");
  box.querySelectorAll("[data-sp]").forEach(b => b.addEventListener("click", async () => {
    const r = await callApi("set_shell_plugin_enabled", { id: b.dataset.sp, enabled: b.dataset.enable === "1" });
    showBannerEl($("plugin-banner"), r.ok ? "ok" : "err", r.message);
    refreshShellPlugins();
  }));
  box.querySelectorAll("[data-sp-remove]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm("卸载该外壳插件？")) return;
    const r = await callApi("remove_shell_plugin", { id: b.dataset.spRemove });
    showBannerEl($("plugin-banner"), r.ok ? "ok" : "err", r.message);
    refreshShellPlugins();
  }));
}

$("btn-refresh-shell-plugins").addEventListener("click", refreshShellPlugins);
$("btn-pick-shell-plugin").addEventListener("click", async () => {
  const r = await callApi("pick_shell_plugin_file");
  if (r && r.path) {
    shellPluginPicked = r.path;
    $("shell-plugin-file-label").textContent = r.path;
    $("btn-import-shell-plugin").disabled = false;
  }
});
$("btn-import-shell-plugin").addEventListener("click", async () => {
  if (!shellPluginPicked) return;
  const r = await callApi("import_shell_plugin", { path: shellPluginPicked });
  showBannerEl($("plugin-banner"), r.ok ? "ok" : "err", r.message);
  shellPluginPicked = "";
  $("shell-plugin-file-label").textContent = "未选择文件";
  $("btn-import-shell-plugin").disabled = true;
  refreshShellPlugins();
});

/* ---------------- shell plugins: 提示词生成（创造模式开发流） ---------------- */

function buildShellPluginPrompt(idea) {
  idea = (idea || "").trim() || "（未填写，请 agent 先与我确认插件想法）";
  return [
    "# 任务：为 DeepSeek Harness for Windows 桌面外壳开发一个外壳插件",
    "",
    "## 背景",
    "外壳（pywebview 桌面窗口）是 DeepSeek Harness（dsh）的 Windows 封装；外壳 UI 为纯 HTML/CSS/JS。",
    "外壳插件 = zip 包（plugin.json + main.js + 可选静态资源），扩展外壳界面：新页面 / 卡片 / 头部按钮。",
    "",
    "## 插件想法",
    idea,
    "",
    "## 插件规范（ShellPlugin API v1）",
    "- plugin.json 字段：",
    '  {"id":"my-plugin","name":"显示名","version":"0.1.0","description":"一句话说明","entry":"main.js"}',
    "  id 仅限字母数字 ._- 且不超过 64 字符。",
    "- main.js 在 window.ShellPlugin 上注册（脚本在外壳页面加载后注入执行）：",
    "  * registerPage({id,title,icon,html,onShow}) 新增左侧导航页面；",
    "  * registerCard({pageId,id,title,html,onMount}) 在既有页面追加卡片（pageId 可选：workspace/plugins/settings/update/logs/about）；",
    "  * registerAction({pageId,id,label,onClick}) 在页面头部追加按钮；",
    "  * on(evt,fn)/emit(evt,data) 事件总线；callApi(method,payload) 调用外壳桥；log(...) 日志。",
    "- 桥方法参考：get_state / list_plugins / list_shell_plugins / start_server / stop_server / read_log 等。",
    "",
    "## 约束",
    "- 纯 HTML/CSS/JS，不依赖构建工具；CSS 优先使用外壳 CSS 变量（--bg/--panel/--fg/--accent/--warn）。",
    "- 不要向公网发起请求；需要数据时通过 callApi 走外壳桥。",
    "- 不得覆盖 window.ShellPlugin。",
    "",
    "## 交付",
    "- 输出一个 zip（内含 plugin.json + main.js），并给出「外壳 → 插件 → 导入外壳插件」的验证步骤；",
    "- 若插件需要与 dsh 核心联动（壳内外联动），同时给出核心侧配套说明（dsh 插件或 API 端点）。",
    "",
    "## 开发方式",
    "- 请使用创造模式开发；先输出插件结构与 API 调用方案，再给完整代码。",
  ].join("\n");
}

$("btn-gen-plugin-prompt").addEventListener("click", () => {
  $("plugin-prompt").value = buildShellPluginPrompt($("plugin-idea").value);
  $("btn-copy-plugin-prompt").disabled = false;
});

$("btn-copy-plugin-prompt").addEventListener("click", async () => {
  const ta = $("plugin-prompt");
  if (!ta.value) return;
  let ok = false;
  try { ok = await navigator.clipboard.writeText(ta.value); } catch (e) { ok = false; }
  if (!ok) {
    ta.select();
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  }
  $("btn-copy-plugin-prompt").textContent = ok ? "已复制" : "复制失败";
  setTimeout(() => { $("btn-copy-plugin-prompt").textContent = "复制"; }, 1500);
});

/* ---------------- boot ---------------- */

(async function init() {
  await waitBridgeReady();
  await loadShellPlugins();
  const bootState = await refreshState();
  const savedTheme = bootState.app.uiState && bootState.app.uiState.theme;
  if (savedTheme) await applyTheme(savedTheme, false);
  if (bootState.app.uiState && bootState.app.uiState.lang) {
    window.__i18nLang = bootState.app.uiState.lang;
    if (typeof applyI18n === "function") applyI18n();
  }
  await loadSettings();
  const state = await refreshState();
  if (!state.app.onboardingDone) showOnboarding(true);
  if (state.server.running) {
    // 恢复上次的沉浸状态；iframe 已加载时不重载，仅切换外壳布局
    openFrame($("dsh-frame"), state.server.url);
    const wantImmersive = !!(state.app.uiState && state.app.uiState.immersive);
    setImmersive(wantImmersive, false);
    if (!wantImmersive) showPage("workspace");
  }
  // 托盘命令轮询：托盘菜单/点击经 Python 队列，由桥线程执行窗口操作
  setInterval(() => callApi("poll_tray").catch(() => {}), 800);
})();
