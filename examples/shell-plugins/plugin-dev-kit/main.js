/* 外壳插件开发套件（F1.3 落地）：可视化生成 plugin.json + main.js 骨架，
   并打包成可导入的 zip（store 压缩 + CRC32，纯 JS 实现，无外部依赖）。
   配合「生成插件提示词（创造模式开发流）」：简单插件用本页直接产出，
   复杂插件把本页生成的骨架与提示词一起交给 agent 开发。 */
"use strict";
(function () {
  if (!window.ShellPlugin) return;

  const esc = s => String(s).replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  /* ---------------- zip (store method + CRC32) ---------------- */
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c;
    }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  function dosDateTime(d) {
    const t = d || new Date();
    const time = (t.getHours() << 11) | (t.getMinutes() << 5) | (t.getSeconds() >> 1);
    const date = (((t.getFullYear() - 1980) & 0x7F) << 9) | ((t.getMonth() + 1) << 5) | t.getDate();
    return (time + (date << 16)) >>> 0;
  }

  function buildZip(files) {
    const enc = new TextEncoder();
    const parts = [];
    const central = [];
    let offset = 0;
    const dt = dosDateTime(new Date());
    for (const f of files) {
      const name = enc.encode(f.name);
      const crc = crc32(f.data);
      const lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true);
      lh.setUint16(6, 0x0800, true); lh.setUint16(8, 0, true);
      lh.setUint32(10, dt, true); lh.setUint32(14, crc, true);
      lh.setUint32(18, f.data.length, true); lh.setUint32(22, f.data.length, true);
      lh.setUint16(26, name.length, true); lh.setUint16(28, 0, true);
      parts.push(new Uint8Array(lh.buffer), name, f.data);
      const ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true);
      ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true);
      ch.setUint16(10, 0, true); ch.setUint32(12, dt, true);
      ch.setUint32(16, crc, true);
      ch.setUint32(20, f.data.length, true); ch.setUint32(24, f.data.length, true);
      ch.setUint16(28, name.length, true); ch.setUint16(30, 0, true);
      ch.setUint16(32, 0, true); ch.setUint16(34, 0, true);
      ch.setUint32(38, 0, true); ch.setUint32(42, offset, true);
      central.push(new Uint8Array(ch.buffer), name);
      offset += 30 + name.length + f.data.length;
    }
    const cdSize = central.reduce((s, p) => s + p.length, 0);
    const eocd = new DataView(new ArrayBuffer(22));
    eocd.setUint32(0, 0x06054b50, true);
    eocd.setUint16(8, files.length, true); eocd.setUint16(10, files.length, true);
    eocd.setUint32(12, cdSize, true); eocd.setUint32(16, offset, true);
    return new Blob([...parts, ...central, new Uint8Array(eocd.buffer)],
      { type: "application/zip" });
  }

  function downloadBlob(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  }

  /* ---------------- templates ---------------- */
  function mainJsFor(cfg) {
    const name = cfg.name || cfg.id;
    if (cfg.type === "page") {
      return `/* ${name} — 外壳插件（页面型） */
"use strict";
(function () {
  if (!window.ShellPlugin) return;
  window.ShellPlugin.registerPage({
    id: "${cfg.id}",
    title: "${name}",
    icon: "🧩",
    html: '<div class="card"><h2>${name}</h2>' +
          '<p style="color:var(--fg-dim);">这是 ${name} 的页面内容。</p></div>',
  });
})();
`;
    }
    return `/* ${name} — 外壳插件（卡片型） */
"use strict";
(function () {
  if (!window.ShellPlugin) return;
  window.ShellPlugin.registerCard({
    pageId: "about",
    id: "${cfg.id}",
    title: "${name}",
    html: '<div class="plugin-meta">这是 ${name} 的卡片内容。</div>',
  });
})();
`;
  }

  function generate() {
    const id = (document.getElementById("pd-id").value || "").trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(id)) {
      alert("id 仅限字母数字 ._-，且不超过 64 字符");
      return;
    }
    const name = (document.getElementById("pd-name").value || "").trim() || id;
    const desc = (document.getElementById("pd-desc").value || "").trim() || name;
    const type = document.getElementById("pd-type").value;
    const pluginJson = JSON.stringify({
      id: id, name: name, version: "1.0.0",
      description: desc, entry: "main.js",
    }, null, 2);
    const mainJs = mainJsFor({ id: id, name: name, type: type });
    document.getElementById("pd-plugin-json").textContent = pluginJson;
    document.getElementById("pd-main-js").textContent = mainJs;
    document.getElementById("pd-dl-json").disabled = false;
    document.getElementById("pd-dl-js").disabled = false;
    document.getElementById("pd-dl-zip").disabled = false;
    window.__pdPluginJson = pluginJson;
    window.__pdMainJs = mainJs;
  }

  function makeZip() {
    if (!window.__pdPluginJson) return;
    const enc = new TextEncoder();
    const id = JSON.parse(window.__pdPluginJson).id;
    const zip = buildZip([
      { name: "plugin.json", data: enc.encode(window.__pdPluginJson) },
      { name: "main.js", data: enc.encode(window.__pdMainJs) },
    ]);
    downloadBlob(zip, id + ".zip");
  }

  window.__pluginDevKit = { buildZip, crc32 };  // dev/test hook
  window.ShellPlugin.registerPage({
    id: "plugin-dev",
    title: "外壳插件开发套件",
    icon: "🧩",
    html: `
      <div class="card">
        <h2>生成插件骨架</h2>
        <div class="field"><label>插件 id（英文，唯一）</label>
          <input id="pd-id" type="text" placeholder="my-first-plugin"></div>
        <div class="field"><label>显示名称</label>
          <input id="pd-name" type="text" placeholder="我的第一个插件"></div>
        <div class="field"><label>描述</label>
          <input id="pd-desc" type="text" placeholder="一句话说明用途"></div>
        <div class="field"><label>类型</label>
          <select id="pd-type" style="max-width:220px;">
            <option value="card">卡片（挂到既有页面）</option>
            <option value="page">独立页面（新增导航）</option>
          </select></div>
        <button id="pd-gen" class="btn primary" type="button">生成骨架</button>
      </div>
      <div class="card">
        <h2>生成结果</h2>
        <pre id="pd-plugin-json" class="log-view" style="height:140px;">（点击「生成骨架」）</pre>
        <pre id="pd-main-js" class="log-view" style="height:140px;"></pre>
        <div class="key-row" style="margin-top:10px;">
          <button id="pd-dl-json" class="btn small" type="button" disabled>下载 plugin.json</button>
          <button id="pd-dl-js" class="btn small" type="button" disabled>下载 main.js</button>
          <button id="pd-dl-zip" class="btn small primary" type="button" disabled>打包下载 zip（可直接导入）</button>
        </div>
        <div class="hint" style="margin-top:8px;">
          zip 下载后到「插件 → 外壳插件 → 导入外壳插件（本地 zip）」安装；
          复杂插件请配合「生成插件提示词」把本页骨架与想法一起交给同工作区新对话用创造模式开发。
        </div>
      </div>`,
    onShow() {
      document.getElementById("pd-gen").addEventListener("click", generate);
      document.getElementById("pd-dl-json").addEventListener("click", () =>
        downloadBlob(new Blob([window.__pdPluginJson || ""],
          { type: "application/json" }), "plugin.json"));
      document.getElementById("pd-dl-js").addEventListener("click", () =>
        downloadBlob(new Blob([window.__pdMainJs || ""],
          { type: "text/javascript" }), "main.js"));
      document.getElementById("pd-dl-zip").addEventListener("click", makeZip);
    },
  });
})();
