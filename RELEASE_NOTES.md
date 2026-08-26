# DeepSeek Harness for Windows v1.0.2 发布声明

**发布日期**：2026-08-27
**项目主页**：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows
**版本标签**：v1.0.2

## 一、版本介绍

DeepSeek Harness for Windows 是基于 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）官方源码构建的 **Windows 桌面封装**，为不熟悉命令行的用户提供完整的图形化体验。

本版本（v1.0.2）聚焦两件事：**数据随软件走（实例隔离、不占 C 盘）** 与 **对 dsh-web 插件生态的全量兼容**。

### 1. 插件与数据全部迁入软件目录（不占 C 盘）

- 全部插件、会话、设置、皮肤、宠物、任务看板等用户数据统一保存在安装目录下的
  **`data\` 文件夹**（`data\.dsh`），不再写入 `C:\Users\<用户>\.dsh`，卸载/移动安装
  目录即可带走全部数据
- 首次启动 v1.0.2 自动**迁移**旧数据：`~/.dsh` 整体移动到 `data\.dsh`（robocopy
  逐文件校验，成功后才会清理 C 盘旧目录；失败自动重试、绝不丢数据），并自动修复
  插件 `file:` 安装路径
- 插件安装时的 pnpm 包仓库与缓存同样重定向到 `data\` 内（`.pnpm-store` /
  `.pnpm-cache`），插件导入缓存亦入 `data\plugin-cache`

### 2. 实例隔离

- 每个安装目录是一套完整独立实例：独立的 `data\`、独立的 `config.json`、独立的端口
  - 同机多实例：默认端口 3080 被占用时自动改用空闲端口并记住
  - 停止服务时只清理本实例的进程，不会误杀其他实例的核心
- 实例可整体复制/移动/改名（首次启动自动修复 junction 与插件路径）

### 3. dsh-web 仓库插件全量兼容

针对 [zhu1090093659/dsh-web](https://github.com/zhu1090093659/dsh-web) 全家族插件
（`@linxin666/dsh-*`，含聚合包 `dsh-web-all`）做了适配：

- 核心进程与插件操作统一注入 `DSH_HOME`，插件的主目录解析（profiles / sessions /
  task-board / skins / pets / worktrees / ssh 配置等）自动落在安装目录内
- 内置 `dsh.cmd` 命令 shim 并加入核心进程 PATH：`dsh-doctor`、
  `dsh-plugin-manager`、`dsh-desktop-launcher` 等需要定位并调用 `dsh` CLI 的插件
  开箱可用；内置 node / pnpm 同步暴露（`dsh-remote-web-ui` 的更新流程可用）
- 自动预置 profile 的 `pnpm-workspace.yaml`：`nodeLinker: hoisted`、
  `allowBuilds`（cloudflared / cpu-features / esbuild / node-pty / ssh2）、
  `minimumReleaseAgeExclude: ['@linxin666/*']`，解决聚合包安装、原生依赖构建与
  pnpm 11 发布年龄门禁三类安装失败
- pnpm 包仓库/缓存重定向（见上），插件触发的安装/更新不再写 C 盘

> 说明：插件自身的"真实用户目录"依赖（`~/.ssh/config` 导入、桌面快捷方式、
> `~/.agents` 技能目录、项目内 `.dsh/skills`）按设计保留指向真实用户目录；
> `git`、`bash`（dsh-liangshen 的 bash 工具）等系统命令仍需系统安装，未安装时
> 相关插件功能不可用。

### 4. 外壳在线升级

- 「关于」页「检查应用更新」升级为完整升级流程：发现新版本 → **一键下载升级包**
  （SHA256 校验）→ **一键安装**（退出外壳 → 自动覆盖安装 → 自动重启）
- 安装覆盖时 Windows 会请求一次系统确认（UAC，安装程序文件名启发式），确认后全自动
- 升级包 `DeepSeekHarness-<版本>-Update.exe` 只覆盖程序文件，**保留**
  `data\`（插件与数据）、`ui\`（自定义界面）、`config.json` 与日志；升级引导脚本
  含自愈兜底：即使升级包后置脚本未执行，也会自动重建核心链接并重新启动应用
- 全量安装包（`-Setup.exe`）与升级包（`-Update.exe`）同时发布在 GitHub Releases，
  附 SHA256 校验文件

### 5. 其他

- 「关于」页新增「数据目录」显示（悬停可见 DSH_HOME 具体路径）
- 修复：停止服务时可能误杀其他 dsh 实例进程；端口冲突直接启动失败

## 二、版本变更

| 模块 | 变更 |
| --- | --- |
| 数据目录 | 新增 `data\` 实例数据目录与 `data_dir` 配置；启动时导出 `DSH_HOME=<安装目录>\data\.dsh`（新增 `app/homes.py`） |
| 旧数据迁移 | 首次启动把 `~/.dsh` 移动到 `data\.dsh`（robocopy + 成功标记 + 失败重试），并修复 `file:` 插件依赖路径 |
| 插件兼容 | 内置 `dsh.cmd` shim；核心进程 PATH 注入内置 node/pnpm；pnpm store/缓存重定向；profile `pnpm-workspace.yaml` 自动预置/修复 |
| 实例隔离 | 端口占用自动切换空闲端口；孤儿进程清理限定本实例 core 目录 |
| 应用升级 | 升级包下载（进度/SHA256）→ 引导脚本退出后静默覆盖安装 → 自动重启；发布资产解析（Setup/Update/sha256） |
| 配置 | 新增 `data_dir`；`app_version` 更新为 1.0.2 |
| 构建 | 新增 `scripts\make-release.ps1`（一键生成 Setup + Update 自解压包与 SHA256）；`build.ps1` 支持 `-Version` |
| UI | 「关于」页新增数据目录显示、升级包下载/安装按钮与进度 |

## 三、安装包与升级包

| 项目 | 说明 |
| --- | --- |
| 安装包 | `DeepSeekHarness-1.0.2-Setup.exe`（7-Zip 自解压，含完整程序） |
| 升级包 | `DeepSeekHarness-1.0.2-Update.exe`（静默覆盖升级，保留 data/ui/config/logs） |
| 校验 | `SHA256SUMS-1.0.2.txt` 与各包 `.sha256` 文件随 Release 发布 |
| 安装方式 | 双击安装包，选择安装目录（默认 `C:\DeepSeek Harness`），自动创建桌面快捷方式 |
| 升级方式 | 外壳「关于」页一键下载安装，或从 Releases 下载 `-Update.exe` 放在**安装目录内**双击运行 |
| 环境要求 | Windows 10/11（内置 Microsoft Edge WebView2） |

> 安装包/升级包未包含在本源码仓库中（GitHub 单文件 100 MB 限制），请在 Releases
> 页面下载：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows/releases

## 四、开源代码声明

本项目为 **MIT License** 开源项目，基于以下开源软件构建。在此向各开源项目的作者与贡献者表示感谢：

| 组件 | 版本 | 用途 | 许可证 | 链接 |
| --- | --- | --- | --- | --- |
| deepseek-ai/deepseek-harness | master（对应 `dsh-0.1.1-rc.2`） | 核心服务器与 Web 界面 | Apache-2.0（遵循上游声明） | https://github.com/deepseek-ai/deepseek-harness |
| dsh-market/dsh-market | dshmarket 1.21.4（由本地源码归档构建） | 插件商店（内置预装，初始关闭，启用离线） | MIT | https://github.com/dsh-market/dsh-market |
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
插件生态，以及 pywebview、PyInstaller、Node.js、pnpm、7-Zip 等开源社区项目为本版本提供的支持。
