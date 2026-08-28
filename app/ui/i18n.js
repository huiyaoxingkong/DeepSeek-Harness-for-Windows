/* 外壳 UI 多语言（E2）：中 / 英。
   零标记方案：以中文原文为键的反向映射，DOMContentLoaded 时遍历静态文本节点
   与 placeholder 替换为当前语言；动态字符串在 app.js 中用 t() 包裹。 */
"use strict";

const I18N_DICT = {
  zh: {
    "nav.workspace": "工作台", "nav.plugins": "插件", "nav.settings": "设置",
    "nav.update": "核心更新", "nav.logs": "日志", "nav.about": "关于",
    "page.plugins": "插件管理", "page.logs": "核心日志",
    "btn.exitImmersive": "⇤ 退出全屏", "btn.startServer": "启动服务器",
    "btn.stopServer": "停止服务器", "btn.restart": "重启", "btn.browser": "浏览器打开",
    "btn.save": "保存设置", "btn.check": "检查更新", "btn.update": "更新核心",
    "btn.copy": "复制", "btn.download": "下载", "btn.immersive": "全屏",
    "settings.api": "模型 API", "settings.providers": "模型提供方", "settings.server": "服务器",
    "settings.appearance": "外观", "settings.environment": "运行环境",
    "settings.network": "网络与镜像（可选）",
    "settings.apiKey": "DeepSeek API Key", "settings.baseUrl": "API Base URL（可选）",
    "settings.port": "端口", "settings.autoStart": "启动应用时自动启动服务器",
    "settings.openBrowser": "启动服务器后同时打开系统浏览器",
    "settings.closeToTray": "关闭窗口时最小化到系统托盘（后台运行）",
    "settings.autoLaunch": "开机自动启动 DeepSeek Harness",
    "settings.proxy": "HTTP 代理", "settings.npmRegistry": "npm registry 镜像",
    "settings.githubMirror": "GitHub 下载镜像前缀",
    "update.versionInfo": "版本信息", "update.flow": "更新流程",
    "update.tagUpdate": "选择版本更新（升级 / 回退）", "update.importLocal": "从本地文件导入核心",
    "logs.health": "迁移/升级健康检查", "plugins.shellPlugins": "外壳插件",
    "plugins.promptGen": "生成插件提示词（创造模式开发流）",
    "empty.title": "服务器未启动",
    "empty.sub": "点击右上角「启动服务器」开始使用 DeepSeek Harness Web 界面",
    "loading.title": "正在启动服务器…",
    "loading.hint": "首次构建核心约需 10 分钟，后续启动约 1~3 分钟，请稍候",
    "status.running": "运行中", "status.stopped": "未启动", "status.noCore": "核心未构建",
    "tools.bundled": "内置", "tools.system": "系统", "tools.missing": "缺失",
    "tools.lazy": "懒人包（内置 Node.js + Git）", "tools.minimal": "极简包（运行环境自装）",
    "lang.label": "界面语言",
    "toast.save": "已保存",
    "btn.copied": "已复制",
    "btn.genPrompt": "生成提示词",
    "btn.install": "安装",
    "btn.pickPlugin": "选择插件包…",
    "plugins.preset": "常用预设：",
    "plugins.presetWebAll": "dsh-web 全家桶（19 插件聚合包）",
    "update.tagBtn": "更新到所选版本",
    "update.refreshList": "刷新列表",
    "logs.filter": "过滤关键词…",
    "instances.title": "本机实例",
    "btn.copy": "复制",
  },
  en: {
    "nav.workspace": "Workspace", "nav.plugins": "Plugins", "nav.settings": "Settings",
    "nav.update": "Core Update", "nav.logs": "Logs", "nav.about": "About",
    "page.plugins": "Plugin Manager", "page.logs": "Core Logs",
    "btn.exitImmersive": "⇤ Exit Fullscreen", "btn.startServer": "Start Server",
    "btn.stopServer": "Stop Server", "btn.restart": "Restart", "btn.browser": "Open in Browser",
    "btn.save": "Save Settings", "btn.check": "Check Updates", "btn.update": "Update Core",
    "btn.copy": "Copy", "btn.download": "Download", "btn.immersive": "Fullscreen",
    "settings.api": "Model API", "settings.providers": "Model Providers", "settings.server": "Server",
    "settings.appearance": "Appearance", "settings.environment": "Runtime Environment",
    "settings.network": "Network & Mirrors (optional)",
    "settings.apiKey": "DeepSeek API Key", "settings.baseUrl": "API Base URL (optional)",
    "settings.port": "Port", "settings.autoStart": "Start server when the app launches",
    "settings.openBrowser": "Also open the system browser on start",
    "settings.closeToTray": "Minimize to system tray on close (keep running)",
    "settings.autoLaunch": "Launch DeepSeek Harness at Windows startup",
    "settings.proxy": "HTTP Proxy", "settings.npmRegistry": "npm registry mirror",
    "settings.githubMirror": "GitHub download mirror prefix",
    "update.versionInfo": "Version Info", "update.flow": "Update Flow",
    "update.tagUpdate": "Update by Release Tag (upgrade / rollback)", "update.importLocal": "Import Core from Local File",
    "logs.health": "Migration / Upgrade Health Check", "plugins.shellPlugins": "Shell Plugins",
    "plugins.promptGen": "Generate Plugin Prompt (Creative Mode Flow)",
    "empty.title": "Server not running",
    "empty.sub": "Click \"Start Server\" in the top-right to open the DeepSeek Harness Web UI",
    "loading.title": "Starting server…",
    "loading.hint": "First build takes ~10 min; later starts ~1-3 min",
    "status.running": "Running", "status.stopped": "Stopped", "status.noCore": "Core not built",
    "tools.bundled": "Bundled", "tools.system": "System", "tools.missing": "Missing",
    "tools.lazy": "Lazy package (bundled Node.js + Git)", "tools.minimal": "Minimal package (self-provided runtimes)",
    "lang.label": "UI Language",
    "toast.save": "Saved",
    "btn.copied": "Copied",
    "btn.genPrompt": "Generate Prompt",
    "btn.install": "Install",
    "btn.pickPlugin": "Choose plugin package…",
    "plugins.preset": "Presets: ",
    "plugins.presetWebAll": "dsh-web all-in-one (19-plugin bundle)",
    "update.tagBtn": "Update to Selected Version",
    "update.refreshList": "Refresh List",
    "logs.filter": "Filter keywords…",
    "instances.title": "Local Instances",
    "btn.copy": "Copy",
  },
};

window.__i18nLang = "zh";
window.__i18nPrevLang = "zh";  // language the static DOM currently shows
window.__i18nKeys = { zh: {}, en: {} };
Object.keys(I18N_DICT).forEach(lang => {
  Object.entries(I18N_DICT[lang]).forEach(([k, v]) => { window.__i18nKeys[lang][v] = k; });
});

window.t = function (key) {
  const dict = I18N_DICT[window.__i18nLang] || I18N_DICT.zh;
  return dict[key] !== undefined ? dict[key] : (I18N_DICT.zh[key] ?? key);
};

function applyI18n() {
  // Look up DOM text with the map of the language CURRENTLY displayed
  // (the DOM starts in zh; after a switch it holds the new language).
  const keys = window.__i18nKeys[window.__i18nPrevLang] || {};
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  textNodes.forEach(node => {
    const raw = node.textContent || "";
    const key = keys[raw];
    if (key) node.textContent = window.t(key);
  });
  document.querySelectorAll("input[placeholder], textarea[placeholder]").forEach(el => {
    const key = keys[el.getAttribute("placeholder") || ""];
    if (key) el.setAttribute("placeholder", window.t(key));
  });
  document.querySelectorAll("button[title], a[title]").forEach(el => {
    const key = keys[el.getAttribute("title") || ""];
    if (key) el.setAttribute("title", window.t(key));
  });
  window.__i18nPrevLang = window.__i18nLang;
}

document.addEventListener("DOMContentLoaded", applyI18n);
