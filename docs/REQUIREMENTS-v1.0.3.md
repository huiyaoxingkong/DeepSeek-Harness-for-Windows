# DeepSeek Harness for Windows v1.0.3 需求收集

- **收集日期**：2026-08-27
- **当前版本**：v1.0.2（tag `v1.0.2`，发布 2026-08-27）
- **内置核心基线**：`@deepseek-ai/dsh-root@0.1.1-rc.2`（上游 commit `b150a551b8d4`，2026-08-21）
- **内置商店**：dshmarket 1.21.4；**兼容对象**：dsh-web 家族 `@linxin666/dsh-*`（检出版 0.3.5）
- **说明**：本文档汇总多方来源的候选需求，按来源分组、按优先级排序（P0 必须 / P1 应做 / P2 建议 / P3 可选）。
- **范围决策（2026-08-27 已确认）**：全部 A–F 纳入 1.0.3；核心基线升级到 rc.8 并回归验证；
  A2 调整为**双包方案**（懒人包内置 Git+Node / 极简包由用户自装，见 A2）；F 组自有需求
  （外壳插件化 / 性能与工作台体验 / 外观系统与桌宠接口）已并入。

---

## A. 项目自身已知限制与遗留问题（本地仓库证据）

### A1 [P0] SFX 安装包中文文件名乱码修复
- **现象**：`.tmp-sfx-test/install-copy` 中出现乱码重复文件
  `鍋滄 DeepSeek Harness.bat`（=「停止」）、`鍚姩 DeepSeek Harness.bat`（=「启动」），
  是 UTF-8 文件名被按 GBK 解码所致；正确的「启动/停止 DeepSeek Harness.bat」同目录并存。
- **影响**：用户安装/升级后目录里出现乱码重复脚本，观感差且可能被误执行。
- **方向**：修复 7-Zip SFX 打包/解压链路的中文文件名编码（如 SFX 参数 `-mcu=on` /
  编码统一），并在发布 smoke 中校验解压后文件名无乱码、无重复。

### A2 [P1] 双包方案：懒人包（内置 Git + Node）/ 极简包（用户自装）【开发中→代码完成】
- **依据**：README「已知限制」与 RELEASE_NOTES 明确：`git`、`bash`（dsh-liangshen 的
  bash 工具）需系统安装，未安装时 `dsh-git-graph`、`dsh-liangshen`、插件 git 源安装不可用。
- **方向（2026-08-27 决策）**：不再把所有能力塞进单一安装包，改为发布两个变体：
  - **懒人包**（推荐）：随应用内置便携版 Git for Windows（git.exe + Git Bash）与
    便携 Node.js，开箱即用；`git.exe`、`bash.exe` 注入核心进程 PATH。
  - **极简包**：不含 Git / Node，依赖用户自装系统 git / bash；应用启动时检测
    git / bash 可用性，在设置页显示状态与安装指引，缺省适配「极简模式」
    （相关插件功能优雅降级，不报错崩）。
- **实现记录（2026-08-27）**：
  - `homes.detect_tools()`（node/git/bash 内置/系统/缺失 + 包风味）与
    `homes.git_path_entries()`（git/cmd、bin、usr/bin、mingw64/bin 注入 PATH）；
    bash 检测优先取 git 同源 Git Bash，避开 WSL 存根；
  - `core_api`/`plugins`：node 缺失回退系统 node；极简包 COREPACK_HOME 落到实例
    data 内；启动/插件操作 PATH 注入内置 Git；缺 Node 时给出明确指引而非「核心未构建」；
  - `scripts/download-portable-git.py`（GitHub Releases PortableGit → 7z 解压 →
    `runtime\git`，规范化布局）；`build-core.ps1` 支持系统 node/pnpm 回退 + 内置 git PATH；
  - `build.ps1 -Flavor Lazy|Minimal`（懒人默认；极简跳过运行时拷贝）；
    `make-release.ps1/smoke-release.ps1 -Flavor`（极简包名 `-Minimal-` 中缀，
    懒人包保持旧名兼容应用内更新）；`updater.py` 默认更新路径过滤 `-Minimal-` 资产；
  - 设置页新增「运行环境」卡片（风味 + node/git/bash 状态标签 + 降级说明）。
- **收益**：懒人包用户 dsh-web 生态三大依赖（git 图形 / bash 工具 / git 源安装）
  开箱可用；极简包保持小体积、依赖自管。

### A3 [P1] dsh-perf 核心补丁行与 DSH_HOME 一致性验证【已核实：一致】
- **依据**：dsh-web 兼容性报告 P2.8——`dsh-perf` 带 bare id 补丁行覆盖核心
  `session-persistence-jsonl` 的 `root: !!js dshHomePath('sessions')`；若 `dshHomePath`
  与 `DSH_HOME` 解析不一致，会话存储会错位。
- **核实结论（2026-08-27，core 源码验证）**：`app-boot/src/index.ts` 在启动时
  `ctx.provide('dshHomePath', dshHomePath)`；`@deepseek-ai/dsh-home-paths` 的解析
  优先级为 显式配置 > `$DSH_HOME` > `~/.dsh`。外壳 spawn 核心时统一注入
  `DSH_HOME=<app>\data\.dsh`，因此 `dshHomePath('sessions')` 天然解析到实例
  `data\.dsh\sessions`——**一致，无需补偿**；发布 smoke 会实际校验该目录落位。
- **方向**：验证内置核心的 `dshHomePath` 与外壳注入的 `DSH_HOME` 一致；不一致时在
  外壳层做补偿（如同时注入核心期望的环境变量），并纳入 smoke。

### A4 [P1] dsh-desktop-launcher 插件冲突治理【已记录】
- **依据**：兼容性报告第三/四部分——该插件与外壳功能重叠（双桌面图标、双 dsh 进程、
  双关机入口）。
- **治理（2026-08-27）**：dsh-web 聚合包中该插件默认 `enabled: false`（上游行为，
  无需代码干预）；外壳接管「创建桌面图标」语义（`app\assets\创建桌面快捷方式.ps1`
  随包分发，托盘/外壳启动入口完备）；README/发布说明明示「不建议启用该插件，若启用
  需将其 dshCommand 指向外壳内置 dsh」。

### A5 [P2] doctor / plugin-manager 的 dsh.cmd shim 转义复测【已测通过】
- **依据**：报告 P2.11——Windows 经 `cmd.exe` 执行 `.cmd` shim，路径含元字符会被
  「unsafe Windows command argument」拦截。
- **实测（2026-08-27）**：在含**空格 + 中文 + 括号**的目录中放置 dsh.cmd（`%~dp0`
  自引用 node.exe），`dsh --version` 输出 `0.1.1-rc.2`（退出码 0），`--help` 正常——
  引号转义正确，无 unsafe argument 拦截；内置 shim 生成逻辑（`ensure_dsh_shim`）一致。

### A6 [P2] 迁移/升级后自动验证（smoke 强化）【已实现】
- **依据**：报告 P3.12。
- **实现（2026-08-27）**：`homes.run_health_check()`——启动后台线程，存在 web profile
  时执行 `dsh --profile web --dump-config`（已验证该命令可用，退出码 0），结果写入
  `logs\health.json` 并记入 launcher.log；`get_state` 暴露 `health` 摘要，日志页新增
  「迁移/升级健康检查」卡片显示 ✅/⚠️ 与失败尾部。

---

## B. 上游核心版本升级

### B1 [P1] 核心基线升级到最新上游【核实更新（2026-08-29）】
- **核实结论（2026-08-27，git ls-remote + blobless clone 验证）**：
  - 上游 tag 时间线：`dsh-v0.1.0-rc.7`（08-17）→ `dsh-v0.1.0-rc.8`（08-19）→
    `dsh-v0.1.1-rc.1`（08-21 14:21）→ `dsh-v0.1.1-rc.2`（08-21 20:03）；
  - 当时 master HEAD = 内置基线 `b150a551b8d4`（rc.2），新闻中的「rc.8 多模态」属更早的 0.1.0 线。
- **更新（2026-08-29）**：上游 master 已前进至 `cd5ef8148`（`dsh-0.1.2-alpha.1`）。
  内置基线**保持 rc.2（稳定版）**；alpha 版本由用户经「核心更新 → 选择版本更新 /
  跟随 master」主动升级。修复构建期元数据缺陷：`write-core-info.py` 原先记录实时
  master 提交，会把 rc.2 源码误标成 alpha.1（更新检查误报「已是最新」）；现改为
  显式参数 → `core\.upstream-commit` 标记 → 本地 git HEAD → API 兜底。
- **回归项（升级前必须验证）**：
  - rc.7 起 node-pty 在 Windows 的持久 PTY shell 问题（pid 0，
    [Discussion #2851](https://github.com/deepseek-ai/deepseek-harness/discussions/2851)）；
  - Windows 下 spawn 的 bash 子进程崩溃导致 ENOENT 未捕获
    （[Discussion #2990](https://github.com/deepseek-ai/deepseek-harness/discussions/2990)）；
  - 极简模式 Shell 工具 / str_replace_editor 沙箱边界
    （[Discussion #2066](https://github.com/deepseek-ai/deepseek-harness/discussions/2066)）。
- **方向**：升级后在 Windows 上跑一轮核心功能 smoke；若 rc.8 有阻断性回归，可退而选择
  较稳的 rc 版本并记录理由。

### B2 [P2] 核心更新页支持选择版本 / 标签【已实现】
- **实现（2026-08-27）**：`updater.list_core_releases()`（GitHub Releases API，30 分钟缓存）；
  桥新增 `list_core_releases` / `update_core({tag})`；更新页新增「选择版本更新（升级 /
  回退）」卡片——下拉选择 tag（含名称与日期），`download_and_build(tag)` 从
  `archive/refs/tags/<tag>.zip` 构建并原子切换（失败自动回退机制复用）；留空 = 跟随 master。

### B3 [P2] 核心更新 / 依赖安装支持自定义源与镜像【已实现】
- **实现（2026-08-27）**：设置页新增「网络与镜像」卡片：`proxy_url`（HTTP 代理）/
  `npm_registry`（pnpm 镜像，经 `npm_config_registry` 注入核心、插件安装与核心构建）/
  `github_mirror`（GitHub 文件/资产 URL 前缀改写：核心源码 zip、应用升级包资产）。
  代理同样注入核心子进程环境（HTTP(S)_PROXY）。

---

## C. 插件生态版本与兼容性

### C1 [P1] dsh-web 家族最新版兼容性复测【已核实：0.3.5 即最新】
- **核实（2026-08-27，npm registry）**：`@linxin666/dsh-web-all` latest = **0.3.5**
  （2026-08-26），与兼容性报告分析的版本一致——内置适配基线即最新，无需改预置；
  全量安装复测纳入发布 smoke。
- **方向**：以最新家族版跑一次全量安装 smoke，输出兼容性结论，必要时更新
  `pnpm-workspace.yaml` 预置。

### C2 [P2] 内置 dshmarket 商店升级【已升级 1.21.4 → 1.33.0】
- **实施（2026-08-27）**：npm 最新 1.33.0；源码构建因沙箱网络慢失败，改为
  **重新打包官方发布 tgz**：新增 `scripts/rebundle-store-tgz.py`（下载官方
  dshmarket-1.33.0.tgz + 解析依赖闭包 js-yaml@4.1.0/argparse@2.0.1/undici@7.29.0
  + 内嵌 node_modules + 写 bundleDependencies，产物 1.3MB、结构校验通过，
  离线预装能力保持）；`app/store/dshmarket-1.33.0.tgz` 已替换 1.21.4；
  `build.ps1`（商店步骤改用 rebundle 脚本 + spec）、`settings.py`、`app/config.json`、
  `smoke-release.ps1` 全部切到 1.33.0。
- **方向**：检查 dshmarket 上游新版本，升级内置包并回归「启用商店 → 重启 → 插件市场」链路。

### C3 [P3] 「一键安装 dsh-web 全家桶」预设【已实现】
- 插件页「安装插件」卡片新增常用预设按钮：一键填入 `@linxin666/dsh-web-all`
  （19 插件聚合包），点击安装即装全家桶；与 A3/A4 的补丁行/冲突治理联动记录不变。

---

## D. 桌面体验增强（对标同类封装）

> 来源：同类 Windows 封装（Easyhoov/deepseek-harness-desktop-windows、
> hairyf/deepseek-harness-desktop、csyyywy/dsh-desktop、huyang218/dsh-desktop 等）
> 的常见能力，本仓库当前均未实现（grep 确认无托盘/自启代码）。

### D1 [P1] 系统托盘与关闭行为【已实现】
- **实现（2026-08-27）**：
  - `app/tray.py`：零依赖 ctypes Shell_NotifyIcon 托盘（隐藏消息窗口 + 弹出菜单：
    打开主界面 / 启动服务器 / 停止服务器 / 退出；左键点击 = 打开主界面）；
  - 命令经线程安全队列 → 外壳 UI 800ms 轮询 `poll_tray` → 桥线程执行窗口操作
    （避免跨线程直接操作 pywebview）；消息循环、WM_COMMAND 分发、DefWindowProcW
    64 位 LPARAM 签名已实测；
  - 关闭行为：设置页新增「关闭窗口时最小化到系统托盘（后台运行）」开关
    （config `close_to_tray`，默认关保持原行为）；`window.events.closing` 拦截
    → hide() 隐藏到托盘；托盘「退出」走 quit_app（停核心 → 销毁窗口 → 停托盘）；
  - 图标随包分发（`dsh.ico` 复制进 dist），无 PIL/pystray 依赖、无 PyInstaller
    隐藏导入负担。

### D2 [P2] 开机自启【已实现】
- 设置页新增「开机自动启动 DeepSeek Harness」开关；`set_auto_launch` 写
  HKCU Run 注册表项（值 = 应用 exe 带引号路径），`get_state` 回读当前状态，
  修改即时生效（无需点保存）。

### D3 [P2] API Key 加密存储【已实现】
- 新增 `app/crypto.py`：Windows DPAPI（CryptProtectData/CryptUnprotectData +
  熵字符串）；config.json 以 `dpapi:` 前缀密文保存，仅同机同用户可解；
  启动时自动把旧明文密钥一次性迁移为密文；`get_api_key`/`get_state`/核心环境注入
  全部经解密路径（解密失败降级为空并记日志）。

### D4 [P2] HTTP 代理设置【已实现】
- 设置页「HTTP 代理」输入；`homes.proxy_env` 把 HTTP(S)_PROXY 注入核心子进程与
  插件安装进程；（updater 下载流量的代理经同环境变量由 urllib 默认读取）。

### D5 [P3] 安装包体积优化【已实施（发布时生效）】
- 实施：7z 压缩级别 7 → **9**（make-release 默认）；构建后新增「发布核心可启动」
  校验（build.ps1 对 dist 跑 `--version`，防回归）。曾尝试 `pnpm prune --prod`
  剪枝，实测会破坏 monorepo 工作区包解析（内部 @deepseek-ai/* 包被剪），**已回退**；
  实际体积以 Release 产物为准（1.0.3 懒人包 476.6 MB，较 1.0.2 的 494 MB 因 mx9 仍略降，
  且新增了内置 Git）。

---

## E. 运维与质量

### E1 [P2] 日志页增强【已实现】
- 日志页新增：关键词过滤输入（实时）、错误/警告行着色（红/黄）、一键复制、
  下载 core.log 文件；渲染改为逐行 div（支持着色）。

### E2 [P2] 多语言外壳 UI（中 / 英）【已实现（主界面范围）】
- 新增 `app/ui/i18n.js`：中/英词典 + 零标记反向映射（按中文原文匹配静态文本节点、
  placeholder 与 title 自动替换）；`window.t(key)` 供动态字符串使用；
  设置页「外观」卡片新增语言选择（中/英），切换即时生效并持久化
  （`ui_state.lang`）；已覆盖：导航 / 页面标题 / 关键按钮 / 设置卡片与标签 /
  状态栏 / 运行环境 / 启动提示；深层提示文案随后续版本逐步补充。

### E3 [P2] 应用升级回滚验证【已实现】
- 升级引导脚本（upgrade.bat）增强：覆盖安装前备份 `DeepSeek Harness.exe.bak`；
  若升级包后置脚本未完成且自愈后 exe 缺失，自动从备份恢复；成功后清理备份文件。

### E4 [P3] 多实例管理面板【已实现】
- 设置页新增「本机实例」卡片：枚举本机运行中的 DeepSeek Harness 进程
  （wmic 进程扫描 + netstat 端口映射），标注「本实例」与监听端口——
  同机多实例（数据/端口隔离）一目了然。

---

## F. 自有需求（用户提供，2026-08-27）

### F1 [P1] 外壳插件化 + 提示词生成开发流（创造模式）【已澄清】【已实现】
- **用户原文**：「外壳也参考核心的插件模式，生成提示词，在另一个同工作区新对话中使用
  创造模式开发外壳插件开发的核心插件。」
- **澄清后理解（2026-08-27）**：
  1. **外壳插件化**：外壳引入插件机制，参考核心的插件模式——壳内插件可挂载页面 /
     按钮 / 功能，支持安装 / 启用 / 停用 / 卸载（现有 `app/ui/` 纯文件定制保留兼容）；
  2. **提示词生成开发流**：外壳内置「生成提示词」能力——按用户对插件的描述生成
     结构化开发提示词，供在**同一工作区的另一个新对话**中以**创造模式**（agent 开发）
     完成插件开发；
  3. **首个开发目标：插件开发插件**：开发一个**壳内插件**（内含新模式，即创造模式），
     它专门用于开发 **壳内插件** 与 **壳内外联动插件**（同时作用于外壳与 dsh 核心）；
     该插件开发插件本身也通过「生成提示词 → 新对话创造模式」产出；
  4. 「壳内外联动」方向：外壳插件与 dsh 核心插件之间的联动机制（桥接/能力互调，
     具体接口在开发计划阶段细化）。
- **实现记录（2026-08-27）**：
  - `app/shellplugins.py`：内置根（`ui/plugins`）/ 用户根（`data/shell-plugins`）双根
    扫描、zip 导入（实例内暂存，不写系统 temp）、启用/停用（`config.json shell_plugins`）、
    卸载（内置不可卸载）、id 白名单校验；
  - `ui_server.py`：`/plugin/<id>/<文件>` 静态服务（用户根覆盖内置根；路径穿越与
    非法 id 拦截，已测）；
  - `app.js`：`window.ShellPlugin` API（registerPage/registerCard/registerAction/
    on/emit/callApi/log）+ 启动注入已启用插件脚本 + 插件页管理 UI；
  - 「生成插件提示词」表单：按想法生成结构化开发提示词（含 ShellPlugin API 规范、
    约束与交付格式），一键复制，指引到工作台新对话用创造模式开发；导入 zip 安装；
  - 内置示例插件 `example-status`（「关于」页运行状态卡片）。
- **验收方向**：壳内可安装/管理插件；「生成提示词」可生成并带入新对话开发；
  「插件开发插件」可用创造模式产出新的外壳插件与联动插件（F1.3 后续波次，
  配合 F3 外观插件作为首个真实插件落地）。

### F2 [P1] 外壳性能优化 + 工作台嵌入显示/沉浸体验【已澄清，三点全做】【已实现】
- **用户原文**：「优化外壳性能，和工作台未全屏外壳全屏下的使用体验。」
- **确认的痛点（2026-08-27，全部纳入）**：
  1. **工作台嵌入显示与布局适配**：普通布局下 iframe 嵌入区铺满剩余视口，消除双重
     滚动条 / 黑边 / 缩放不适；沉浸切换更顺滑；
  2. **性能**：启动速度（PyInstaller onefile 解压）、运行内存、界面与 iframe 渲染响应；
  3. **沉浸状态记忆与切换体验**：记住上次沉浸状态、退出全屏回到原位、入口更顺手。
- **实现记录（2026-08-27）**：
  1. 布局：`#page-workspace` 全宽（去掉 960px 限制）+ flex 纵向填满剩余视口，
     frame-wrap 高度自适应（消除窗口全屏时 iframe 两侧留白、双重滚动条与黑边）；
  2. 性能：打包确认为 onedir（无 onefile 解压启动开销）；`detect_tools` 结果按
     app_dir 缓存（get_state 轮询不再重复探测）；启动服务器时显示 spinner + 时长提示
     （感知性能）；沉浸切换不再重载 iframe；
  3. 沉浸体验：进入/退出沉浸带淡入动画；状态持久化（config.json → ui_state.immersive），
     启动时恢复上次状态（非沉浸时回到工作台普通布局）；停止服务器自动退出沉浸；
     退出全屏回到工作台原位。
- **现状**：工作台页用 `iframe#dsh-frame` 嵌入 dsh Web；「全屏」按钮进入沉浸模式
  （隐藏外壳 chrome），「退出全屏」返回普通布局。

### F3 [P1] 外壳外观系统（多组内置外观 + 插件扩展）+ 桌宠插件接口【已确认】【已实现】
- **用户原文**：「外壳新增外观系统（做几组不同的外观），保留插件接口，外壳插件系统中
  保留桌宠插件接口。」
- **理解**：
  1. **外观系统**：外壳新增外观（皮肤/主题）系统，内置**多组不同外观**（做几组成品
     外观，覆盖配色 / 布局风格差异），设置页可一键切换、即时生效、持久记忆；
  2. **保留插件接口**：外观系统以插件接口形态实现——外观本身可作为壳内插件注册
     （新外观 = 新增插件/主题包），与 F1 外壳插件系统打通，而非写死内置几套；
  3. **桌宠插件接口**：外壳插件系统中**预留桌宠插件接口**——允许壳内插件实现桌面
     宠物（浮动挂件 / Live2D 等，参照核心 dsh-pet 概念），包括宠物的挂载区域、
     交互与生命周期管理；接口先预留并给出示例实现，不要求 1.0.3 做完整桌宠。
- **实现记录（2026-08-27）**：
  1. 内置 5 组外观：深邃黑（默认基线）/ 深海蓝青 / 暖橙霞光 / 森林绿 / 浅色
     （`app/ui/themes/*.css`，覆盖 CSS 变量 + 布局微调，浅色含组件级适配）；
  2. 设置页「外观」卡片：色块预览 chip，点击**即时切换**（注入 style#shell-theme，
     免重载）并持久化（`config.json → ui_state.theme`，启动恢复）；
  3. **插件接口**：`ShellPlugin.registerTheme({id,name,css})`（支持 URL 或 CSS 文本）
     ——新外观 = 插件提供，列表标注「插件外观」；
  4. **桌宠插件接口（预留）**：全窗口透明挂载层 `#shell-pet-layer`
     （pointer-events:none、顶层、沉浸模式仍可见）；`ShellPlugin.registerPet({id,x,y,
     html,draggable,onMount})` / `unregisterPet(id)` / `getPetLayer()`；
     内置示例插件 `example-pet`（可拖拽浮动小球，点击变色）。
- **现状（改造前）**：外壳仅靠 `ui/style.css` 顶部 `:root` CSS 变量换肤（手动改文件），
  无外观切换界面、无插件化外观、无桌宠能力。
- **与 F1 关系**：F1 的壳内插件机制是 F3 的地基（外观与桌宠都是壳内插件的典型类型）；
  开发顺序上先落地 F1 插件机制，再做 F3。

---

## 优先级汇总

| 优先级 | 编号 | 主题 |
| --- | --- | --- |
| P0 | A1 | SFX 中文文件名乱码修复 |
| P1 | A2 | 内置便携 Git（git + bash） |
| P1 | A3 | dsh-perf 补丁行与 DSH_HOME 一致性验证 |
| P1 | A4 | dsh-desktop-launcher 冲突治理 |
| P1 | B1 | 核心基线升级（rc.2 → rc.8，含 Windows 回归验证） |
| P1 | C1 | dsh-web 家族最新版兼容复测 |
| P1 | D1 | 系统托盘与关闭行为 |
| P1 | F1 | 外壳插件化（参考核心插件模式 + 提示词生成开发流） |
| P1 | F2 | 外壳性能优化 + 工作台非全屏/全屏体验 |
| P1 | F3 | 外壳外观系统（多组内置外观 + 插件接口）+ 桌宠插件接口 |
| P2 | A5 | doctor/plugin-manager shim 转义复测 |
| P2 | A6 | 迁移/升级后自动验证 smoke |
| P2 | B2 | 核心更新支持选择版本/tag |
| P2 | B3 | npm 镜像 / GitHub 镜像配置 |
| P2 | C2 | dshmarket 商店升级 |
| P2 | D2 | 开机自启 |
| P2 | D3 | API Key DPAPI 加密 |
| P2 | D4 | HTTP 代理设置 |
| P2 | E1 | 日志页增强 |
| P2 | E2 | 多语言外壳 UI |
| P2 | E3 | 应用升级回滚验证 |
| P3 | C3 | dsh-web 全家桶一键安装预设 |
| P3 | D5 | 安装包体积优化 |
| P3 | E4 | 多实例管理面板 |

---

## 范围决策（2026-08-27）

| 决策项 | 结论 |
| --- | --- |
| 需求范围 | 全部 A–E 纳入 1.0.3 |
| A2 Git/Node | 双包方案：懒人包（内置便携 Git + Node）/ 极简包（用户自装，应用检测并优雅降级） |
| B1 核心基线 | 升级到 rc.8 并回归验证；阻断性回归则退选较稳 rc 版本 |
| 自有需求 | 已并入 F 组（F1 外壳插件化+创造模式开发流、F2 性能/嵌入显示/沉浸体验、F3 外观系统+桌宠接口），均已澄清 |
| 发布节奏 | 不设硬性日期，尽快；按 P0/P1 → P2 → P3 顺序推进 |
| 状态 | **范围已冻结**（24 项）；等待用户发出开发指令即开工 |

---

## 参考来源

- 本仓库：`README.md`、`RELEASE_NOTES.md`（已知限制）、`.tmp-dsh-web-report.md`（dsh-web
  兼容性报告 P0–P3 建议）、`.tmp-sfx-test/`（SFX 测试产物，乱码证据）
- 上游核心：https://github.com/deepseek-ai/deepseek-harness （releases / discussions
  #2851 #2990 #2066）
- dsh-web 生态：https://github.com/zhu1090093659/dsh-web 、
  https://github.com/zhu1090093659/dsh-web-ui
- dsh-market：https://github.com/dsh-market/dsh-market
- 同类封装（对标）：https://github.com/Easyhoov/deepseek-harness-desktop-windows 、
  https://github.com/hairyf/deepseek-harness-desktop 、
  https://github.com/csyyywy/dsh-desktop 、
  https://github.com/huyang218/dsh-desktop
- Windows 侧上游问题参考：https://github.com/Jyleaves/dsh-win-bash-fix （Git Bash 修复示例）
