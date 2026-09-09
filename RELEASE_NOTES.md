# DeepSeek Harness for Windows v1.0.4 发布声明

**发布日期**：2026-09-09
**项目主页**：https://github.com/huiyaoxingkong/DeepSeek-Harness-for-Windows
**版本标签**：v1.0.4

## 一、版本介绍

DeepSeek Harness for Windows 是基于 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）官方源码构建的 **Windows 桌面封装**，为不熟悉命令行的用户提供完整的图形化体验。

本版本（v1.0.4）是 v1.0.3 的**稳定性修复版**，聚焦排查结论中的四类问题：**内部插件更新失败**、**外壳与内部插件连接稳定性**、**外壳显示问题** 与 **插件更新兼容性**，并完成一轮安全加固（桥方法白名单、DNS rebinding 防护、路径穿越与 zip-slip 防护）。

### 1. 内部插件更新修复（ERR_PNPM_UNEXPECTED_STORE）

- 旧实例的 web profile 依赖在旧路径（`~/.dsh`）时期链接到了**用户全局 pnpm store**，与 1.0.3 起强制使用的实例内 store（`<数据目录>\store`）不一致，导致插件安装 / 更新 / 卸载全部报错。
- 现在**启动时自动检测** store 归属：不一致时把旧 store 的包内容合并进实例 store（同为 pnpm 11 布局，内容寻址文件直接复用，无需重新下载）、重建 profile 依赖，全程快照保护、忽略构建脚本（避免原生模块编译卡死）、自动清理残留。
- 插件操作过程中遇到该错误也会**自动重建并重试一次**，用户无需手动处理；服务器启动与插件操作会等待自愈完成，核心绝不会带着半个插件树启动。

### 2. 外壳服务并发与断连容错

- 外壳 UI 服务器改为**并发处理**（ThreadingTCPServer）：慢速桥接调用（核心版本列表、商店目录抓取）不再阻塞外壳插件清单等其他请求。
- 客户端中途断开的连接不再刷错误日志（WinError 10053 静默化）。

### 3. 外壳显示修复

- **显式 MIME 映射**：WebView2 严格 MIME 检查下，依赖系统注册表推断的 `.js/.css` 类型偶发导致外壳插件脚本与主题静默不加载，现按扩展名显式返回正确类型。
- 版本信息页「当前核心版本」显示真实版本号（不再显示提交哈希）。

### 4. 安全加固

- **桥方法白名单**：内部方法（`_` 开头）不再可经 HTTP 调用。
- **桥调用仅 POST**：GET 桥派发移除，恶意网页无法用 `<img>`/表单标签跨站触发无参动作。
- **DNS rebinding 防护**：Host 头必须是 127.0.0.1 / localhost / ::1，否则拒绝。
- 请求体上限 2 MB；插件文件解析与 zip 导入（含核心源码 zip）增加目录穿越防护。

### 5. 兼容性与生态

- 旧配置的内置商店源自动指向随应用分发的 **dshmarket 1.33.0**（历史乱码标签自动修正）。
- `dsh-doctor` 插件状态目录经 `DSH_DOCTOR_HOME` 重定向到实例数据目录（消除 C 盘 `~/.dsh-doctor` 残留与 rename EPERM）。
- 外壳插件自定义入口（plugin.json `entry`）正确生效；内置**外壳插件开发套件**（可视化生成骨架并打包 zip）。
- 新增回归测试 `tools/test-shell-fixes.py`（31 项：服务 / MIME / 插件入口 / 穿越防护 / 并发 / 断连 / 安全头 / store 自愈流程）。

## 二、版本变更

| 模块 | 变更 |
| --- | --- |
| 插件更新 | 新增 `app/homes.py heal_profile_store()`：store 归属检测、旧 store 内容合并、依赖重建（快照 + 忽略构建脚本 + 残留清理），每次启动后台执行；`app/plugins.py` 遇 ERR_PNPM_UNEXPECTED_STORE 自动重建重试一次；`app/main.py` 服务器启动/插件操作等待自愈完成 |
| 外壳服务 | `app/ui_server.py` 改用 ThreadingTCPServer 并发；断连读写静默；显式 MIME 映射表 |
| 安全 | 桥方法白名单 + POST-only + Host 校验 + 2MB 请求体上限；`shellplugins.resolve` 分隔符感知包含检查；插件 zip 与核心源码 zip 成员路径校验 |
| 外壳插件 | 自定义 `entry` 生效；zip 导入路径校验；plugin-dev-kit 开发套件随包 |
| 商店/生态 | `app/store.py heal_store_sources()`：内置源 spec 对齐随包 dshmarket 版本 + 乱码标签修正；`DSH_DOCTOR_HOME` 实例化 |
| UI | 核心版本号显示修复；`app/ui/app.js` 版本信息页与轮询渲染修正 |
| 构建发布 | 版本 1.0.4；`smoke-release.ps1` 商店包通配检测 + 干跑拷贝排除 `data\store`；`upload-release.ps1` 只上传当前版本资产；含中文 ps1 保持 UTF-8 BOM |
| 测试 | 新增 `tools/test-shell-fixes.py` 回归测试（31 项，可重复运行） |

## 三、安装包与升级包

| 项目 | 说明 |
| --- | --- |
| 懒人包安装/升级 | `DeepSeekHarness-1.0.4-Setup.exe` / `-Update.exe`（内置 Node + Git，推荐） |
| 极简包安装/升级 | `DeepSeekHarness-1.0.4-Minimal-Setup.exe` / `-Minimal-Update.exe`（无内置运行时） |
| 校验 | `SHA256SUMS-1.0.4.txt` / `SHA256SUMS-1.0.4-Minimal.txt` 与各包 `.sha256` 文件随 Release 发布 |
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

---

# 历史版本

# DeepSeek Harness for Windows v1.0.3 发布声明
