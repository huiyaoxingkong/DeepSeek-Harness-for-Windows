# v1.0.3 开发计划（错峰 / 成本控制）

- **需求基线**：`docs/REQUIREMENTS-v1.0.3.md`（24 项，范围已冻结）
- **策略**：错峰开发——按阶段串行推进，每阶段完成并验证后再进入下一阶段；
  成本控制——优先本地工具与单次通过编辑，避免大规模并行子代理与重复大文件读取。
- **版本基线**：`app_version` 1.0.2 → 1.0.3；README/RELEASE_NOTES 随阶段同步更新。

## 阶段排期

| 阶段 | 需求 | 内容 | 验证方式 |
| --- | --- | --- | --- |
| 1 | A1 (P0) | SFX 安装包中文文件名乱码修复 | ✅ 完成：规范辅助脚本（GBK bat + stop-core.ps1）入 `app\assets`、build 集成、smoke 断言、7z 中文名往返验证通过 |
| 2 | B1 (P1) | 核心基线升级 rc.2 → rc.8 | ✅ 完成（结论：无需升级——内置 rc.2 即上游 master HEAD 与最新 tag；改为发布前 Windows 回归验证） |
| 3 | A2 (P1) | 双包方案：懒人包（内置便携 Git+Node）/ 极简包 | ✅ 完成：detect_tools/git PATH 注入/极简降级/设置页运行环境卡片/双 Flavor 构建发布 smoke/更新器 Minimal 资产过滤；便携 Git 2.55.0.5 已入 `runtime\git`（git.exe 验证可用；bash 在沙箱内因命名管道限制无法起进程，与系统 Git Bash 行为一致，属环境限制，发布 smoke 于真实环境复验） |
| 4 | F1 (P1) | 外壳插件机制 + 「生成提示词」开发流 | ✅ 完成：shellplugins 管理器（内置+用户双根、zip 导入/启停/卸载、安全 id 校验）、ui_server /plugin/<id>/ 静态服务（路径穿越防护）、ShellPlugin JS API（registerPage/registerCard/registerAction/on/emit/callApi）、插件页管理 UI + 提示词生成（复制/创造模式开发流说明）、内置示例插件 example-status；端到端测试全过（扫描/启停/导入/卸载/坏包拒绝/HTTP 服务与越权拦截） |
| 5 | F2 (P1) | 性能优化（启动/内存/响应）+ 工作台嵌入显示与沉浸体验 | ✅ 完成：工作台全宽铺满+flex 纵向填满（去 960px 限制/双重滚动条/黑边）、沉浸切换淡入动画、启动加载指示（spinner+提示）、沉浸状态记忆（config ui_state，启动恢复，停止服务器退出沉浸）、detect_tools 结果缓存（get_state 轮询零开销）；onedir 打包确认无解压启动开销 |
| 6 | F3 (P1) | 外观系统（多组内置外观 + 插件接口）+ 桌宠插件接口 | ✅ 完成：5 组内置外观（黑/蓝青/霞光/森林/浅色）、设置页外观卡片即时切换+持久化、ShellPlugin.registerTheme 插件接口、桌宠挂载层 + registerPet/unregisterPet/getPetLayer 接口 + 示例桌宠插件 example-pet；端到端测试全过 |
| 7 | A3/A4/A5/A6/C1/C2/D1 (P1/P2) | 兼容性收尾 + 托盘 + 商店升级 | ✅ 完成：A3 源码核实 dshHomePath≡DSH_HOME；A4 记录聚合包默认禁用+外壳接管；A5 含空格/中文/括号路径 shim 实测通过；A6 迁移后 dump-config 健康检查（logs/health.json + 日志页卡片）；C1 核实 dsh-web-all 0.3.5 即最新；C2 dshmarket 升级 1.33.0（rebundle-store-tgz.py 离线重打包，结构校验过）；D1 ctypes 零依赖托盘（消息循环+命令队列实测）+ 关闭到托盘开关 |
| 8 | B2/B3/D2/D3/D4/E1/E2/E3 (P2) | 核心版本选择/镜像、自启、DPAPI、代理、日志、i18n、回滚 | ✅ 完成：B2 发布 tag 选择更新/回退（Releases API + tag zip 构建）；B3 代理/npm 镜像/GitHub 镜像三配置全链注入；D2 HKCU Run 开机自启开关；D3 DPAPI 密钥加密 + 旧明文自动迁移（往返实测）；D4 HTTP 代理注入核心/插件进程；E1 日志过滤/着色/复制/下载；E2 中英 i18n（零标记反向映射 + 语言选择持久化）；E3 升级 exe 备份/恢复回滚 |
| 9 | C3/D5/E4 (P3) + 发布 | 全家桶预设、包体优化、多实例面板；make-release + RELEASE_NOTES | ✅ 全部完成：4 个安装包 + SHA256 产物齐备（Lazy 606.5MB / Minimal 496.4MB）；双包结构验证通过（GBK bat 中文正确、GUI SFX 模块、极简无 runtime、核心启动 0.1.1-rc.2）；smoke（结构/中文名/状态排除/升级演练）PASS；源码已提交 + 标签 v1.0.3；**GitHub 上传需用户在本机执行 upload-release.ps1（沙箱无法使用 git 凭据）** |

## 成本控制约定

- 每阶段单独确认入口条件（依赖数据/网络是否可用），不可用先做同阶段可本地完成的部分；
- 涉及网络下载（上游核心、便携 Git/Node）先探测通道，失败立即改用缓存/降级方案并记录；
- 不做大范围并行子代理；优先单文件定向编辑；复读大文件用 offset/limit；
- 每完成一个阶段更新本文件「状态」并汇报一次。

## 系统测试与修复轮（2026-08-29）

真实运行 dist 开发实例 + HTTP 桥驱动测试，发现并修复 9 个缺陷：

| # | 缺陷 | 修复 |
| --- | --- | --- |
| 1 | 安装目录含空格时，传给 dsh/pnpm 的本地包路径被按空格拆分（默认安装路径必踩） | `homes.cli_path()`：无空格 junction（%TEMP%\dsh-j<哈希> → 应用目录）映射；实测预装 2.2s 成功 |
| 2 | Windows 11 移除 wmic → 实例面板/孤儿进程清理静默失效 | 改用 PowerShell Get-CimInstance（实测列出生产+开发实例） |
| 3 | pnpm 大包下载超时导致插件安装失败 | 插件/核心子进程注入放宽的 fetch timeout/retries |
| 4 | 语言切换失效（applyI18n 用目标语言映射查当前 DOM 文本） | 改用「当前显示语言」映射 + prevLang 追踪 |
| 5 | 迁移复制旧 node_modules（旧 store 硬链接）→ ERR_PNPM_UNEXPECTED_STORE | 迁移排除 node_modules + 迁移后自动 pnpm install |
| 6 | 全新 profile 首次安装缺 allowBuilds → ERR_PNPM_IGNORED_BUILDS | ensure_profile_workspace 预创建目录+模板 |
| 7 | write-core-info 记录实时 master 而非实际源码 → 版本误报 | 优先级：显式参数 → .upstream-commit → git HEAD → API 兜底 |
| 8 | 插件 worker 因孙进程持有 stdout 管道永不结束 → 页面永久「安装中」 | 收集线程 + proc.wait 超时，从进程退出定状态 |
| 9 | 8.3 短名被禁用时无空格路径方案失效 | 并入 #1 的 junction 方案 |

验证：核心启动/停止、dsh Web 200、健康检查 ok、主题/语言持久化、
实例面板、托盘轮询、自启注册表、tag zip 可达、**全家桶免 SSH 预设 20 插件
真实安装成功并带载启动**（聚合包在无编译工具机器上会因 cpu-features 失败，
已提供免编译预设并记录）。

## 工程约定（本轮新增）

- **含中文的 .ps1 必须 UTF-8 BOM**：无 BOM 时 PowerShell 按 ANSI 读脚本导致中文乱码
  （v1.0.2 SFX 标题即为乱码；本次已统一补 BOM）。注意：用编辑工具改这类文件后需
  重新补 BOM（编辑工具会去掉 BOM）。
- **双包资产命名**：懒人包保持 `DeepSeekHarness-<ver>[-Setup|Update].exe`（旧名不变，
  应用内更新兼容）；极简包加 `-Minimal-` 中缀；更新器（Lazy 默认路径）过滤
  `-Minimal-` 资产；极简包升级走 Releases 手动下载。

## F1 设计草案（下一波细化）

- **壳内插件**：`ui/plugins/<id>/plugin.json`（id/name/version/slots/entry）+ `main.js`；
  外壳加载器注册页面/卡片/按钮，`window.ShellPlugin` API（registerPage / registerCard /
  onEvent / callApi 透传桥）；配置 `config.json → shell_plugins: {enabled:[...]}`。
- **安装/管理**：本地 zip 导入（解压至 data 内插件目录）+ 启用/停用/卸载；插件页新增
  「外壳插件」区块（与核心插件列表并列）。
- **生成提示词**：插件页「生成插件提示词」表单（描述插件想法）→ 产出结构化开发提示词
  （含 ShellPlugin API 说明与约束）→ 一键复制 / 打开 dsh Web 新对话；
  对接 F1.3「插件开发插件（创造模式）」：提示词引导 agent 在同工作区新对话中开发
  壳内插件或壳内外联动插件；示例落地由 F3 外观插件充当。
