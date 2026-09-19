# DeepSeek Harness for Windows v1.0.5 发布声明

**发布日期**：2026-09-20
**项目主页**：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows
**版本标签**：v1.0.5

## 一、版本介绍

DeepSeek Harness for Windows 是基于 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）官方源码构建的 **Windows 桌面封装**，为不熟悉命令行的用户提供完整的图形化体验。

v1.0.5 是**缺陷修复版**，解决三件事：

1. **工作台退出全屏后界面只剩一条边**（外壳 UI 布局缺陷，1.0.0 起就存在）；
2. **核心（内核）升级 / 降级无法完成**（`core.backup` 因 Windows 路径长度限制删不掉，
   一旦出现过一次失败，之后所有核心更新都会失败）；
3. **全版本内核适配**：内核入口、启动参数、配置转储均改为“探测式”，
   升级到新内核或回退到旧内核都能正常启动，不再依赖某个具体版本的路径与命令行写法。

本版**随包内核升级到上游最新版**：`dsh 0.1.6-alpha.2`
（tag `dsh-v0.1.6-alpha.2`，upstream commit `ddefc45`，2026-09-17），
安装后无需联网即可直接使用最新内核；旧内核仍可通过「核心更新」页选择版本回退
（已在开发实例实测升级 / 降级 / 再升级）。

同时修复了“升级包不会刷新外壳界面”的发布缺陷：1.0.3 / 1.0.4 的安装即使升级到新版，
外壳界面也不会被更新，等于修好的 bug 送不到用户手里。

## 二、缺陷与修复

### 0. 1.0.3 起「看起来有、实际没生效」的功能（本版逐一修好）

| 功能 | 症状 | 根因 | 修复后实测 |
| --- | --- | --- | --- |
| **外观（主题）系统** | 设置页有 5 个外观可选，点任何一个都没反应 | 内置外观用的是相对路径（`themes/ocean.css`），而 `applyTheme` 只对 `http(s)://`、`//`、`/` 开头的值发起请求，于是把**路径字符串本身**当成 CSS 注入 | 点击「浅色」→ 注入 1361 字符真实 CSS，背景 `rgb(14,17,22)` → `rgb(244,246,250)`，选中态正确 |
| **界面语言切换（中/英）** | 选 English 后界面仍是中文 | `applyI18n` 用文本节点**整串**精确匹配字典键，而导航文本节点带缩进换行（`<span>◇</span>插件\n        `），永远匹配不上 | 选 English → 导航「◇插件」→「◇Plugins」，并写入 `ui_state.lang` |
| **添加商店源** | 点击即报错，永远添加不上 | `#store-catalog` 同时是目录列表 `<div>` 与目录地址 `<input>`（HTML 重复 id），`getElementById` 取到 div、`.value` 为 `undefined` → `TypeError` | 输入框独立为 `store-catalog-url`，点击后正常调用 `store_add`（点击穿透审计实测 `store_add` 已触发） |
| **取消核心更新** | 长更新（下载 + 重建内核，数分钟到数十分钟）无法中止 | `cancel_update` 与 `CoreUpdater.cancel()` 早已实现，但界面上没有任何入口 | 更新页进度卡片新增「取消更新」按钮，仅更新中显示；实测点击后调用 `cancel_update` |

附带修复：**卸载插件先校验**——`remove_plugin` 之前对任何名字都回「操作已开始」，再异步失败；
现在与「停用」一致，先校验是否为已安装依赖并给出明确提示。

### 0.1 随包内容调整

**示例外壳插件不再随任何安装包分发**：`example-status`、`example-pet`、`plugin-dev-kit`
移到仓库 `examples/shell-plugins/`（附 README 说明如何作为用户插件导入试用），
`app/ui/plugins/` 不再随包——安装后「外壳插件」列表为空，产品里不再出现示例/开发用插件。

### 1. 退出全屏后工作台 iframe 塌陷（只显示一条边）

**现象**：启动服务器后外壳自动进入全屏（沉浸模式）；点「⇤ 退出全屏」后，工作台只剩
顶部一条约 150px 高的窄条，其余是空白；有时还伴随外层滚动条。

**根因**：`.frame-wrap` 的高度由父级 flex 决定（`flex: 1; height: auto`），此时子元素
iframe 的 `height: 100%` 无法解析成确定值，浏览器按 `auto` 处理并回落到 iframe 的
**默认高度 150px**；沉浸模式下容器高度是 `100vh`（确定值）所以正常，一退出全屏就暴露。
用 Edge/WebView2 同内核的真实渲染实测（`tools/immersive-check/`，退出全屏后实测
iframe 高度 **150px**、容器 624px）：

| 场景 | 修复前 iframe | 修复后 iframe | 容器 |
| --- | --- | --- | --- |
| 启动后（全屏） | 1250×725 | 1250×725 | 1250×725 |
| 退出全屏 | **980×150** | 980×622 | 982×624 |
| 反复切换 | **980×150** | 980×622 | 982×624 |
| 切到别的页面再回来 | **980×150** | 980×622 | 982×624 |
| 窄窗口（1000×640） | **730×150** | 730×484 | 732×486 |
| 停止服务器（空状态） | 空状态不铺满 | 980×569 | 982×571 |

**修复**：iframe 与空状态改为绝对定位铺满容器（`position: absolute` +
`top/right/bottom/left: 0`），不再依赖百分比高度能否解析；沉浸模式下不再把
`.frame-wrap` 改成 `position: static`（否则绝对定位子元素的包含块会变成视口）；
顺带修正非全屏时的双滚动条。

### 2. 内核升级 / 降级失败：`core.backup` 无法删除

**现象**：从「核心更新」页选择版本更新，进度走到最后一步报
“无法切换核心目录（文件被占用）: backup removal failed”，重试多少次都一样；
此后**任何**核心更新都无法完成。

**根因**：pnpm 的目录树普遍超过 Windows `MAX_PATH`（260 字符），例如

```
core\backup\node_modules\.pnpm\@mistralai+mistralai@2.2.6_...\node_modules\@mistralai\
mistralai\esm\models\operations\executepostworkflowregistrationv1workflows....d.ts   (>300 字符)
```

`shutil.rmtree`（普通路径）和 `cmd /c rmdir /s /q` 都会以 **WinError 3** 失败；
旧实现因此把上一次失败更新留下的 `core.backup` 永远删不掉，而删除失败被当成致命错误，
于是每次换核都在第一步就失败。实测：同一目录用新实现的
`homes.remove_tree()` **0.0 秒删除成功**。

**修复**：

- 新增 `homes.remove_tree()`：`\\?\` 扩展长度路径递归删除，兼容只读文件（git pack
  文件默认只读）、**绝不跟随 junction**（不会误删实例 pnpm store 的内容）、
  robocopy 空目录镜像 + `rmdir` 兜底；
- 换核前校验待安装核心（目录存在、CLI 入口存在），失败信息不再误报“文件被占用”；
- 换核失败自动把旧核心放回原位；换核后校验新核心可启动，不通过则回滚；
- 删不掉的陈旧备份不再阻塞更新（改用带时间戳的新备份名），下次启动继续清理；
- 每次启动后台清理历史遗留的 `core.backup*`。

### 3. 全版本内核适配（升级 / 降级都能用）

#### 3.1 最新内核拒绝裸地址：工作台会显示 401 错误页

dsh **0.1.6-alpha.2** 起，`dsh web` 启动时打印的不再是裸地址，而是带随机 token 的地址：

```
dsh web: http://127.0.0.1:3080/?token=8drWFuoGUEbPci3rbjIXyigRCJ40jb_V1vVOQTW9pf8
```

并且**拒绝一切不带 token 的请求**：`GET /` → `401 dsh web authentication required;
reopen the URL printed by dsh web`。1.0.4 及以前固定把
`http://127.0.0.1:<端口>/` 交给 WebView 加载，因此在最新内核上工作台只会显示这个 401
错误页——界面完全不可用（实测：iframe 内部页面 `#root` 不存在、正文就是那句
authentication required）。

**修复**：启动器读取内核启动输出里打印的地址（含 token），用它作为工作台 iframe 与
「浏览器打开」的地址；内核只打印裸地址（旧版本）时自动回退，两边都正常。实测对照：

| 加载地址 | 最新内核 iframe 内部页面 |
| --- | --- |
| 裸地址 `http://127.0.0.1:3080/`（1.0.4 行为） | 401 错误页，`#root` 不存在，正文 “dsh web authentication required…” |
| 内核打印的 token 地址（1.0.5） | 真实界面挂载成功：标题「DSH 本地构建」、版本 0.1.6-alpha.2-9f209c3、会话列表与输入框齐全 |

#### 3.2 其余适配项

| 项目 | 1.0.4 及以前 | 1.0.5 |
| --- | --- | --- |
| CLI 入口 | 硬编码 `core\apps\cli\lib\bin.js` | 解析 `apps/cli/package.json` 的 `bin.dsh`，回退旧路径（构建脚本、冒烟测试同步改为解析式） |
| 启动参数 | 固定 `web --no-open --port N --host 127.0.0.1` | 7 级候选梯度（`web … --host` → `--profile web …` → 去 `--host` → 纯 `web`），仅在识别到“未知参数/未知命令”时降级重试，成功组合记入 `config.json`，换核后自动重新探测 |
| 启动地址 | 固定裸地址 | 读取内核打印的地址（含 token），无输出时回退裸地址 |
| 启动失败判断 | 90 秒超时 / 进程退出 | 8 秒快速窗口内退出即判定为“命令被拒绝”，并只使用**本次尝试**的日志判定，避免旧日志干扰 |
| 健康检查 | 固定 `--dump-config`，不认识就报“异常” | 依次尝试 `--profile web --dump-config` / `web --dump-config` / `--dump-default-config`，不认识则记为“该版本不支持”而非损坏 |
| 版本号 | 根 `package.json` | 根 `package.json` → `apps/cli/package.json` 依次回退 |
| 孤儿进程清理 | 匹配硬编码路径 | 匹配解析出的入口相对路径（兼容新旧布局） |

### 4. 非英文 Windows 上的子进程乱码崩溃

Windows 命令行工具（`mklink`、`netstat`、`robocopy`、PowerShell）按**控制台代码页**
输出（简体中文为 GBK），不是 UTF-8。1.0.4 对这些输出使用 UTF-8 解码：解码发生在
subprocess 的读取线程里，一旦遇到 GBK 字节就抛 `UnicodeDecodeError`。

实测一次核心换核（换核后需重建数千个 pnpm workspace junction）产生
**3400 多条异常堆栈**，并且 junction 重建期间随时可能中断——这类崩溃正是“核心更新
看起来失败/卡住”的一部分。修复：统一使用 OEM 代码页 + `errors="replace"` 解码
（`homes.console_text_kwargs()`），PowerShell 调用额外强制
`[Console]::OutputEncoding=UTF8`，修复后同一次换核的异常堆栈为 **0**。

### 5. 升级后外壳界面不刷新（发布链路缺陷）

1.0.4 的 `post-update.bat` 只在 `ui\.version` 标记**不存在**时才安装随包外壳 UI。
所有 1.0.3 / 1.0.4 安装都已有该标记，因此升级后仍然使用旧界面——本次修好的
全屏 bug 也就永远送不到用户手里。

**修复**：安装脚本按版本号比对刷新（旧目录保留为 `ui-backup`）；启动器每次启动也会
比对随包 UI 与在装 UI 的版本并自动刷新（覆盖手动复制、极简包、只换 `_internal` 等路径），
旧目录保留为 `ui-backup-<旧版本>`，用户自定义的界面文件不会静默丢失。

## 三、测试与验证

| 测试 | 内容 | 结果 |
| --- | --- | --- |
| `tools/test-1.0.5.py` | **119 项**：超 MAX_PATH 删除、只读文件、junction 不跟随、入口解析 5 种布局、启动梯度、内核打印地址（token/裸地址/无输出）、usage 错误识别、控制台输出解码、健康检查容忍度、换核 / 回滚 / 陈旧备份、外壳 UI 同步（含不降级）、CSS 不变式、**重复 id / 主题加载 / i18n 空白匹配 / 取消更新控件 / 示例插件不随包 / 卸载校验** | **119/119 通过** |
| `tools/audit-features.py` | 静态交叉核对：DOM id 引用与重复、`callApi` ↔ Bridge 方法、按钮是否有实现、示例插件是否随包 | **ALL CHECKS PASS** |
| `tools/audit-backend.py` | **49 项**后端功能核对：对临时实例逐个调用全部 Bridge 方法，校验返回结构与持久化（含 API Key 的 DPAPI 加密往返） | **49/49 通过** |
| `tools/immersive-check/` | Edge 153（与随应用 WebView2 同内核）无头驱动真实点击：8 个布局场景 + 真实内核 iframe 挂载 + 外观切换 + 全页面/全按钮点击穿透（核对「按钮 → 桥方法」）+ 取消更新 + 新手引导 + 语言切换，共 **13 个场景** | **13/13 通过**（修复前 6 个场景失败） |
| `tools/core-update-test/run_core_update.py` | 用启动器自身的更新管线，在 `dist\DeepSeek Harness` 开发实例里真实下载 → 构建 → 换核 → 健康检查 → 启动校验 | 升级 / 降级 / 再升级 **全部通过** |
| `tools/core-update-test/test_launch_ladder.py` | 真实 dsh CLI：故意把坏参数放在候选梯度最前面，验证自动降级并记住可用组合 | **10/10 通过**（0.1.1-rc.2 与 0.1.6-alpha.2 各一轮） |
| `tools/core-update-test/test_plugin_on_core.py` | 用启动器自身的插件管理在真实实例上安装 / 列出 / 卸载随包 dshmarket | **8/8 通过**（两个内核各一轮） |

真机内核升级 / 降级（开发实例 `dist\DeepSeek Harness`）：

| 动作 | 起始内核 | 目标内核 | 旧核心备份 | 健康检查 | 启动地址 | HTTP |
| --- | --- | --- | --- | --- | --- | --- |
| 升级 | dsh 0.1.1-rc.2 | dsh 0.1.6-alpha.2 | 已回收 | exit 0 | 带 token 的地址 | 200 |
| 降级 | dsh 0.1.6-alpha.2 | dsh 0.1.1-rc.2 | 已回收 | exit 0 | 裸地址 | 200 |
| 再升级 | dsh 0.1.1-rc.2 | dsh 0.1.6-alpha.2 | 已回收 | exit 0 | 带 token 的地址 | 200 |

完整数据见 `docs/TEST-REPORT-1.0.5.md`。

## 四、版本变更

| 模块 | 变更 |
| --- | --- |
| 随包内核 | `core\` 更新为上游最新版 **dsh 0.1.6-alpha.2**（tag `dsh-v0.1.6-alpha.2`，commit `ddefc45`，2026-09-17）：重新构建（`pnpm install` + `pnpm build`）、重定位 3438 个 pnpm workspace junction、写入 `.dsh-desktop-info.json` / `.upstream-commit` 标记 |
| 外观/语言 | `app/ui/app.js`：`applyTheme` 按“是否含规则块”区分 CSS 文本与样式表地址，失败时移除旧外观；`app/ui/i18n.js`：文本节点按去空白后的内容查表并保留原空白 |
| 商店/插件 | `app/ui/index.html`：目录地址输入框改用唯一 id `store-catalog-url`（消除重复 id）；`app/plugins.py`：`remove()` 先校验是否已安装 |
| 核心更新 | `app/ui/index.html` + `app/ui/app.js`：新增「取消更新」按钮（仅更新中显示）并接入 `cancel_update` |
| 示例插件 | `app/ui/plugins/*` → `examples/shell-plugins/*`（含 README），不再随包分发；新增回归检查确保不会再被误打包 |
| 外壳 UI | `app/ui/style.css`：iframe / `.frame-empty` 绝对定位铺满；沉浸模式保持 `position: relative`；去除双滚动条。`app/ui/app.js`：启动服务器后使用内核打印的地址（含 token） |
| 内核管理 | `app/homes.py` 新增 `remove_tree()`（`\\?\` 长路径、只读、junction 安全）、`long_path()`、`console_text_kwargs()`、`version_newer()`；`app/updater.py` 换核前校验、失败回滚、成功校验、陈旧备份不阻塞、`cleanup_stale_core_backups()`；启动时后台清理 |
| 内核适配 | `app/core_api.py`：`resolve_cli_entry()`、入口/版本解析回退链、7 级启动候选梯度、按次日志判定、日志句柄回收、**内核打印地址（token）发现**；`app/homes.py` 健康检查多形态容忍 |
| 乱码崩溃 | `app/relink.py` / `app/junctions.py` / `app/core_api.py` / `app/main.py`：子进程输出按 OEM 代码页解码，PowerShell 强制 UTF-8 输出 |
| 界面刷新 | 新增 `app/shellui.py`（启动时按版本刷新外壳 UI，保留备份且不降级）；`post-update.bat` 按版本比对刷新；`app/ui/.version` 1.0.5 |
| 构建发布 | `build.ps1` / `scripts/smoke-release.ps1` 解析式 CLI 入口；`make-release.ps1` / `upload-release.ps1` 默认版本 1.0.5 |
| 测试 | 新增 `tools/test-1.0.5.py`、`tools/immersive-check/`、`tools/core-update-test/`；`.gitignore` 允许提交 `tools/` 下的测试脚本（仍忽略随包二进制） |

## 五、安装包与升级包

| 项目 | 说明 |
| --- | --- |
| 懒人包安装/升级 | `DeepSeekHarness-1.0.5-Setup.exe` / `-Update.exe`（内置 Node + Git，推荐） |
| 极简包安装/升级 | `DeepSeekHarness-1.0.5-Minimal-Setup.exe` / `-Minimal-Update.exe`（无内置运行时） |
| 校验 | `SHA256SUMS-1.0.5.txt` / `SHA256SUMS-1.0.5-Minimal.txt` 与各包 `.sha256` 文件随 Release 发布 |
| 安装方式 | 双击安装包，选择安装目录（默认 `C:\DeepSeek Harness`），自动创建桌面快捷方式 |
| 升级方式 | 外壳「关于」页一键下载安装（懒人包），或从 Releases 下载对应 `-Update.exe` 放在**安装目录内**双击运行 |
| 环境要求 | Windows 10/11（内置 Microsoft Edge WebView2）；极简包需自装 Node.js LTS（可选 Git） |

> 安装包/升级包未包含在本源码仓库中（GitHub 单文件 100 MB 限制），请在 Releases
> 页面下载：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows/releases

## 六、开源代码声明

本项目为 **MIT License** 开源项目，基于以下开源软件构建。在此向各开源项目的作者与贡献者表示感谢：

| 组件 | 版本 | 用途 | 许可证 | 链接 |
| --- | --- | --- | --- | --- |
| deepseek-ai/deepseek-harness | dsh-0.1.6-alpha.2（随包，2026-09-17，commit `ddefc45`；已实测 0.1.1-rc.2 ↔ 0.1.6-alpha.2 升级/降级） | 核心服务器与 Web 界面 | Apache-2.0（遵循上游声明） | https://github.com/deepseek-ai/deepseek-harness |
| dsh-market/dsh-market | dshmarket 1.33.0（官方 tgz 离线重打包） | 插件商店（内置预装，初始关闭，启用离线） | MIT | https://github.com/dsh-market/dsh-market |
| Git for Windows | 2.55.0.5（PortableGit） | 懒人包内置 git / Git Bash | GPL-2.0 | https://github.com/git-for-windows/git |
| pywebview | 6.2.1 | 桌面窗口（WebView2 宿主） | MIT | https://github.com/r0x0r/pywebview |
| PyInstaller | 6.22.2 | Python 启动器打包为 exe | GPL-2.0（含引导加载器例外） | https://github.com/pyinstaller/pyinstaller |
| Node.js | v24.16.0（便携版） | 内置运行时 | MIT | https://nodejs.org |
| pnpm（corepack） | 11.x | 核心依赖安装与构建、插件管理 | MIT | https://github.com/pnpm/pnpm |
| 7-Zip | — | 自解压安装包/升级包制作 | GNU LGPL / BSD 3-Clause | https://www.7-zip.org |
| Microsoft Edge WebView2 | 系统自带 | 渲染外壳 UI | 微软专有（系统组件） | https://developer.microsoft.com/microsoft-edge/webview2 |

## 七、免责声明

- 本项目仅是对上游开源项目的**桌面封装层**，核心功能与能力均来自上游 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 项目；本项目的任何修改不改变上游项目的许可证约束。
- 插件商店（dshmarket）与 dsh-web 系列插件均为第三方开源项目，安装前请确认来源可信。
- 使用本软件产生的 API 调用费用、数据安全等问题由使用者自行负责。
- 本项目按"原样"提供，不提供任何明示或默示的担保。

## 八、致谢

感谢 DeepSeek 团队开源的 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 项目、
[dsh-market](https://github.com/dsh-market/dsh-market) 插件市场项目、[zhu1090093659/dsh-web](https://github.com/zhu1090093659/dsh-web)
插件生态、Git for Windows，以及 pywebview、PyInstaller、Node.js、pnpm、7-Zip 等开源社区项目为本版本提供的支持。

---

# 历史版本

## v1.0.4（2026-09-09）

稳定性修复版：内部插件更新失败（ERR_PNPM_UNEXPECTED_STORE）自愈、外壳服务并发与断连容错、
外壳静默文件 MIME 修复、外壳插件自定义入口、桥方法白名单 / POST-only / DNS rebinding 防护、
内置商店源自愈、`DSH_DOCTOR_HOME` 实例化。完整声明见 git 历史与 Releases 页面。

## v1.0.3（2026-08-29）

双包发布（懒人包 / 极简包）、外壳插件系统与主题、系统托盘、DPAPI 密钥存储、
核心 tag 更新与回退、镜像与代理、健康检查、i18n、日志查看、实例面板、内置商店 1.33.0。

## v1.0.2 / v1.0.1 / v1.0.0

数据目录实例化（`<安装目录>\data\.dsh`）、dsh-web 插件家族兼容、应用内自升级、
核心组件 junction 恢复、本地核心 / 插件导入、插件商店多源目录、首次发行。
