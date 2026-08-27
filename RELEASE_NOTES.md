# DeepSeek Harness for Windows v1.0.3 发布声明

**发布日期**：2026-08-27
**项目主页**：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows
**版本标签**：v1.0.3

## 一、版本介绍

DeepSeek Harness for Windows 是基于 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）官方源码构建的 **Windows 桌面封装**，为不熟悉命令行的用户提供完整的图形化体验。

本版本（v1.0.3）在 v1.0.2 实例隔离与 dsh-web 全量兼容的基础上，聚焦四件事：**双包发布（懒人包 / 极简包）**、**外壳插件化与外观系统**、**桌面体验（托盘 / 自启 / 沉浸记忆）** 与 **安全运维（密钥加密 / 升级回滚 / 健康检查）**。

### 1. 双包发布：懒人包与极简包

- **懒人包（默认）**：内置便携 Node.js + **便携 Git for Windows 2.55**（git.exe + Git Bash）。
  核心与插件进程 PATH 自动注入 Git 目录——dsh-web 生态的 `dsh-git-graph`（git 图形）、
  `dsh-liangshen`（bash 工具）、插件的 git 源安装**开箱可用**，不再依赖系统安装 Git。
- **极简包（`-Minimal-`）**：不内置任何运行时，体积更小；应用自动检测系统 Node / Git，
  设置页「运行环境」卡片显示内置 / 系统 / 缺失状态；缺失时对应功能优雅降级并给出指引。
- 同一版本同时发布两套 Setup / Update 安装包，懒人包保持原资产名（应用内更新无缝），
  极简包带 `-Minimal-` 中缀（手动下载升级）。

### 2. 外壳插件系统 + 外观系统 + 桌宠接口

- **外壳插件化（参考核心插件模式）**：壳内插件以 zip（`plugin.json` + `main.js`）分发，
  经 `window.ShellPlugin` API 挂载新页面 / 卡片 / 页头按钮，支持本地导入、启用 / 停用 /
  卸载；内置示例插件（运行状态卡片、桌宠小球）。
- **生成插件提示词（创造模式开发流）**：插件页输入想法即可生成结构化开发提示词
  （含 ShellPlugin API 规范、约束与交付格式），复制到工作台同工作区的新对话中用
  **创造模式**开发外壳插件（壳内外联动方向已预留），产物 zip 一键回装。
- **外观系统**：内置 5 组外观（深邃黑 / 深海蓝青 / 暖橙霞光 / 森林绿 / 浅色），
  设置页一键切换、即时生效、自动记忆；插件经 `registerTheme` 可提供无限新外观。
- **桌宠插件接口（预留）**：全窗口透明挂载层 + `registerPet / unregisterPet /
  getPetLayer`（支持拖拽与生命周期回调），完整桌宠（Live2D 等）按同一接口实现。

### 3. 桌面体验

- **系统托盘**：托盘图标 + 菜单（打开主界面 / 启动服务器 / 停止服务器 / 退出），
  左键点击恢复窗口；新增「关闭窗口时最小化到系统托盘（后台运行）」与「开机自启」开关。
- **工作台布局与沉浸**：嵌入区全宽铺满（修复全屏时两侧留白与双重滚动条），
  沉浸模式状态记忆（重启恢复）、淡入切换、停止服务器自动退出沉浸。

### 4. 安全与运维

- **API Key DPAPI 加密**：`config.json` 不再明文保存密钥（Windows DPAPI 用户级加密，
  仅同机同用户可解）；旧明文密钥首次启动自动迁移。
- **升级回滚**：应用升级前备份 exe，升级失败自动恢复。
- **迁移 / 升级健康检查**：启动后自动 `dump-config` 验证插件层与数据目录落位，
  结果在日志页卡片展示。
- **核心版本选择**：支持按发布版本（tag）更新或回退（不再只跟 master）。
- **网络适配**：HTTP 代理 / npm registry 镜像 / GitHub 下载镜像三配置。
- **日志页增强**：关键词过滤、错误/警告着色、一键复制、下载日志文件。
- **中英双语**：界面语言一键切换并记忆；**本机实例面板**：查看同机运行实例与端口。

### 5. 修复与生态

- 修复安装包中文文件名乱码（旧版残留乱码文件启动时自动清理）。
- dshmarket 商店升级 **1.33.0**（离线重打包，依赖内嵌，预装仍零网络）。
- 核实：内置核心即上游最新（`dsh-0.1.1-rc.2`，master 顶点）；dsh-web 家族适配基线
  `0.3.5` 即 npm 最新。

## 二、版本变更

| 模块 | 变更 |
| --- | --- |
| 双包发布 | `build.ps1/make-release.ps1/smoke-release.ps1` 支持 `-Flavor Lazy\|Minimal`；懒人包内置便携 Git（`scripts/download-portable-git.py`）；极简包省略运行时拷贝 |
| 运行环境检测 | `homes.detect_tools()`（node/git/bash 内置/系统/缺失 + 包风味，缓存）；Git 目录注入核心与插件进程 PATH；极简模式优雅降级 |
| 外壳插件 | 新增 `app/shellplugins.py`（双根扫描/zip 导入/启停/卸载）；`ui_server` `/plugin/<id>/` 静态服务（越权拦截）；`ShellPlugin` JS API；内置示例插件 |
| 外观/桌宠 | 5 组内置外观（`app/ui/themes/`）；`registerTheme` 插件接口；桌宠挂载层与 `registerPet` 接口；示例桌宠插件 |
| 托盘/自启 | 新增 `app/tray.py`（ctypes Shell_NotifyIcon，零依赖）；`poll_tray` 桥命令队列；关闭到托盘、开机自启开关 |
| 核心更新 | `updater.list_core_releases()` + tag 构建/回退；代理 / npm 镜像 / GitHub 镜像全链注入 |
| 安全 | 新增 `app/crypto.py`（DPAPI）；密钥加密迁移；升级 exe 备份回滚；健康检查（`logs/health.json`） |
| UI | 工作台全宽铺满、沉浸记忆、加载指示、日志增强、中英双语（`app/ui/i18n.js`）、本机实例面板 |
| 商店 | dshmarket 1.21.4 → 1.33.0（`scripts/rebundle-store-tgz.py` 离线重打包） |
| 构建 | 压缩级别 9；核心构建后 `pnpm prune --prod` 裁剪发布体积；smoke 增加核心启动与中文名断言 |
| 修复 | SFX 中文名乱码（A1）；BOM 编码统一（含中文的 ps1 全部 UTF-8 BOM） |

## 三、安装包与升级包

| 项目 | 说明 |
| --- | --- |
| 懒人包安装/升级 | `DeepSeekHarness-1.0.3-Setup.exe` / `-Update.exe`（内置 Node + Git，推荐） |
| 极简包安装/升级 | `DeepSeekHarness-1.0.3-Minimal-Setup.exe` / `-Minimal-Update.exe`（无内置运行时） |
| 校验 | `SHA256SUMS-1.0.3.txt` / `SHA256SUMS-1.0.3-Minimal.txt` 与各包 `.sha256` 文件随 Release 发布 |
| 安装方式 | 双击安装包，选择安装目录（默认 `C:\DeepSeek Harness`），自动创建桌面快捷方式 |
| 升级方式 | 外壳「关于」页一键下载安装（懒人包），或从 Releases 下载对应 `-Update.exe` 放在**安装目录内**双击运行 |
| 环境要求 | Windows 10/11（内置 Microsoft Edge WebView2）；极简包需自装 Node.js LTS（可选 Git） |

> 安装包/升级包未包含在本源码仓库中（GitHub 单文件 100 MB 限制），请在 Releases
> 页面下载：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows/releases

## 四、开源代码声明

本项目为 **MIT License** 开源项目，基于以下开源软件构建。在此向各开源项目的作者与贡献者表示感谢：

| 组件 | 版本 | 用途 | 许可证 | 链接 |
| --- | --- | --- | --- | --- |
| deepseek-ai/deepseek-harness | dsh-0.1.1-rc.2（master 顶点） | 核心服务器与 Web 界面 | Apache-2.0（遵循上游声明） | https://github.com/deepseek-ai/deepseek-harness |
| dsh-market/dsh-market | dshmarket 1.33.0（官方 tgz 离线重打包） | 插件商店（内置预装，初始关闭，启用离线） | MIT | https://github.com/dsh-market/dsh-market |
| Git for Windows | 2.55.0.5（PortableGit） | 懒人包内置 git / Git Bash | GPL-2.0 | https://github.com/git-for-windows/git |
| pywebview | 6.2.1 | 桌面窗口（WebView2 宿主） | MIT | https://github.com/r0x0r/pywebview |
| PyInstaller | 6.22.2 | Python 启动器打包为 exe | GPL-2.0（含引导加载器例外） | https://github.com/pyinstaller/pyinstaller |
| Node.js | v24.16.0（便携版） | 内置运行时 | MIT | https://nodejs.org |
| pnpm（corepack） | 11.x | 核心依赖安装与构建、插件管理 | MIT | https://github.com/pnpm/pnpm |
| 7-Zip | — | 自解压安装包/升级包制作 | GNU LGPL / BSD 3-Clause | https://www.7-zip.org |
| Microsoft Edge WebView2 | 系统自带 | 渲染外壳 UI | 微软专有（系统组件） | https://developer.microsoft.com/microsoft-edge/webview2 |

## 五、免责声明

- 本项目仅是对上游开源项目的**桌面封装层**，核心功能与能力均来自上游 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 项目；本项目的任何修改不改变上游项目的许可证约束。
- 插件商店（dshmarket）与 dsh-web 系列插件均为第三方开源项目，安装前请确认来源可信。
- 使用本软件产生的 API 调用费用、数据安全等问题由使用者自行负责。
- 本项目按"原样"提供，不提供任何明示或默示的担保。

## 六、致谢

感谢 DeepSeek 团队开源的 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 项目、
[dsh-market](https://github.com/dsh-market/dsh-market) 插件市场项目、[zhu1090093659/dsh-web](https://github.com/zhu1090093659/dsh-web)
插件生态、Git for Windows，以及 pywebview、PyInstaller、Node.js、pnpm、7-Zip 等开源社区项目为本版本提供的支持。
