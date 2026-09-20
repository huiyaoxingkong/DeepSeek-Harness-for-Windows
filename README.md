# DeepSeek Harness Desktop

将 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）
封装为 Windows 桌面应用：

- **exe 启动器**（`DeepSeek Harness.exe`）：WebView2 窗口 + 本地 Web UI（工作台 / 插件 / 设置 / 核心更新 / 日志）
- **新手引导**：首次启动分步引导（工作台 / API Key / 插件与更新）
- **核心可更新**：一键从 GitHub 官方源码（master 分支）下载 → `pnpm install` → `pnpm build` → 原子切换，失败自动回退
- **核心可本地导入**：选择本地源码压缩包（.zip）构建并切换核心，无需网络 / 代理
- **插件管理**：安装 / 卸载 / 启用 / 停用插件（npm 包、git 仓库、本地路径）
- **插件可本地导入**：选择本地插件包（.tgz / .tar.gz / .zip）直接安装，无需代理
- **插件商店**：内置 dsh-market 插件商店（初始关闭，可一键启用），支持添加 / 移除自定义商店源
- **独立可换肤 UI**：外壳界面是纯 HTML/CSS/JS，直接编辑文件即可自定义
- **内置 Node.js 运行时**：无需在系统安装 Node.js
- **数据随软件走**：插件、会话、设置、皮肤全部保存在安装目录 `data\` 内，不占用 C 盘；每个安装目录是独立实例
- **dsh-web 插件生态兼容**：内置 dsh CLI/pnpm 暴露、profile 工作区自动预置，`@linxin666/dsh-*` 全家族插件开箱可用
- **应用在线升级**：「关于」页一键下载升级包（SHA256 校验）并静默覆盖升级（保留数据与自定义界面），自动重启

## 版本 1.0.5

修复（均带回归测试）：

### 一、1.0.3 起「看起来有、实际没生效」的功能

- **外观（主题）系统彻底修好**：内置外观用的是相对路径（`themes/ocean.css`），而
  `applyTheme` 只对 `http(s)://`、`//`、`/` 开头的值发起请求，于是把**路径字符串本身**
  当成 CSS 注入 —— 点任何外观都毫无变化。现在按“是否含规则块”判断是 CSS 文本还是样式表
  地址，加载失败时移除旧外观而不是停留在上一个外观。（实测：点击「浅色」后注入 1361 字符
  的真实 CSS，背景 `rgb(14,17,22)` → `rgb(244,246,250)`。）
- **界面语言切换（中/英）修好**：`applyI18n` 用文本节点的**整串**精确匹配字典键，而导航
  等文本节点带缩进换行（`<span>◇</span>插件\n        `），永远匹配不上「插件」，
  于是切换语言毫无反应。现在按去空白后的文本查表并保留原空白。
- **「添加商店源」修好**：`#store-catalog` 同时是目录列表 `<div>` 与目录地址 `<input>`
  （HTML 重复 id），`getElementById` 取到 div、`.value` 为 `undefined`，点击即抛
  `TypeError`、永远发不出 `store_add`。输入框改用 `store-catalog-url`。
- **核心更新可取消**：`cancel_update` 与 `CoreUpdater.cancel()` 早已实现，但界面上没有任何
  入口（长更新无法中止）。更新页进度卡片现在提供「取消更新」按钮，仅在更新进行中显示。

### 二、随包内容与体验

- **示例外壳插件不再随任何安装包分发**：`example-status`、`example-pet`、`plugin-dev-kit`
  移到仓库 `examples/shell-plugins/`（附 README 说明如何导入试用），`app/ui/plugins/`
  不再随包，安装后「外壳插件」列表为空。
- **卸载插件先校验**：`remove_plugin` 之前对任何名字都回「操作已开始」，再异步失败；
  现在与「停用」一致，先校验是否为已安装依赖并给出明确提示。
- **旧版 dsh-web 聚合插件自动清理**：作者已把 `@linxin666/dsh-web-ui-all` 标记为废弃
  （npm 弃用提示「迁移到 `@linxin666/dsh-web-all`」，包内 `dsh.migrate.to` 指向它），
  最后一个版本 0.3.6（2026-08-27）与当前家族 0.3.23（2026-09-16）差距明显，与随包的
  0.1.6 内核组合使用时 Web UI 出现异常（用户实测）。升级到 1.0.5 时启动器会**先清理
  profile 清单**（`dependencies` + `dsh.profile.bundles`，离线也生效），再用 pnpm 把
  `node_modules` 与清单对齐（多余旧包被删除、随包商店包装入）；`post-update.bat` 在升级时
  还会用随包 dsh CLI 先卸载一次（那时清单未改，命令有效）。
  同时下线 `dsh-chat-recovery` / `dsh-desktop-launcher` / `dsh-perf` /
  `dsh-client-ui-aionui-panel` 四个已退出家族列表的包。预设与一键安装按钮已对齐作者的
  当前包集合（各包 0.3.23，声明 `dsh >= 0.1.5-rc.1`），**清理不会自动安装替代包**。
- **内置商店插件升级**：随包 `dshmarket` 由 1.33.0 升到 **1.50.0**（peer 兼容
  `^0.1.2-alpha.2`，可在 0.1.6 内核上加载）；旧安装的商店源配置会在启动时自动指向新包。

### 三、缺陷修复

- **启动服务器期间切换页签不再「异常放大」/卡死**：启动服务器可能要 1–3 分钟（首次构建核心
  更久），期间若点击左侧页签（设置 / 插件…），服务器就绪时仍会强制进入沉浸全屏 ——
  侧边栏被隐藏、「退出全屏」按钮又随被隐藏的工作台页一起消失，当前页被撑成满屏
  （padding 归零、不可滚动、页头隐藏），用户既看不到导航也没有返回入口。现在：
  只有仍停留在工作台页时才自动全屏；离开工作台页会自动退出全屏，侧边栏与页头恢复。
  （实测：修复前 body=`immersive`、侧边栏 `display:none`、content padding `0px`、
  `overflow:hidden`、无页头；修复后 `immersive` 未生效、侧边栏 `flex`、
  padding `22px 26px`、可正常滚动，且停留在用户点击的页签上。）
- **彻底修复「工作台退出全屏后页面只显示一条边」**：iframe 用 `height: 100%` 填充
  一个由 flex 决定高度的容器时，浏览器按 `auto` 处理并回落到 iframe 默认的 **150px**
  高度——所以一退出全屏（或任何非全屏状态）工作台就只剩一条窄边。现在 iframe 与空状态
  都用绝对定位铺满容器，与父级高度是否“确定”无关；同时去掉沉浸模式下 `position: static`
  造成的定位包含块外溢，并修正非全屏时的双滚动条。
- **修复核心升级 / 降级无法完成（`core.backup` 卡死）**：pnpm 目录树普遍超过 Windows
  `MAX_PATH`（260 字符），`shutil.rmtree` 与 `cmd rmdir` 都会以 WinError 3 失败，于是
  上一次失败更新留下的 `core.backup` 永远删不掉，此后**每一次**核心更新都报
  “无法切换核心目录（文件被占用）”。现在统一走 `\\?\` 扩展长度路径删除，兼容只读文件
  （git pack）且绝不跟随 junction；换核前校验待安装核心、换核后校验可启动入口，失败自动
  回滚；无法删除的陈旧备份不再阻塞更新，下次启动继续清理。
- **非英文 Windows 上的子进程解码崩溃**：`mklink` / `netstat` / `robocopy` / PowerShell
  输出的是控制台代码页（简体中文为 GBK）而非 UTF-8，旧实现按 UTF-8 解码，一次换核产生
  **2287+ 条异常堆栈**。现在统一按 OEM 代码页 + `errors="replace"` 解码，PowerShell 调用
  强制 UTF-8 输出，同一次换核异常堆栈为 **0**。
- **全版本内核适配（升级或降级都能用）**：
  - **最新内核的鉴权地址**：dsh ≥ 0.1.6 启动时打印
    `dsh web: http://127.0.0.1:<端口>/?token=<随机串>`，并且**拒绝一切不带该 token 的请求**
    （401「dsh web authentication required」）。1.0.4 及以前固定加载裸地址，因此换成最新内核
    后工作台会直接显示 401 错误页、界面无法使用。现在启动器读取内核启动输出中打印的地址
    （含 token）并交给 WebView 加载，「浏览器打开」按钮同样使用该地址；旧内核只打印裸地址时
    自动回退，两侧都正常。
  - CLI 入口按 `apps/cli/package.json` 的 `bin.dsh` 解析（不再硬编码
    `apps/cli/lib/bin.js`），构建脚本、冒烟测试同步改为解析式；
  - 启动参数改为**候选梯度**：`web --no-open --port N --host 127.0.0.1` →
    `--profile web …` → 去 `--host` → 纯 `web`，只在识别到“未知参数/未知命令”时才降级
    重试，成功组合记入 `config.json`（`core_launch_mode`），换核后自动重新探测；
  - 健康检查容忍不认识 `--dump-config` 的核心（记为“该版本不支持”，而不是损坏），
    并确保 `logs\` 目录存在；
  - 核心版本号改为根 `package.json` → `apps/cli/package.json` 依次回退读取。
- **随包内核升级到上游最新版 dsh 0.1.6-alpha.2**（tag `dsh-v0.1.6-alpha.2`，
  commit `ddefc45`，2026-09-17）：安装后无需联网即可使用最新内核。

### 四、关闭应用：先确认、保存设置、关闭内核服务器

- **关闭窗口时弹出确认界面**：点窗口 X 不再直接退出，而是弹出「关闭 DeepSeek Harness？」
  对话框，三种选择：
  - **取消**：继续使用（服务器保持运行）；
  - **最小化到托盘**：窗口隐藏、内核服务器继续在后台运行（托盘菜单可再打开）；
  - **关闭应用**：先**保存设置**（写入 `config.json`）并**停止内核服务器**，再退出。
- **顺序与兜底**：`quit_app` 依次执行「保存设置 → 停止内核 → 停止托盘 → 销毁窗口」，
  且 `webview.start()` 的 `finally` 里还会再做一次保存 + 停止内核，任何退出路径都不会留下
  孤儿服务器进程；若再次按窗口 X（或外壳界面卡住无法应答），直接按「确认」处理并退出，
  不会把用户困住。
- **可关闭确认**：设置页新增「关闭窗口时先弹出确认界面」（`close_confirm`，默认开启）；
  关掉后恢复旧行为（按 `close_to_tray` 决定最小化到托盘还是直接退出）。托盘菜单的「退出」
  属于显式操作，仍直接退出（同样会先保存设置并停止服务器）。

### 五、发布链路

- **升级后外壳界面确实会被刷新（且不丢用户自定义）**：1.0.4 的 `post-update.bat` 只在缺少
  `ui\.version` 标记时才更新外壳 UI，因此所有已升级到 1.0.3/1.0.4 的安装都会**一直沿用
  旧界面**（修好的布局也送不到用户手里）。现在安装包与启动器都会按版本号比对，并采用
  **合并式刷新**：
  - 随包 UI 里的文件**就地更新**（index.html / style.css / app.js / i18n.js / themes / .version 等）；
  - **用户自己添加的文件保持不动**（例如 `ui\custom.css`）；
  - 升级前整个 `ui\` 先快照到 `ui-backup[-版本号]`（约 150 KB，只做一次），用户改过的文件可随时取回；
  - 1.0.5 起不再随包的**示例外壳插件**（`plugin-dev-kit` / `example-status` / `example-pet`）
    会在刷新时从在装 `ui\plugins\` 中清除，避免升级后仍被加载；
  - 只有在装 UI 比随包 UI **旧**时才刷新，绝不会把更新版本降级。

### 六、测试与功能实现检查

- `tools/test-1.0.5.py`：**259 项**回归（长路径删除 / 只读与 junction、入口解析与降级阶梯、
  启动地址与 token、健康检查容忍度、换核与回滚、外壳 UI 同步、控制台输出解码、CSS 不变式、
  重复 id、主题加载、i18n 空白匹配、取消更新控件、示例插件不随包、卸载校验、
  profile 旧插件迁移与 pruned 回退、预设包集合、随包商店包版本）。
- `tools/immersive-check/`：Edge/WebView2 同内核无头驱动 **16 个场景**（8 个布局 +
  真实内核 iframe 挂载 + 外观切换 + 全页面/全按钮点击穿透 + 取消更新 + 新手引导 + 语言切换），
  并带桥调用日志核对「按钮 → 桥方法」是否真的打通。
- `tools/audit-features.py`：静态交叉核对（DOM id 引用/重复、`callApi` ↔ Bridge 方法、
  按钮是否有实现、示例插件是否随包）。
- `tools/audit-backend.py`：**65 项**后端功能核对（对临时实例逐个调用全部 Bridge 方法，
  校验返回结构与持久化，含 API Key 的 DPAPI 加密往返）。
- `tools/core-update-test/`：用启动器自身的更新管线在 `dist\DeepSeek Harness` 实例上真机
  升级 0.1.1-rc.2 → 0.1.6-alpha.2、降级回 0.1.1-rc.2、再升级，全部通过；启动梯度 10/10、
  插件路径 8/8（两个内核各一轮）；`test_plugin_migration_on_core.py` 在该实例的 0.1.6 内核上
  复现「旧聚合包 + 旧商店」的升级前状态，跑完迁移后确认旧包已从清单与 `node_modules` 移除、
  新包 `@linxin666/dsh-web-all@0.3.23` 可安装且内核仍正常提供服务（token 地址 HTTP 200、
  裸地址 401）。

## 版本 1.0.4

修复与稳定性：

- **修复内部插件更新失败（ERR_PNPM_UNEXPECTED_STORE）**：旧实例的 profile 依赖可能
  链接到用户全局 pnpm store，与实例内 store 不一致导致所有插件安装 / 更新报错；
  启动时自动检测并把 store 内容合并进实例 store、重建 profile 依赖，插件操作遇到
  该错误时也会自动重建并重试一次。
- **外壳服务并发与断连容错**：外壳 UI 服务器改为多线程，慢速桥接调用（版本列表、
  目录抓取）不再阻塞其他请求；客户端中途断开不再刷错误日志。
- **外壳静态文件 MIME 修复**：显式映射 .js/.css/.json 等类型，避免 WebView2 严格
  MIME 检查导致外壳插件脚本 / 主题偶发不加载。
- **外壳插件自定义入口**：plugin.json 的 `entry` 字段（非 main.js）现在正确生效。
- **外壳插件安全加固**：插件文件解析与 zip 导入增加目录穿越防护。
- **内置商店源自愈**：旧配置的内置商店源自动指向随应用分发的 dshmarket 包版本
  （1.33.0），历史乱码标签自动修正。
- **dsh-doctor 状态目录实例化**：`DSH_DOCTOR_HOME` 指向实例数据目录，避免 C 盘
  残留与杀软 / 同步导致的 rename EPERM。
- 版本信息页「当前核心版本」显示真实核心版本号（不再显示提交哈希）。

## 版本 1.0.3

新增功能：

- **双包发布**：**懒人包**（默认，内置便携 Node.js + Git for Windows——dsh-web 生态的
  git 图形 / bash 工具 / 插件 git 源安装开箱可用）与**极简包**（`-Minimal-`，不内置
  运行时，自动检测系统 Node/Git，设置页「运行环境」显示状态与降级说明）。
- **外壳插件系统**（参考核心插件模式）：壳内插件可挂载新页面 / 卡片 / 页头按钮
  （`window.ShellPlugin` API），支持本地 zip 导入、启用 / 停用 / 卸载；内置示例插件
  （运行状态卡片、桌宠小球）。
- **生成插件提示词（创造模式开发流）**：插件页按想法生成结构化开发提示词（含
  ShellPlugin API 规范与交付格式），复制到工作台同工作区新对话中用创造模式开发
  外壳插件（壳内外联动方向预留），产物 zip 一键回装。
- **外观系统**：内置 5 组外观（深邃黑 / 深海蓝青 / 暖橙霞光 / 森林绿 / 浅色），
  设置页一键切换、即时生效并记忆；插件经 `registerTheme` 提供新外观；**桌宠插件
  接口**预留（全窗口挂载层 + `registerPet/unregisterPet/getPetLayer`）。
- **系统托盘**：托盘图标 + 菜单（打开主界面 / 启动 / 停止 / 退出），左键恢复窗口；
  新增「关闭窗口时最小化到托盘」与「开机自启」开关。
- **核心更新增强**：支持选择发布版本（tag）更新或**回退**；HTTP 代理 / npm registry
  镜像 / GitHub 下载镜像配置（设置页「网络与镜像」）。
- **安全与运维**：API Key 改用 Windows DPAPI 加密存储（旧明文自动迁移）；应用升级
  增加 exe 备份回滚；迁移/升级后自动健康检查（日志页卡片展示）；日志页过滤 / 着色 /
  复制 / 下载；中英双语界面切换；本机多实例面板；dshmarket 商店升级 1.33.0。
- **修复与体验**：安装包中文文件名乱码（旧版残留文件启动自动清理）；工作台嵌入区
  全宽铺满（去除 960px 限宽与双重滚动条）；沉浸状态记忆与淡入切换；启动加载指示。

## 版本 1.0.2

新增功能：

- **插件与数据迁入软件目录**：全部用户数据（插件 / 会话 / 设置 / 皮肤 / 宠物 /
  任务看板等）保存在安装目录 `data\`（`data\.dsh`）。首次启动自动把旧
  `~/.dsh` 移动过来（robocopy 逐文件校验，成功后才清理 C 盘旧目录，失败自动
  重试），并自动修复插件 `file:` 安装路径；pnpm 包仓库与缓存同样重定向到
  `data\` 内。
- **实例隔离**：每个安装目录独立数据 / 配置 / 端口；3080 被占用时自动改用空闲
  端口；停止服务只清理本实例进程。
- **dsh-web 仓库插件全量兼容**（[zhu1090093659/dsh-web](https://github.com/zhu1090093659/dsh-web)）：
  统一注入 `DSH_HOME`；内置 `dsh.cmd` 命令 shim 并加入核心进程 PATH（dsh-doctor /
  dsh-plugin-manager 等需要调用 dsh CLI 的插件可用），
  node / pnpm 同步暴露；自动预置 profile `pnpm-workspace.yaml`
  （`nodeLinker: hoisted`、`allowBuilds`、`minimumReleaseAgeExclude`），解决聚合包
  安装、原生依赖构建与 pnpm 11 发布年龄门禁三类安装失败。
- **外壳在线升级**：「关于」页检查应用更新 → 下载升级包（进度 + SHA256 校验）→
  一键安装（退出 → 静默覆盖 → 自动重启）；升级只覆盖程序文件，保留
  `data\` / `ui\` / `config.json` / 日志。

## 版本 1.0.1

新增功能：

- **核心本地导入**：「核心更新」页 →「从本地文件导入核心」，选择 deepseek-harness
  源码压缩包（GitHub archive 或自行备份均可），应用用内置工具链完成安装与构建并
  原子切换，失败自动回退。全程本地执行，适用于无代理 / 受限网络环境。
- **插件本地导入**：「插件」页 →「导入插件（本地文件）」，支持 npm 打包的
  `.tgz / .tar.gz` 或插件源码 `.zip`，从本地文件安装、自动启用，无需代理。
- **插件商店**：「插件」页新增「插件商店」。外壳商店为内置插件目录（与 dsh-market 同一
  数据源，浏览 / 搜索 / 一键安装 / 更新 / 卸载，始终可用）；商店源是提供 dsh Web 内
  插件市场的插件包（参考 [dsh-market/dsh-market](https://github.com/dsh-market/dsh-market)），
  内置 `dshmarket` 随应用预装（离线，首次启动后台安装但不开启），商店卡片点「启用」后
  重启服务器即可在 dsh Web「设置 → 插件市场」使用；UI 与来源标注参考 dsh-market 客户端，
  商店源模型字段化（含 catalog 目录地址），为多商店兼容打基础。

## 版本 1.0.0 发行包

`dist\DeepSeekHarness-1.0.0-Setup.exe`（约 213 MB）——自解压安装包：

- 双击运行，选择安装目录（默认 `C:\DeepSeek Harness`）
- 自动重建工作区链接（约 10 秒）、创建桌面快捷方式并启动应用
- 首次启动显示新手引导
- SHA256：`3735B4CB9E962CD62331110E804B0BAFCED59F85C9A8A8E4FEA50974E2701DB3`

## 目录结构

```
deepseek_harness/
├── build.ps1                 # 一键构建脚本（-Version 指定版本）
├── post-install.bat          # 安装包解压后执行（快捷方式 + junction 恢复 + 启动）
├── post-update.bat           # 升级包解压后执行（同上）
├── app/                      # Python 启动器源码（exe 本体）
│   ├── main.py               # 入口（pywebview 窗口 + 桥方法）
│   ├── homes.py              # ★ 实例数据目录 / DSH_HOME 重定向 / 旧数据迁移 / 路径修复
│   ├── core_api.py           # dsh 服务器子进程管理 + 端口冲突处理 + 孤儿进程清理
│   ├── updater.py            # GitHub 源码下载 / 构建 / 原子切换 + 应用升级包下载安装
│   ├── plugins.py            # 插件安装 / 卸载 / 启停 + 本地文件导入
│   ├── store.py              # 插件商店源管理（内置 dshmarket 预置源）
│   ├── settings.py           # config.json 读写
│   ├── ui_server.py          # 外壳 UI 的本地 HTTP 服务（127.0.0.1 随机端口）
│   ├── relink.py             # NTFS junction 重链接（pnpm 链接迁移）
│   ├── store/                # ★ 随应用预装的商店插件包（由 dsh-market-main.zip 构建）
│   └── ui/                   # ★ 外壳 UI（可编辑）
│       ├── index.html
│       ├── style.css         # 主题由文件顶部 CSS 变量控制
│       └── app.js            # 与 Python 桥通信逻辑
├── scripts/
│   ├── install-node.ps1      # 下载便携版 Node.js 到 runtime/
│   ├── build-core.ps1        # 构建核心（git init + pnpm install + pnpm build）
│   ├── build-store.ps1       # 从 dsh-market-main.zip 构建商店插件包（离线打包）
│   ├── make-release.ps1      # ★ 一键生成 Setup + Update 自解压包与 SHA256 校验
│   ├── write-core-info.py    # 记录上游 commit 信息
│   └── relink.py             # 构建期 junction 重链接
├── core/                     # deepseek-harness 源码（构建产物，可由应用更新）
├── runtime/                  # 便携 Node.js（node.exe + corepack + pnpm 垫片）
├── release/                  # ★ make-release.ps1 产物（Setup/Update exe + sha256）
└── dist/DeepSeek Harness/    # 最终应用（分发给用户整个文件夹）
```

## 使用（最终应用 `dist\DeepSeek Harness\`）

**正式启动方式（exe 快捷方式）**：

1. 双击桌面「DeepSeek Harness」快捷方式（或应用目录内的 `DeepSeek Harness.lnk`）。
2. 若桌面没有快捷方式（如换电脑/移动目录后），运行应用目录下的 `创建桌面快捷方式.ps1` 重建。
   （`启动/停止 DeepSeek Harness.bat` 仅用于测试排障，非正式入口。）

启动后：

1. 在「设置」页填写 DeepSeek API Key（可选项 Base URL、端口）。
2. 工作台点「启动服务器」，dsh Web 界面（默认 http://127.0.0.1:3080）自动全窗口显示在应用内。
3. 「插件」页可安装/卸载/启用/停用插件，可导入本地插件包（.tgz/.zip），
   并管理插件商店源（内置 dshmarket 商店初始关闭，启用后重启服务器生效）。
4. 「核心更新」页可检查 GitHub 上的最新源码并一键更新核心，也可从本地源码
   压缩包导入核心（无需网络）（更新前请先停止服务器）。

## 插件管理

「插件」页面提供 dsh profile（`~/.dsh/profiles/web`）的插件管理：

- **安装**：支持 npm 包名（`pnpm add`）、git 仓库、本地路径；操作实时输出，安装前自动停止服务器
- **导入**：支持本地文件 `.tgz / .tar.gz / .zip`（.zip 自动解压后安装），无需网络代理；安装完成自动启用
- **卸载**：从 profile 依赖移除
- **启用/停用**：加入/移出 `dsh.profile.bundles` 层栈（包保留在 node_modules，重启后生效）
- **列表**：区分 内置层（dsh-base 等，不可卸载）/ 已启用 / 已停用 / 普通依赖

插件操作走 dsh 官方机制（`dsh plugin --profile web <add|remove>`），由 dsh 自动调和 bundle 层。

## 插件商店

「插件」页的「插件商店」卡片分两块：

### 外壳插件商店（插件目录，始终启用）

外壳内置的插件商店，**始终可用**，与 dsh-market 使用同一数据源
（awesome-dsh-plugin 目录，每日更新，2000+ 插件，双语描述），**支持多商店源目录**：

- **多源目录**：每个带 `catalog` 地址的商店源都会并入外壳商店；顶部源标签切换
  「全部 / 单个源」，合并视图下每张卡片标注来源（`来源` 徽章）
- **浏览 / 搜索**：分类筛选 + 关键词搜索（名称 / 作者 / 描述），卡片显示名称、
  作者、Star、下载量、中文描述与仓库链接
- **安装**：一键安装（优先 npm 包，GitHub-only 插件走仓库地址）；已安装插件显示
  状态（已启用 / 已停用）与已装版本
- **更新 / 卸载**：已安装插件可一键更新（`pnpm update`）或卸载
- **添加源**：填写名称 + 安装来源（可选）+ 目录地址 plugins.json（可选，至少一项），
  仅目录源（无安装来源）也可添加——为未来更多商店类型预留

### 商店源（核心商店插件）

商店源是提供 dsh Web 内插件市场的插件包，UI 风格与来源标注参考了
dsh-market 客户端的卡片 / 状态徽章 / 版本号设计：

- **内置商店**：随应用预装 `dshmarket` 商店插件包。包体由本地源码归档
  `dsh-market-main.zip` 经 `scripts\build-store.ps1` 构建而成（构建期编译
  `lib/` + `client/` 并把运行时依赖 js-yaml/argparse/undici 一并打进 tarball）。
  首次启动应用时在后台**预装但不开启**（离线安装进 profile，并以
  `cordis.patch.yml` 的 `disabled: true` 行停用——dsh 官方补丁层机制，与
  dsh-market 自身的停用方式一致，不受后续插件操作的 bundle 调和影响）；
  在商店卡片点「启用」即时生效，重启服务器后在 dsh Web「设置 → 插件市场」使用
- **来源标注**：每个商店源展示名称、内置徽章、状态（已启用/已停用/未安装）、
  已装版本号，以及来源主页链接（`homepage` 字段）；多商店源可并存，卡片按源区分
- **添加 / 移除商店源**：支持 npm 包名、git 仓库、本地路径；内置源不可移除（可停用）
- **兼容基础**：商店源模型（`store_sources`）字段化——`name`（安装包名）、
  `label`、`spec`、`homepage`、`catalog`（目录地址）、`builtin`；支持多源目录
  合并与「仅目录」源，后续新增商店类型只需扩展该模型

配置文件 `config.json` 字段：

```json
{
  "api_key": "",          // DeepSeek API Key（或从设置页填写）
  "base_url": "",         // 可选，API Base URL
  "port": 3080,           // dsh Web 端口
  "auto_start": false,    // 启动应用时自动启动服务器
  "open_browser": false,  // 启动服务器时同时打开系统浏览器
  "core_dir": "core",
  "runtime_dir": "runtime",
  "app_version": "1.0.1",
  "store_sources": [      // 插件商店源列表（多源兼容模型）
    {
      "name": "dshmarket",                  // 安装包名
      "label": "dshmarket 插件商店",        // 显示名称
      "spec": "store/dshmarket-1.50.0.tgz", // 相对应用目录的本地包路径
      "homepage": "https://github.com/dsh-market/dsh-market",  // 来源标注
      "catalog": "https://awesome-dsh-plugin.com/plugins.json", // 外壳商店目录地址
      "builtin": true
    }
  ]
}
```

## 自定义外壳 UI

`ui/` 目录下的 HTML/CSS/JS 就是外壳界面，保存后重启应用生效：

- `style.css` 顶部 `:root` 的 CSS 变量控制全部配色（换肤只需改这些变量）
- `index.html` 修改布局与页面
- `app.js` 顶部注释说明了与 Python 桥的通信方式：
  - pywebview 环境：`window.pywebview.api.<方法>(参数)`
  - 普通浏览器环境：`POST /api/bridge/<方法>`（JSON body）
- 桥方法列表：`get_state`、`save_settings`、`start_server`、`stop_server`、
  `restart_server`、`read_log`、`check_update`、`download_update`、`cancel_update`、
  `list_plugins`、`install_plugin`、`remove_plugin`、`set_plugin_enabled`、
  `import_plugin`、`pick_plugin_file`、`store_list`、`store_add`、`store_remove`、
  `store_set_enabled`、`import_core`、`pick_core_archive`、`check_app_update`

## 从源码构建

环境要求：Windows 10/11（内置 WebView2）、Python 3.12+、网络。

```powershell
# 1. 安装依赖（pywebview + PyInstaller）
python -m pip install pywebview pyinstaller

# 2. 将官方源码放入 core\（或由应用内更新自动下载）
#    （本仓库构建时使用的版本与 GitHub master 一致）

# 3. 一键构建：下载便携 Node → 构建核心 → PyInstaller 打包 → 组装 dist
powershell -ExecutionPolicy Bypass -File build.ps1
```

分步执行（可选）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-node.ps1   # 便携 Node
powershell -ExecutionPolicy Bypass -File scripts\build-core.ps1      # 构建核心
python -m PyInstaller --noconfirm --distpath dist\pyinstaller `
    --workpath dist\.build app\dsh-desktop.spec                       # 打包 exe
```

## 核心更新机制

「核心更新」页流程（`updater.py`）：

1. 查询 GitHub API `repos/deepseek-ai/deepseek-harness/commits/master` 获取最新提交
2. 下载 `https://github.com/deepseek-ai/deepseek-harness/archive/refs/heads/master.zip`
3. 解压 → `git init`（上游构建脚本需要）→ `pnpm install --node-linker=hoisted`
4. `pnpm run build`（关闭 pnpm 11 的隐式依赖检查，避免网络抖动时的二次安装）
5. 原子切换：旧核心移到 `core.backup`，新核心移入 `core`，重建 pnpm junction 链接
6. 记录上游 commit 到 `core/.dsh-desktop-info.json`，下次检查即显示「已是最新」

## 已知限制

- 更新期间请勿关闭应用（会中断构建；下次启动自动清理残留临时目录）
- 在线更新需要网络（GitHub + npm registry）；本地导入核心/插件无需 GitHub，但依赖安装仍需 npm registry（有 pnpm 缓存时自动复用）
- 首次构建核心约需 10 分钟（依赖安装 + 编译），后续更新利用 pnpm 缓存会快很多
