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
    return hasArgs
      ? Promise.resolve(window.pywebview.api[method](payload))
      : Promise.resolve(window.pywebview.api[method]());
  }
  return fetch(`/api/bridge/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(j => j.data);
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
  if (name === "plugins") refreshPlugins();
  if (name === "settings") loadSettings();      // 进入设置页时重新加载（含 API Key 掩码）
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
    ? `运行中 :${server.port}` : (server.coreReady ? "未启动" : "核心未构建");

  $("btn-start").hidden = running;
  $("btn-stop").hidden = !running;
  $("btn-restart").hidden = !running;
  $("btn-open-browser").hidden = !running;

  $("about-app-version").textContent = app.version || "-";
  $("about-port").textContent = String(server.port);
  return state;
}

function showBanner(type, text) {
  const b = $("server-banner");
  b.className = "banner " + type;
  b.textContent = text;
  b.classList.remove("hidden");
  setTimeout(() => b.classList.add("hidden"), 6000);
}

async function startServer() {
  const res = await callApi("start_server");
  if (res.ok) {
    showBanner("ok", res.message || "服务已启动");
    await refreshState();
    openFrame($("dsh-frame"), `http://127.0.0.1:${res.port || await getPort()}`);
  } else {
    showBanner("err", res.message || "启动失败");
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
  document.body.classList.add("immersive");
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
}

function exitImmersive() {
  document.body.classList.remove("immersive");
  document.querySelectorAll(".nav-item").forEach(b => {
    b.classList.toggle("active", b.dataset.page === "workspace");
  });
}

$("btn-immersive").addEventListener("click", () => {
  if (document.body.classList.contains("immersive")) exitImmersive();
  else document.body.classList.add("immersive");
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
  refreshProviders();
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

$("btn-change-key").addEventListener("click", () => {
  setKeyMode(apiKeyEditing ? "masked" : "editing");
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
  const data = await callApi("list_plugins");
  renderPlugins(data);
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

/* ---------------- logs ---------------- */

function refreshLog() {
  callApi("read_log").then(res => {
    $("log-view").textContent = res || "(空)";
    $("log-view").scrollTop = $("log-view").scrollHeight;
  }).catch(() => {
    $("log-view").textContent = "(读取日志失败)";
  });
}
$("btn-refresh-log").addEventListener("click", refreshLog);

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

/* ---------------- boot ---------------- */

(async function init() {
  await loadSettings();
  const state = await refreshState();
  if (!state.app.onboardingDone) showOnboarding(true);
  if (state.server.running) {
    openFrame($("dsh-frame"), state.server.url);
  }
})();
