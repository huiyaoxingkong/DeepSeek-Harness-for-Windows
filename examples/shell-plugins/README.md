# 外壳插件示例（仅供开发参考，不随安装包分发）

本目录是**外壳插件（Shell Plugin）的开发参考**。1.0.5 起，这些示例**不再预装进任何安装包**
（懒人包 / 极简包 / 升级包都不再包含 `ui\plugins\`），保留在源码仓库里只作开发参考。

| 目录 | 说明 | 演示的接口 |
| --- | --- | --- |
| `example-status/` | 在「关于」页追加运行状态卡片（时钟 + 服务器状态） | `ShellPlugin.registerCard` |
| `example-pet/` | 可拖拽的浮动桌宠小球，点击变色 | 桌宠接口（`ShellPlugin.pet` 挂载层 `#shell-pet-layer`） |
| `plugin-dev-kit/` | 外壳插件开发套件：可视化生成插件骨架并打包 zip | `registerPage` / `registerAction` / 骨架与打包实现参考 |

## 如何在外壳里试用

外壳插件是 zip 包（`plugin.json` + `main.js` + 可选静态资源），两种方式：

1. **作为用户插件导入（推荐）**：把插件目录压成 zip，在外壳「插件 → 导入外壳插件」里选择该 zip。
   用户插件安装到 `<安装目录>\data\shell-plugins\<id>\`，随实例数据保存，升级不会覆盖。
2. **作为内置插件**：把插件目录复制到 `<安装目录>\ui\plugins\<id>\`（需要重新打包时才随包分发）。

## 规范速览（ShellPlugin API v1）

`plugin.json`：

```json
{ "id": "my-plugin", "name": "显示名", "version": "0.1.0", "description": "一句话说明", "entry": "main.js" }
```

`main.js` 在 `window.ShellPlugin` 上注册：

- `registerPage({ id, title, icon, html, onShow })` —— 新增左侧导航页面
- `registerCard({ pageId, id, title, html, onMount })` —— 在既有页面追加卡片
  （`pageId` 可选：`workspace` / `plugins` / `settings` / `update` / `logs` / `about`）
- `registerAction({ pageId, id, label, onClick })` —— 在页面头部追加按钮
- `registerTheme({ id, name, css })` —— 注册外观：`css` 可以是 CSS 文本，也可以是样式表地址
  （内置外观用相对路径 `themes/xxx.css`）
- `on(evt, fn)` / `emit(evt, data)` —— 事件总线；`callApi(method, payload)` —— 调用外壳桥
- `log(...)` —— 写入外壳日志

约束：纯 HTML/CSS/JS，不依赖构建工具；不要向公网发起请求；不得覆盖 `window.ShellPlugin`。

## 开发与验证

`plugin-dev-kit` 的源码同时给出了「生成骨架 → 打包 zip」的完整实现，可直接照抄；
外壳侧的插件加载、启用/停用、导入、主题注册等逻辑见 `app/shellplugins.py` 与 `app/ui/app.js`。
