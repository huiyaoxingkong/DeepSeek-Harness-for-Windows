/* 桌宠插件接口示例：注册一个可拖拽的浮动小球。
   完整桌宠（Live2D 等）可按同一接口实现：registerPet 返回挂载元素，
   getPetLayer() 获取全窗口透明挂载层，unregisterPet 卸载。 */
"use strict";
(function () {
  if (!window.ShellPlugin || !window.ShellPlugin.registerPet) return;
  const colors = ["#4d6bfe", "#0ea5b7", "#e8633a", "#3fa55c", "#fbbf24"];
  let i = 0;
  window.ShellPlugin.registerPet({
    id: "example-pet-ball",
    name: "示例小球",
    x: "calc(100% - 76px)",
    y: "140px",
    draggable: true,
    html: '<div style="width:44px;height:44px;border-radius:50%;' +
      'background:radial-gradient(circle at 30% 30%, #6d86ff, #4d6bfe);' +
      'box-shadow:0 4px 14px rgba(0,0,0,.4);cursor:grab;' +
      '" title="桌宠插件接口示例：按住拖动，点击变色"></div>',
    onMount(el) {
      el.addEventListener("click", () => {
        i = (i + 1) % colors.length;
        const ball = el.firstElementChild;
        if (ball) ball.style.background =
          `radial-gradient(circle at 30% 30%, ${colors[i]}, ${colors[i]})`;
      });
    },
  });
})();
