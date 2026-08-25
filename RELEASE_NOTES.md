# DeepSeek Harness for Windows v1.0.1 发布声明

**发布日期**：2026-08-24
**项目主页**：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows
**版本标签**：v1.0.1

## 一、版本介绍

DeepSeek Harness for Windows 是基于 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）官方源码构建的 **Windows 桌面封装**，为不熟悉命令行的用户提供完整的图形化体验。

本版本（v1.0.1）在 v1.0.0 基础上新增以下功能：

### 1. 核心本地导入（无代理环境可用）

「核心更新」页新增「从本地文件导入核心」：选择 deepseek-harness 源码压缩包
（`.zip`，GitHub 官方 archive 或自行备份的源码均可），应用使用内置工具链完成
依赖安装与构建并**原子切换核心**，失败自动回退。全程本地执行，GitHub 不可达时
也能更新核心。

### 2. 插件本地导入（无代理环境可用）

「插件」页新增「导入插件（本地文件）」：支持 npm 打包的 `.tgz / .tar.gz` 或
插件源码 `.zip`（自动解压后安装），从本地文件安装并自动启用，无需代理。

### 3. 外壳插件商店（始终启用）

「插件」页新增插件商店，外壳内置、**始终可用**，与 dsh-market 使用同一数据源
（awesome-dsh-plugin 目录，每日更新，2000+ 插件，双语描述）：

- **浏览 / 搜索**：分类筛选 + 关键词搜索，卡片显示名称、作者、Star、下载量、
  中文描述与仓库链接
- **安装 / 更新 / 卸载**：一键安装（优先 npm 包），已安装插件显示状态与版本，
  可一键更新或卸载

### 4. 多商店源支持（为兼容更多商店打基础）

- 商店源模型字段化：`name` / `label` / `spec` / `homepage` / `catalog` / `builtin`
- 支持导入更多商店源：名称 + 安装来源 + **目录地址**（plugins.json，至少一项；
  可添加"仅目录"源）
- 外壳商店**多源目录合并展示**，卡片标注来源（来源徽章链接到源主页）
- 单源目录加载失败不影响其他源，界面提示失败原因

### 5. 内置商店插件（安装但不开启）

- `dshmarket` 插件商店（[dsh-market/dsh-market](https://github.com/dsh-market/dsh-market)，
  1.21.4）由本地源码归档 `dsh-market-main.zip` 构建打包，运行时依赖
  （js-yaml / argparse / undici）一并内置，**应用内启用完全离线**，不再下载
- 首次启动后台**预装但不开启**（`cordis.patch.yml` 官方补丁层停用行，与
  dsh-market 自身的停用机制一致，不受后续插件操作影响）
- 商店卡片点「启用」即时生效，重启服务器后在 dsh Web「设置 → 插件市场」
  浏览社区插件

### 6. 其他

- **关于页**：新增「检查应用更新」（GitHub Releases，结果缓存 30 分钟）与
  「代码来源」清单（上游项目、许可证与用途）
- **Bug 修复**：
  - 应用版本在启动早期不显示（pywebview 桥未就绪时 HTTP 回退对无参方法调用失败）
  - 安装目录含空格（如 `C:\DeepSeek Harness`）时本地插件 / 商店安装失败
  - 商店更新 / 卸载接口缺少参数校验（防止误触发全量更新）

### 完整特性

- **exe 启动器**：WebView2 窗口 + 本地 Web UI（工作台 / 插件 / 设置 / 核心更新 / 日志 / 关于）
- **新手引导**：首次启动分步引导（工作台 / API Key / 插件与更新）
- **核心可更新 / 可本地导入**：GitHub 一键更新，或从本地源码压缩包导入（无需网络）
- **插件管理**：安装 / 卸载 / 启用 / 停用，支持 npm 包、git 仓库、本地路径与本地文件导入
- **插件商店**：外壳商店（目录浏览，始终启用）+ 多商店源 + 内置 dshmarket 商店（安装但不开启）
- **独立可换肤 UI**：外壳界面为纯 HTML/CSS/JS，可直接编辑自定义
- **内置 Node.js 运行时**：无需在系统安装 Node.js

## 二、版本变更

| 模块 | 变更 |
| --- | --- |
| 核心更新页 | 新增「从本地文件导入核心」（updater.py 支持本地 zip 构建流水线） |
| 插件页 | 新增「导入插件（本地文件）」与「插件商店」卡片 |
| 关于页 | 新增「检查应用更新」（GitHub Releases，结果缓存 30 分钟）与「代码来源」清单 |
| 外壳商店 | 新增插件目录浏览：与 dsh-market 同一数据源（awesome-dsh-plugin，2000+ 插件、双语描述），支持搜索 / 分类筛选 / 一键安装 / 更新 / 卸载，始终可用 |
| 多商店源 | 商店源模型字段化（`homepage` / `catalog`）；支持导入更多源（含"仅目录"源）；多源目录合并展示，卡片标注来源 |
| 内置商店 | 由本地源码归档 `dsh-market-main.zip`（dshmarket 1.21.4）经 `scripts\build-store.ps1` 构建打包，运行时依赖一并内置，应用内启用完全离线 |
| 商店预装 | 首次启动后台预装内置商店（安装但不开启，`cordis.patch.yml` 停用行，兼容后续插件操作） |
| 商店 UI | 参考 dsh-market 客户端（Market.module.css）的卡片 / 状态徽章 / 版本号 / 来源标注设计 |
| 桥接 API | 新增 `pick_core_archive` / `import_core` / `pick_plugin_file` / `import_plugin` / `store_*` / `check_app_update` 方法 |
| 配置 | 新增 `store_sources` 字段（内置 dshmarket 预置源）；`app_version` 更新为 1.0.1 |
| Bug 修复 | 版本启动早期不显示；安装目录含空格时本地安装失败；商店操作缺参数校验 |
| 安装包修复 | 修复解压安装后核心缺失工作区链接导致服务器无法启动（`ERR_MODULE_NOT_FOUND`）的问题：随包附带 `core\junctions.json` 链接清单，安装脚本与应用启动自愈两种机制均用 `mklink /J` 重建（无需管理员权限） |

## 三、安装包

| 项目 | 说明 |
| --- | --- |
| 安装包 | `DeepSeekHarness-1.0.1-Setup.exe`（约 517 MB，7-Zip 自解压） |
| 安装方式 | 双击运行，选择安装目录（默认 `C:\DeepSeek Harness`），自动创建桌面快捷方式 |
| SHA256 | `650765D38813A6A649A198DFD0BAEFBDC90EC361089AE9E5010775EC48E0C650` |
| 环境要求 | Windows 10/11（内置 Microsoft Edge WebView2） |

> 安装包未包含在本源码仓库中（GitHub 单文件 100 MB 限制），请在 Releases 页面下载：
> https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows/releases

## 四、开源代码声明

本项目为 **MIT License** 开源项目，基于以下开源软件构建。在此向各开源项目的作者与贡献者表示感谢：

| 组件 | 版本 | 用途 | 许可证 | 链接 |
| --- | --- | --- | --- | --- |
| deepseek-ai/deepseek-harness | master（对应 `dsh-0.1.1-rc.2`） | 核心服务器与 Web 界面 | Apache-2.0（遵循上游声明） | https://github.com/deepseek-ai/deepseek-harness |
| dsh-market/dsh-market | dshmarket 1.21.4（由本地源码归档构建） | 插件商店（内置预装，初始关闭，启用离线） | MIT | https://github.com/dsh-market/dsh-market |
| pywebview | 6.2.1 | 桌面窗口（WebView2 宿主） | MIT | https://github.com/r0x0r/pywebview |
| PyInstaller | 6.22.2 | Python 启动器打包为 exe | GPL-2.0（含引导加载器例外） | https://github.com/pyinstaller/pyinstaller |
| Node.js | v24.16.0（便携版） | 内置运行时 | MIT | https://nodejs.org |
| pnpm（corepack） | 11.x | 核心依赖安装与构建 | MIT | https://github.com/pnpm/pnpm |
| 7-Zip | — | 自解压安装包制作 | GNU LGPL / BSD 3-Clause | https://www.7-zip.org |
| Microsoft Edge WebView2 | 系统自带 | 渲染外壳 UI | 微软专有（系统组件） | https://developer.microsoft.com/microsoft-edge/webview2 |

## 五、免责声明

- 本项目仅是对上游开源项目的**桌面封装层**，核心功能与能力均来自上游 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 项目；本项目的任何修改不改变上游项目的许可证约束。
- 插件商店（dshmarket）为第三方开源插件，商店中的插件均为第三方代码，安装前请确认来源可信。
- 使用本软件产生的 API 调用费用、数据安全等问题由使用者自行负责。
- 本项目按"原样"提供，不提供任何明示或默示的担保。

## 六、致谢

感谢 DeepSeek 团队开源的 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 项目、
[dsh-market](https://github.com/dsh-market/dsh-market) 插件市场项目，以及 pywebview、PyInstaller、
Node.js、pnpm、7-Zip 等开源社区项目为本版本提供的支持。
