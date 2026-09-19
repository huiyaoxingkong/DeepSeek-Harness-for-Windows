# 1.0.5 修改列表（待确认后打包上传）

**状态**：代码与内核已就绪、已本地提交；**尚未打包、尚未上传**
**基线**：上一发布提交 `e168454`（v1.0.4）
**当前提交**：`404dc99`（缺陷修复与内核适配）、`29a937b`（随包内核 + 上传脚本）
**变更规模**：30 个文件，+3849 / −223 行

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
| `app/ui/style.css` | **工作台退出全屏后 iframe 塌陷**：iframe 与空状态改绝对定位铺满容器（`top/right/bottom/left:0`），不再依赖 `height:100%`（在 flex 决定高度的父级下会回落到 150px）；沉浸模式保持 `position: relative`（原为 `static`，会让绝对定位子元素的包含块跑到视口）；消除非全屏时的双滚动条 |
| `app/ui/app.js` | 启动服务器后使用内核打印的地址（含 token），无该字段时回退裸地址 |
| `app/homes.py` | 新增 `remove_tree()` / `long_path()`：`\\?\` 扩展长度路径递归删除，清理只读属性（git pack），**绝不跟随 junction**，robocopy 空镜像兜底；新增 `console_text_kwargs()`（OEM 代码页 + `errors=replace`）、`PS_UTF8_PREFIX`、`version_newer()`；健康检查改为多形态容忍 + 保证 `logs\` 存在 |
| `app/updater.py` | 换核前校验（目录存在 + CLI 入口存在）、失败把旧核心放回、换核后校验可启动入口（不通过则回滚）、删不掉的陈旧备份改用时间戳名而不阻塞更新、新增 `cleanup_stale_core_backups()`、`_remove_path` 委托给长路径安全实现 |
| `app/core_api.py` | CLI 入口按 `apps/cli/package.json` 的 `bin.dsh` 解析（`resolve_cli_entry`）、7 级启动候选梯度（`LAUNCH_CANDIDATES`）与按次日志判定、启动记忆 `core_launch_mode`、**内核打印地址（token）发现** `_discover_web_url()`、日志句柄回收、孤儿进程按解析出的入口匹配、版本号回退链 |
| `app/relink.py`、`app/junctions.py`、`app/main.py` | 子进程输出按控制台代码页解码（`mklink`/`netstat`/PowerShell），PowerShell 调用强制 UTF-8 输出 —— 修复非英文 Windows 上一次换核产生 2287+ 条 `UnicodeDecodeError` 堆栈 |
| `app/plugins.py`、`app/shellplugins.py` | 暂存/解包目录改用长路径安全删除 |
| `app/settings.py` | `VERSION = "1.0.5"`；新增 `core_launch_mode` 配置项 |
| `app/shellui.py`（新增） | 启动时按版本同步外壳 UI：随包更新版本时刷新并保留 `ui-backup[-版本]`，**不把更新版本的在装 UI 降级**，失败自动还原 |
| `post-update.bat` | UI 刷新条件由“缺少 `ui\.version` 标记”改为“标记不是本版版本号”（1.0.4 的旧规则导致已升级安装永远沿用旧界面） |
| `app/ui/.version` | `1.0.4` → `1.0.5` |

### 2.2 构建与发布

| 文件 | 变更 |
| --- | --- |
| `build.ps1` | 默认版本 `1.0.5`；新增 `Get-CoreCliEntry`（解析 `bin.dsh`，回退 `apps/cli/lib/bin.js`）；核心存在性判断与「随包核心可启动」校验改用解析结果 |
| `scripts/smoke-release.ps1` | 默认版本 `1.0.5`；核心入口检查改为解析式（不再硬编码路径） |
| `scripts/make-release.ps1`、`scripts/upload-release.ps1` | 默认版本 `1.0.5` |
| `scripts/upload-release.mjs`（新增） | **Node 版上传脚本**：提交 + 打标签 + 推送、创建 Release、上传安装包与校验文件；凭据依次取 `--token` / `GITHUB_TOKEN` / `GH_TOKEN` / git 凭据助手；内置重试与 `--dry-run`。原因：本机仅 PowerShell 5.1（`upload-release.ps1` 要求 PS7），且 schannel 证书吊销检查不可用（`CRYPT_E_REVOCATION_OFFLINE`），Node 的 OpenSSL 正常 |
| `.gitignore` | `tools/` 改为 `tools/*` + 放行测试脚本与 `tools/immersive-check/`、`tools/core-update-test/`（7-Zip 等二进制仍忽略） |

### 2.3 文档与发布说明

| 文件 | 变更 |
| --- | --- |
| `RELEASE_NOTES.md` | 重写为 v1.0.5 发布声明：三类缺陷 + 最新内核 401 token 适配 + 非英文 Windows 解码崩溃 + 界面刷新缺陷 + 随包内核升级；含测试结果表与开源声明 |
| `README.md` | 新增 1.0.5 章节（修复点、全版本适配说明、测试入口） |
| `docs/TEST-REPORT-1.0.5.md`（新增） | 完整测试报告：浏览器实测数据（含修复前后对照）、Python 回归、真机升级/降级/再升级、启动梯度、插件路径、结论与遗留 |

### 2.4 测试与工具（新增）

| 文件 | 用途 |
| --- | --- |
| `tools/test-1.0.5.py` | 98 项回归（长路径/只读/junction、入口解析、启动梯度、token 地址、健康检查、换核回滚、UI 同步、解码、CSS 不变式） |
| `tools/immersive-check/cdp_probe.mjs`、`stub_server.py`、`diag_removal.py` | Edge/WebView2 同内核无头驱动：8 个布局场景 + 真实内核 iframe 挂载校验 + 截图；`diag_removal.py` 用于诊断删不掉的目录 |
| `tools/core-update-test/run_core_update.py` | 用启动器自身的更新管线在实例目录真机升级/降级 |
| `tools/core-update-test/test_launch_ladder.py` | 真实 CLI 的启动参数降级与记忆验证 |
| `tools/core-update-test/test_plugin_on_core.py` | 真实内核上的插件安装/列出/卸载验证 |

---

## 三、构建工具链（不在 git 中）

| 项目 | 内容 |
| --- | --- |
| 位置 | `tools/python-full/pkg/tools/python.exe`（可移植 CPython，不动系统环境、不写注册表） |
| 版本 | CPython **3.12.10** + pip 25.0.1 |
| 打包依赖 | `pyinstaller 6.22.2`、`pywebview 6.2.1`、`pyinstaller-hooks-contrib 2026.7`、`pythonnet 3.1.0`、`clr_loader 0.3.1`、`bottle 0.13.4`、`proxy_tools 0.1.0`、`PyYAML 6.0.3`、`setuptools 84.0.0`、`typing_extensions 4.16.0` |
| 冒烟验证 | PyInstaller 冻结「import webview + yaml」测试程序并成功运行；`_internal` 产出 `webview/pythonnet/clr_loader/yaml/setuptools`，与 1.0.4 包结构一致 |
| 与 1.0.4 差异 | 不再打入 `cryptography` / `bcrypt`（应用未引用；`app/crypto.py` 走 ctypes/DPAPI），包体更小 |
| 其它就绪 | `runtime/`（Node 24.16.0 + PortableGit 2.55.0）、`app/store/dshmarket-1.33.0.tgz`、`tools/7zip`（含 GUI SFX 模块）均在位 |

---

## 四、验证结论（已完成，全部可复跑）

| 测试 | 结果 |
| --- | --- |
| `tools/test-1.0.5.py`（含新工具链运行） | **98/98 通过** |
| `tools/immersive-check/`（Edge 153 无头） | **8/8 通过**；修复前退出全屏 iframe=980×150，修复后 980×622 |
| 真机升级 `0.1.1-rc.2 → 0.1.6-alpha.2` | 通过（备份回收、健康检查 exit 0、HTTP 200） |
| 真机降级 `0.1.6-alpha.2 → 0.1.1-rc.2` | 通过（裸地址 HTTP 200，旧内核无需 token） |
| 再升级回 `0.1.6-alpha.2` | 通过 |
| 启动梯度 / 插件路径（两个内核各一轮） | 10/10、8/8 |
| 最新内核鉴权对照 | 裸地址 → 401（界面无法使用）；token 地址 → 真实界面挂载（标题「DSH 本地构建」、`#root` 已挂载） |
| 随包内核（0.1.6-alpha.2）自检 | `--version` exit 0；`--profile web --dump-config` exit 0 |

---

## 五、待确认后执行的打包

```powershell
powershell -ExecutionPolicy Bypass -File scripts\make-release.ps1 -Version 1.0.5 -Flavor Lazy
powershell -ExecutionPolicy Bypass -File scripts\make-release.ps1 -Version 1.0.5 -Flavor Minimal
powershell -ExecutionPolicy Bypass -File scripts\smoke-release.ps1  -Version 1.0.5
powershell -ExecutionPolicy Bypass -File scripts\smoke-release.ps1  -Version 1.0.5 -Flavor Minimal
```

产物（`release/`）：`DeepSeekHarness-1.0.5-Setup.exe`、`-Update.exe`、`-Minimal-Setup.exe`、`-Minimal-Update.exe` + 各自 `.sha256` + `SHA256SUMS-1.0.5[-Minimal].txt`（参考 1.0.4：懒人包 ≈530MB、极简包 ≈447MB）。预计 45–90 分钟；磁盘余量 41.7GB。

## 六、上传前需要确认的网络与凭据

本机实测（当前时刻）：

| 目标 | 结果 |
| --- | --- |
| `api.github.com` | ✅ 可达（Release 创建、Git Data API 均返回 401“需认证”，说明路由可达） |
| `codeload.github.com`、`objects.githubusercontent.com` | ✅ 可达 |
| **`github.com`（git push、`uploads.github.com`）** | ❌ 连接超时（`20.205.243.166`，与网络环境有关；早前 `ls-remote` 曾成功一次，属间歇性） |

因此：

- **源码推送**：`git push` 走 github.com，当前不可用；可改用 **Git Data API**（api.github.com ✅）推送这 2 个提交与 `v1.0.5` 标签；
- **Release 资产（4 个安装包，约 2GB）**：官方上传域名 `uploads.github.com` 指向 github.com，当前不可用。可行方案：
  1. 换到能访问 github.com 的网络（或代理/VPN）后由本机上传；
  2. 由你在本机执行 `scripts\upload-release.ps1`（沿用 v1.0.3 的做法）；
  3. 等待网络恢复后重试（脚本内置重试与退避）。
- **凭据**：本机 `git credential fill` 非交互读取失败（`terminal prompts disabled`），因此脚本需要 `GITHUB_TOKEN`（或 `--token`）。若你确认 git 已登录且网络可用，可在能访问 github.com 的会话里直接执行上传命令。

> 结论：**打包可以随时开始**；上传建议在网络能访问 `github.com` 的环境执行，或提供 token 由我走 API 路径（源码+标签可走 API，安装包资产受 `uploads.github.com` 限制）。
