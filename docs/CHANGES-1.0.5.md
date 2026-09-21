# 1.0.5 修改列表

**状态**：代码与内核已就绪；第一版已打包并发布 v1.0.5；**本轮（旧插件清理 + 商店升级）为同版本覆盖更新**
**基线**：上一发布提交 `e168454`（v1.0.4）
**当前提交**：`404dc99`（缺陷修复与内核适配）、`29a937b`（随包内核 + 上传脚本）、本轮旧插件迁移提交
**变更规模**：33 个文件，+4100 / −223 行（含本轮）

---

## 一、随包内核（不在 git 中，随安装包分发）

| 项目 | 变更 |
| --- | --- |
| 版本 | `dsh 0.1.1-rc.2` → **`dsh 0.1.6-alpha.2`** |
| 来源 | tag `dsh-v0.1.6-alpha.2`，upstream commit `ddefc45`，2026-09-17（`Merge pull request #4469 … release-dsh-0.1.6-alpha.2`） |
| 构建 | 用启动器自身的更新管线重建（`pnpm install` + `pnpm build`），pnpm 11.7.0 / Node 24.16.0 |
| 目录重定位 | **3438 个 pnpm workspace junction** 全部重建到新路径（`relink.rebase_junctions`，0 失败，134s） |
| 标记文件 | `.dsh-desktop-info.json`（tag/commit/date/source=github）、`.upstream-commit` |
| 验证 | `node core/apps/cli/lib/bin.js --version` → `0.1.6-alpha.2`（exit 0）；`--profile web --dump-config` → exit 0 |
| 说明 | `core/` 一直由 `.gitignore` 排除（约 2.7GB，不进源码仓库）；源码仓库推送到 GitHub，**最新内核随 4 个安装包分发**。旧内核保留在 `.tmp-core-old-0.1.1-rc.2` 以便回滚 |

---

## 二、代码修改（git 跟踪）

### 2.1 缺陷修复

| 文件 | 变更 |
| --- | --- |
| `app/ui/app.js` | **启动服务器期间切换页签导致界面「异常放大」/卡死**：`openFrame` 原来无条件 `setImmersive(true)`，若用户在启动等待期间（1–3 分钟，首次构建更久）切到别的页签，沉浸模式会隐藏侧边栏与页头、把 `.content` padding 归零并禁止滚动，而「退出全屏」按钮位于已被隐藏的工作台页内 → 既无导航也无返回入口。现在只有停留在工作台页时才自动全屏，`showPage` 离开工作台页时自动退出全屏。另：**外观（主题）系统修好**（相对路径被当 CSS 注入）；启动服务器后使用内核打印的地址（含 token）；新增「取消更新」按钮的显隐与点击处理 |
| `app/ui/i18n.js` | **语言切换修好**：原来用文本节点整串精确匹配字典键，导航文本带缩进换行（`<span>◇</span>插件\n        `）永远匹配不上；改为按去空白后的文本查表并保留原空白；新增 `update.cancel`、`settings.closeConfirm`、`close.*` 中英文词条 |
| `app/main.py`（关闭流程） | **关闭应用时确认 + 保存 + 停止内核**：`_on_closing` 在开启确认时取消原生关闭并置位 `_close_requested`（`poll_tray` 把它带给外壳，另有 evaluate_js 即时通道）；新增 `cancel_close()` / `hide_to_tray()` / `_save_state()` / `_hide_window()` / `_nudge_shell()`；`quit_app()` 改为「保存设置 → 停止内核 → 停止托盘 → 销毁窗口」；`webview.start()` 的 `finally` 兜底保存 + 停止内核；确认界面出现后再按一次 X 视为确认并直接退出（外壳无响应时也不会被困住） |
| `app/settings.py` | 新增 `close_confirm`（默认 `True`）：关闭窗口时是否先弹确认界面 |
| `app/ui/index.html` | **消除重复 id**：`#store-catalog` 同时是目录列表 `<div>` 与目录地址 `<input>`，导致「添加商店源」取到 div、`.value` 为 undefined、点击即抛 `TypeError`；输入框改为 `store-catalog-url`。新增 `#btn-cancel-update`（取消更新）、关闭确认对话框 `#close-confirm-dialog`（取消 / 最小化到托盘 / 关闭应用，置于 `<script>` 之前以便绑定事件）与设置项 `#close-confirm` |
| `app/ui/themes/*.css` | 主题文件本身未改动（5 套内置外观 + 插件可注册外观）；问题在加载逻辑，已由 `applyTheme` 修复 |
| `app/plugins.py` | `remove()` 先校验插件是否为已安装依赖（原来对任何名字都回「操作已开始」再异步失败）；暂存目录改用长路径安全删除 |
| `app/ui/style.css` | **工作台退出全屏后 iframe 塌陷**：iframe 与空状态改绝对定位铺满容器（`top/right/bottom/left:0`），不再依赖 `height:100%`（在 flex 决定高度的父级下会回落到 150px）；沉浸模式保持 `position: relative`；消除非全屏时的双滚动条 |
| `app/homes.py` | 新增 `remove_tree()` / `long_path()`：`\\?\` 扩展长度路径递归删除，清理只读属性（git pack），**绝不跟随 junction**，robocopy 空镜像兜底；新增 `console_text_kwargs()`（OEM 代码页 + `errors=replace`）、`PS_UTF8_PREFIX`、`version_newer()`；健康检查改为多形态容忍 + 保证 `logs\` 存在 |
| `app/updater.py` | 换核前校验（目录存在 + CLI 入口存在）、失败把旧核心放回、换核后校验可启动入口（不通过则回滚）、删不掉的陈旧备份改用时间戳名而不阻塞更新、新增 `cleanup_stale_core_backups()`、`_remove_path` 委托给长路径安全实现 |
| `app/core_api.py` | CLI 入口按 `apps/cli/package.json` 的 `bin.dsh` 解析（`resolve_cli_entry`）、7 级启动候选梯度与按次日志判定、启动记忆 `core_launch_mode`、**内核打印地址（token）发现** `_discover_web_url()`、日志句柄回收、孤儿进程按解析出的入口匹配、版本号回退链 |
| `app/relink.py`、`app/junctions.py`、`app/main.py` | 子进程输出按控制台代码页解码（`mklink`/`netstat`/PowerShell），PowerShell 调用强制 UTF-8 输出 —— 修复非英文 Windows 上一次换核产生 2287+ 条 `UnicodeDecodeError` 堆栈 |
| `app/settings.py` | `VERSION = "1.0.5"`；新增 `core_launch_mode` 配置项 |
| `app/shellui.py`（新增） | 启动时按版本同步外壳 UI：随包更新版本时刷新并保留 `ui-backup[-版本]`，**不把更新版本的在装 UI 降级**，失败自动还原 |
| `post-update.bat` | UI 刷新条件由“缺少 `ui\.version` 标记”改为“标记不是本版版本号”（1.0.4 的旧规则导致已升级安装永远沿用旧界面） |
| `app/ui/.version` | `1.0.4` → `1.0.5` |

### 2.1b 随包内容调整

| 变更 | 说明 |
| --- | --- |
| `app/ui/plugins/{example-status,example-pet,plugin-dev-kit}` → `examples/shell-plugins/` | **示例外壳插件不再随任何安装包分发**，只作开发参考（附 `README.md` 说明规范与导入方式）；`app/ui/plugins/` 不再存在，安装后「外壳插件」列表为空 |

### 2.1c 旧版 dsh-web 插件清理与内置商店升级（本轮）

背景（已核对 npm 元数据与包内容）：

| 证据 | 内容 |
| --- | --- |
| 上游弃用 | `@linxin666/dsh-web-ui-all` 最新版 `0.3.6`（2026-08-27）带 npm 弃用提示「迁移到 `@linxin666/dsh-web-all`，请勿用此版本」；安装时 pnpm 打印 `[WARN] deprecated @linxin666/dsh-web-ui-all@0.3.6: 迁移到 @linxin666/dsh-web-all` |
| 包内迁移指令 | 该包 `dsh.migrate = { to: "@linxin666/dsh-web-all", since: "0.3.6" }` |
| 版本落差 | 旧聚合包及其全部依赖固定在 `0.3.6`；作者当前家族为 `0.3.23`（2026-09-16），声明 `dsh.engines.dsh >= 0.1.5-rc.1` |
| 兼容问题 | 用户实测 `dsh-web-ui-all` 与随包的 `0.1.6-alpha.2` 内核不兼容（Web UI 异常） |

| 文件 | 变更 |
| --- | --- |
| `app/migrate.py`（新增） | profile 迁移：**清单优先**把 5 个包从 `dependencies` 与 `dsh.profile.bundles` 移除（离线也生效，这是决定内核是否加载插件的地方），随后在 profile 内执行 `pnpm install --no-frozen-lockfile --ignore-scripts` 让 `node_modules` 与清单一致（删除多余旧包、装入随包商店包）；顺带把内置 `dshmarket` 依赖重指向 `<app>\store` 下最高版本的 tgz（`bundled_store()`）；记录上游 `dsh.migrate.to` 目标（只记录，**不自动安装**）；无 profile / 无运行时 / 已迁移分别返回 `no-profile` / `no-core-cli` / `up-to-date`，绝不抛异常 |
| ↑ 两处真机实测得出的设计修正 | ① **不能用 `dsh plugin --profile web remove` 做清理**：清单已被改为不含这些依赖，pnpm 会以 `ERR_PNPM_CANNOT_REMOVE_MISSING_DEPS` 拒绝，prune 永远不会执行 → 改为 `pnpm install` 对账；② **pnpm 输出必须重定向到文件、超时用 `taskkill /F /T` 杀进程树**：Windows 上杀掉 `pnpm.cmd` 后 node 子进程仍持有管道写端，`subprocess.run(capture_output=True)` 会永久阻塞在 `communicate()`（实测卡死 30 分钟以上），导致 `_heal_done` 永不置位、**所有插件操作被阻塞** → 改为文件日志 + 超时杀树，并把 600s 作为上限 |
| `scripts/rebundle-store-tgz.py` | 默认版本不再硬编码 `1.33.0`，改为从 `app/settings.py` 的内置商店 spec 推导；构建时删除其它 `dshmarket-*.tgz`（否则 `-SkipCoreBuild` 打包会把已下线的旧商店包重新塞回安装包） |
| `app/homes.py`、`app/updater.py`（卡死点加固） | 新增 `kill_process_tree()`（`taskkill /F /T`）、`run_capture()`（输出写文件、超时杀进程树——替代 Windows 上会永久阻塞的 `subprocess.run(capture_output=True, timeout=…)`）、`run_stream()`（守护线程读输出 + 可取消 + 杀树）。改用于：profile store 自愈的 pnpm install（原 timeout=1800s 的管道捕获，一旦超时会让 `_heal_done` 永不置位、**所有插件操作永久阻塞**）、健康检查的 `dsh --dump-config`（内核会再生成子进程）、以及核心更新的 pnpm install/build（原 `for line in proc.stdout` 读原始管道且**无法取消**：点「取消更新」后仍要等整轮 pnpm 跑完；现在 `stop=self._cancel`，取消即刻杀树返回） |
| `app/main.py` | `_heal_profile()` 在 profile store 自愈后调用 `migrate.migrate_profile(APP_DIR, node_exe, bin_js, home)`，位于 `_heal_done.set()` 之前（插件操作会等它） |
| `post-update.bat` | 新增升级期清理块：`set DSH_HOME=…\data\.dsh` + `node core\apps\cli\lib\bin.js plugin --profile web remove <5 个包>`，profile 或 CLI 缺失时 `goto skip_profile_migration` 安全跳过；冒烟测试的 dry-run 副本没有 pnpm store，用 `no-plugin-migration.flag` 跳过（由 `smoke-release.ps1` 生成） |
| ↑ 批处理文件编码修复（冒烟实测发现） | `post-update.bat` / `post-install.bat` 必须是**严格 GBK + CRLF**：此前编辑把 UTF-8 写进了 ANSI 批处理，产生替换字符（U+FFFD），其双字节前导字节吞掉换行，cmd.exe 失去行边界、把后续行当命令执行（实测升级脚本整个跑飞、junction 未恢复）→ 已从干净版本重建，并新增回归检查（无 BOM / 严格 GBK / 无替换字符 / 全 CRLF） |
| `app/settings.py`、`build.ps1` | 内置商店源 spec 由 `store/dshmarket-1.33.0.tgz` 改为 `store/dshmarket-1.50.0.tgz` |
| `app/store/dshmarket-1.50.0.tgz`（替换） | 1.33.0 → **1.50.0**（peer `@deepseek-ai/dsh-settings: ^0.1.0-rc.7 \|\| ^0.1.1-rc.2 \|\| ^0.1.2-alpha.2`，可在 0.1.6 内核上加载）；1.33.0 的 peer `^0.1.1-rc.2` 不含 0.1.6 |
| `app/ui/app.js` | 「一键填入全家桶」→ `@linxin666/dsh-web-all@0.3.23`；「免编译预设」对齐作者当前 19 个包 + `dsh-better-sidebar` + `@mlgbnb/dsh-archive-manager`（移除 `dsh-web-ui-all` / `chat-recovery` / `desktop-launcher` / `perf` / `client-ui-aionui-panel`，补入 `dsh-i18n` / `dsh-usage` / `dsh-client-ui-preset-center` / `dsh-client-ui-model-capabilities` / `dsh-session-archive`） |
| `app/ui/index.html`、`app/ui/i18n.js` | 预设按钮文案与提示同步为「dsh-web 全家桶（聚合包 0.3.23）」 |

### 2.2 构建与发布

| 文件 | 变更 |
| --- | --- |
| `build.ps1` | 默认版本 `1.0.5`；新增 `Get-CoreCliEntry`（解析 `bin.dsh`，回退 `apps/cli/lib/bin.js`）；核心存在性判断与「随包核心可启动」校验改用解析结果 |
| `scripts/smoke-release.ps1` | 默认版本 `1.0.5`；核心入口检查改为解析式（不再硬编码路径） |
| `scripts/make-release.ps1`、`scripts/upload-release.ps1` | 默认版本 `1.0.5` |
| `scripts/upload-release.mjs`（新增） | **Node 版上传脚本**：提交 + 打标签 + 推送、创建 Release、上传安装包与校验文件；凭据依次取 `--token` / `GITHUB_TOKEN` / `GH_TOKEN` / git 凭据助手；内置重试与 `--dry-run`。原因：本机仅 PowerShell 5.1（`upload-release.ps1` 要求 PS7），且 schannel 证书吊销检查不可用（`CRYPT_E_REVOCATION_OFFLINE`），Node 的 OpenSSL 正常 |
| `.gitignore` | `tools/` 改为 `tools/*` + 放行测试脚本与 `tools/immersive-check/`、`tools/core-update-test/`（7-Zip 等二进制仍忽略） |
| `scripts/make-patch.ps1`（新增） | 从 `dist\DeepSeek Harness` 组装**增量补丁**：`payload\{exe,_internal,ui,store\*,post-update.bat}` + `apply-patch.ps1` + 双击入口 + `MANIFEST.sha256` + `补丁说明.md`，压缩为 `release\DeepSeekHarness-<ver>-Patch.zip`（约 14.5 MB）；打包前校验 `post-update.bat` 严格 GBK + CRLF 且无替换字符 |
| `scripts/apply-patch.ps1`、`scripts/apply-patch.bat`（新增） | 补丁应用器：**只认 `-InstallDir` 指定的实例**（按进程可执行文件路径匹配——不会因为别的实例在运行而拒绝，也绝不会关掉别的实例）；备份 → 镜像 `_internal` → 合并 UI → 替换 exe / `post-update.bat` → 写入新商店包并删旧包 → `dsh plugin remove`（只传清单里确实存在的名字；`Start-Process` 参数自行加引号，兼容含空格的默认安装路径 `C:\DeepSeek Harness`）→ profile 清单清理 → config 修正 → 逐文件哈希校验；支持 `-DryRun` / `-StopApp` / `-NoRestart` |
| `scripts/test-patch.ps1`（新增） | 补丁验收：把补丁应用到一个**真实实例的副本**（离线场景 + core/runtime junction 的 CLI 场景），39 项断言全部通过 |
| `scripts/fix-script-encodings.py`（新增） | 脚本编码归一化与检查（PS1 → UTF-8 BOM + CRLF；`.bat` → 控制台代码页 + CRLF），防止再次出现「UTF-8 写进 ANSI 批处理」导致的 cmd 行边界丢失 |
| `docs/PATCH-1.0.5.md`（新增） | 增量补丁说明：用途、动作清单、使用/回滚、验收方法、已知边界 |

### 2.3 文档与发布说明

| 文件 | 变更 |
| --- | --- |
| `RELEASE_NOTES.md` | 重写为 v1.0.5 发布声明：三类缺陷 + 最新内核 401 token 适配 + 非英文 Windows 解码崩溃 + 界面刷新缺陷 + 随包内核升级；含测试结果表与开源声明 |
| `README.md` | 新增 1.0.5 章节（修复点、全版本适配说明、测试入口） |
| `docs/TEST-REPORT-1.0.5.md`（新增） | 完整测试报告：浏览器实测数据（含修复前后对照）、Python 回归、真机升级/降级/再升级、启动梯度、插件路径、结论与遗留 |

### 2.4 测试与工具（新增）

| 文件 | 用途 |
| --- | --- |
| `tools/test-1.0.5.py` | **259 项**回归（长路径/只读/junction、入口解析、启动梯度、token 地址、健康检查、换核回滚、UI 同步、解码、CSS 不变式、重复 id、主题加载、i18n 空白匹配、取消更新控件、示例插件不随包、卸载校验、**旧插件迁移与 prune 回退、预设包集合、随包商店包版本、启动/升级脚本接线**） |
| `tools/audit-features.py` | 静态交叉核对：DOM id 引用与重复、`callApi` ↔ Bridge 方法、按钮是否有实现、示例插件是否随包 |
| `tools/audit-backend.py` | **65 项**后端功能核对：对临时实例逐个调用全部 Bridge 方法并校验返回结构与持久化 |
| `tools/check-duplicate-ids.py` | 单独排查 HTML 重复 id（会被 `getElementById` 静默绑定到错误元素） |
| `tools/immersive-check/cdp_probe.mjs`、`stub_server.py`、`diag_removal.py` | Edge/WebView2 同内核无头驱动：**16 个场景**（8 个布局 + 真实内核 iframe 挂载 + 外观切换 + 全页面/全按钮点击穿透并核对「按钮 → 桥方法」+ 取消更新 + 新手引导 + 语言切换）+ 截图；`diag_removal.py` 用于诊断删不掉的目录 |
| `tools/core-update-test/run_core_update.py` | 用启动器自身的更新管线在实例目录真机升级/降级 |
| `tools/core-update-test/test_launch_ladder.py` | 真实 CLI 的启动参数降级与记忆验证 |
| `tools/core-update-test/test_plugin_on_core.py` | 真实内核上的插件安装/列出/卸载验证 |
| `tools/core-update-test/test_plugin_migration_on_core.py`（新增） | 在开发实例的真实内核上复现升级前状态（5 个旧包 + 旧商店）→ 商店源重指向 → 迁移（清单 + `node_modules`）→ 安装 `@linxin666/dsh-web-all@0.3.23` → 内核启动与 HTTP 校验 |
| `scripts/test-patch.ps1`（新增） | 增量补丁验收（真实实例副本，39 项）：离线场景与 CLI 场景全部通过 |
| `examples/shell-plugins/`（含 README） | 外壳插件示例与开发套件：仅作开发参考，**不随包分发** |

---

## 三、构建工具链（不在 git 中）

| 项目 | 内容 |
| --- | --- |
| 位置 | `tools/python-full/pkg/tools/python.exe`（可移植 CPython，不动系统环境、不写注册表） |
| 版本 | CPython **3.12.10** + pip 25.0.1 |
| 打包依赖 | `pyinstaller 6.22.2`、`pywebview 6.2.1`、`pyinstaller-hooks-contrib 2026.7`、`pythonnet 3.1.0`、`clr_loader 0.3.1`、`bottle 0.13.4`、`proxy_tools 0.1.0`、`PyYAML 6.0.3`、`setuptools 84.0.0`、`typing_extensions 4.16.0` |
| 冒烟验证 | PyInstaller 冻结「import webview + yaml」测试程序并成功运行；`_internal` 产出 `webview/pythonnet/clr_loader/yaml/setuptools`，与 1.0.4 包结构一致 |
| 与 1.0.4 差异 | 不再打入 `cryptography` / `bcrypt`（应用未引用；`app/crypto.py` 走 ctypes/DPAPI），包体更小 |
| 其它就绪 | `runtime/`（Node 24.16.0 + PortableGit 2.55.0）、`app/store/dshmarket-1.50.0.tgz`、`tools/7zip`（含 GUI SFX 模块）均在位 |

---

## 四、验证结论（已完成，全部可复跑）

| 测试 | 结果 |
| --- | --- |
| `tools/test-1.0.5.py`（含新工具链运行） | **259/259 通过** |
| `tools/audit-features.py` | **ALL CHECKS PASS**（无缺失/重复 id、无未实现按钮、无未实现桥方法、示例插件未随包） |
| `tools/audit-backend.py` | **65/65 通过**（全部 Bridge 方法可用且返回结构正确） |
| `tools/core-update-test/test_plugin_migration_on_core.py`（新增） | **32/32 通过**：真实 0.1.6 内核上复现旧插件 + 旧商店的升级前状态 → 商店源重指向 → 迁移（清单 + pnpm 对账 + 幂等）→ 安装 `@linxin666/dsh-web-all@0.3.23` → 迁移前后内核均 token 地址 HTTP 200 / 裸地址 401 |
| 安装包冒烟 `smoke-release.ps1`（懒人包 / 极简包） | 真实解包 + 校验 + 升级 dry-run（`post-update.bat` 真实执行、UI 合并刷新、用户文件保留、核心 junction 恢复）**全部通过** |
| 增量补丁 `scripts\test-patch.ps1` | **39/39 通过**（真实实例副本上离线应用 + 真实 `dsh plugin remove`），补丁包 `release\DeepSeekHarness-1.0.5-Patch.zip`（14.5 MB） |
| `tools/immersive-check/`（Edge 153 无头，13 场景） | **16/16 通过**；修复前退出全屏 iframe=980×150，修复后 980×622；外观 `rgb(14,17,22)`→`rgb(244,246,250)`；导航「◇插件」→「◇Plugins」；取消更新可点击并调用 `cancel_update` |
| 真机升级 `0.1.1-rc.2 → 0.1.6-alpha.2` | 通过（备份回收、健康检查 exit 0、HTTP 200） |
| 真机降级 `0.1.6-alpha.2 → 0.1.1-rc.2` | 通过（裸地址 HTTP 200，旧内核无需 token） |
| 再升级回 `0.1.6-alpha.2` | 通过 |
| 启动梯度 / 插件路径（两个内核各一轮） | 10/10、8/8 |
| 最新内核鉴权对照 | 裸地址 → 401（界面无法使用）；token 地址 → 真实界面挂载（标题「DSH 本地构建」、`#root` 已挂载） |
| 随包内核（0.1.6-alpha.2）自检 | `--version` exit 0；`--profile web --dump-config` exit 0 |

### 4.1 本轮「功能实现检查」发现并修复的问题

| # | 功能 | 症状 | 根因 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 外观（主题）系统（1.0.3 新增） | 5 个外观点了都没反应 | `applyTheme` 只识别 URL 前缀，内置外观是相对路径 → 把路径当 CSS 注入 | 已修复并实测 |
| 2 | 界面语言切换（1.0.3 新增） | 选 English 仍是中文 | i18n 用文本节点整串精确匹配，导航文本带缩进换行 | 已修复并实测 |
| 3 | 添加商店源 | 点击即抛 `TypeError` | HTML 重复 id `store-catalog`（div 与 input 同名） | 已修复并实测 |
| 4 | 取消核心更新 | 无法中止长更新 | 桥方法已实现、界面无入口 | 已补按钮并实测 |
| 5 | 卸载插件 | 未安装的名字也回「操作已开始」 | `remove()` 未校验依赖 | 已修复 |
| 6 | 示例外壳插件 | 随包出现在产品里 | 放在 `app/ui/plugins` 被打包 | 已移出打包路径 |

---

## 五、打包（同版本覆盖发布）

第一版 v1.0.5 已打包并发布；本轮代码变更（`app/migrate.py` 等）后**以同一版本 1.0.5 重新打包**
（用户确认：版本号不变、覆盖上传）。

```powershell
# 便携工具链（不写系统环境）：PyInstaller 打包 → dist\DeepSeek Harness
$env:PATH = "<repo>\tools\python-full\pkg\tools;$env:PATH"
powershell -ExecutionPolicy Bypass -File build.ps1 -Version 1.0.5 -SkipCoreBuild -Flavor Lazy
powershell -ExecutionPolicy Bypass -File build.ps1 -Version 1.0.5 -SkipCoreBuild -Flavor Minimal
# 自解压安装/升级包 + 校验文件
powershell -ExecutionPolicy Bypass -File scripts\make-release.ps1 -Version 1.0.5 -Flavor Lazy -SkipBuild
powershell -ExecutionPolicy Bypass -File scripts\make-release.ps1 -Version 1.0.5 -Flavor Minimal -SkipBuild
# 冒烟（真实安装 → 启动 → 检查 payload / UI 合并刷新 / junction 恢复 / 商店包）
powershell -ExecutionPolicy Bypass -File scripts\smoke-release.ps1 -Version 1.0.5
powershell -ExecutionPolicy Bypass -File scripts\smoke-release.ps1 -Version 1.0.5 -Flavor Minimal
```

产物（`release/`）：`DeepSeekHarness-1.0.5-Setup.exe`、`-Update.exe`、`-Minimal-Setup.exe`、
`-Minimal-Update.exe` + 各自 `.sha256` + `SHA256SUMS-1.0.5[-Minimal].txt`。

## 六、覆盖上传（v1.0.5 同标签重发）

`scripts/upload-release.mjs` 本轮补齐“重发”能力：

| 参数 | 作用 |
| --- | --- |
| `--force-tag` | 已存在的标签移动到当前 HEAD（本地 `git tag -af` + `git push --force origin <tag>`） |
| （默认）release 已存在时 | `PATCH /releases/<id>` 用最新 `RELEASE_NOTES.md` 刷新发布说明 |
| 同名资产 | 先 `DELETE /releases/assets/<id>` 再重新上传（原有行为） |

实际命令（凭据取 `GITHUB_TOKEN`/`GH_TOKEN`/git 凭据助手，push 走 `github.com`，资产走 `uploads.github.com`）：

```powershell
node scripts\upload-release.mjs --version 1.0.5 --force-tag
```

网络说明：本机 `github.com`（git push、`uploads.github.com`）为**间歇性不可达**，
`api.github.com` / `codeload.github.com` / `objects.githubusercontent.com` 稳定可达；
脚本内置重试与退避，失败可原样重跑（已存在的 release 与同名资产会被正确替换）。
