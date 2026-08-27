/* 外壳插件示例：在「关于」页追加一个运行状态卡片。
   演示 window.ShellPlugin.registerCard 的用法，可作为开发外壳插件的起点。 */
"use strict";
(function () {
  if (!window.ShellPlugin) return;
  window.ShellPlugin.registerCard({
    pageId: "about",
    id: "example-status",
    title: "外壳插件 · 运行状态",
    html: '<div class="plugin-meta" id="example-status-line">加载中…</div>',
    onMount(card) {
      const line = card.querySelector("#example-status-line");
      const tick = async () => {
        try {
          const state = await window.ShellPlugin.callApi("get_state", {});
          const srv = state && state.server ? state.server : {};
          line.textContent = `${new Date().toLocaleString()} · 服务器：${srv.running ? "运行中 :" + srv.port : "未启动"}`;
        } catch (e) {
          line.textContent = `${new Date().toLocaleString()} · 状态获取失败`;
        }
      };
      tick();
      setInterval(tick, 5000);
    },
  });
})();
