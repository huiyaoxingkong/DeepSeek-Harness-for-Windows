# DeepSeek Harness Desktop

将 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）
封装为 Windows 桌面应用：

- **exe 启动器**（`DeepSeek Harness.exe`）：WebView2 窗口 + 本地 Web UI（工作台 / 插件 / 设置 / 核心更新 / 日志）
- **新手引导**：首次启动分步引导（工作台 / API Key / 插件与更新）
- **核心可更新**：一键从 GitHub 官方源码（master 分支）下载 → `pnpm install` → `pnpm build` → 原子切换，失败自动回退
- **插件管理**：安装 / 卸载 / 启用 / 停用插件（npm 包、git 仓库、本地路径）
- **独立可换肤 UI**：外壳界面是纯 HTML/CSS/JS，直接编辑文件即可自定义
- **内置 Node.js 运行时**：无需在系统安装 Node.js

## 版本 1.0.0 发行包

`dist\DeepSeekHarness-1.0.0-Setup.exe`（约 213 MB）——自解压安装包：

- 双击运行，选择安装目录（默认 `C:\DeepSeek Harness`）
- 自动重建工作区链接（约 10 秒）、创建桌面快捷方式并启动应用
- 首次启动显示新手引导
- SHA256：`3735B4CB9E962CD62331110E804B0BAFCED59F85C9A8A8E4FEA50974E2701DB3`

## 目录结构

```
deepseek_harness/
├── build.ps1                 # 一键构建脚本
├── app/                      # Python 启动器源码（exe 本体）
│   ├── main.py               # 入口（pywebview 窗口）
│   ├── core_api.py           # dsh 服务器子进程管理 + 孤儿进程清理
│   ├── updater.py            # GitHub 源码下载 / 构建 / 原子切换
│   ├── settings.py           # config.json 读写
│   ├── ui_server.py          # 外壳 UI 的本地 HTTP 服务（127.0.0.1 随机端口）
│   ├── relink.py             # NTFS junction 重链接（pnpm 链接迁移）
│   └── ui/                   # ★ 外壳 UI（可编辑）
│       ├── index.html
│       ├── style.css         # 主题由文件顶部 CSS 变量控制
│       └── app.js            # 与 Python 桥通信逻辑
├── scripts/
│   ├── install-node.ps1      # 下载便携版 Node.js 到 runtime/
│   ├── build-core.ps1        # 构建核心（git init + pnpm install + pnpm build）
│   ├── write-core-info.py    # 记录上游 commit 信息
│   └── relink.py             # 构建期 junction 重链接
├── core/                     # deepseek-harness 源码（构建产物，可由应用更新）
├── runtime/                  # 便携 Node.js（node.exe + corepack + pnpm 垫片）
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
3. 「插件」页可安装/卸载/启用/停用插件（dsh 插件化架构：插件为 profile 依赖，声明 `dsh.bundle` 的加入层栈）。
4. 「核心更新」页可检查 GitHub 上的最新源码并一键更新核心（更新前请先停止服务器）。

## 插件管理

「插件」页面提供 dsh profile（`~/.dsh/profiles/web`）的插件管理：

- **安装**：支持 npm 包名（`pnpm add`）、git 仓库、本地路径；操作实时输出，安装前自动停止服务器
- **卸载**：从 profile 依赖移除
- **启用/停用**：加入/移出 `dsh.profile.bundles` 层栈（包保留在 node_modules，重启后生效）
- **列表**：区分 内置层（dsh-base 等，不可卸载）/ 已启用 / 已停用 / 普通依赖

插件操作走 dsh 官方机制（`dsh plugin --profile web <add|remove>`），由 dsh 自动调和 bundle 层。

配置文件 `config.json` 字段：

```json
{
  "api_key": "",          // DeepSeek API Key（或从设置页填写）
  "base_url": "",         // 可选，API Base URL
  "port": 3080,           // dsh Web 端口
  "auto_start": false,    // 启动应用时自动启动服务器
  "open_browser": false,  // 启动服务器时同时打开系统浏览器
  "core_dir": "core",
  "runtime_dir": "runtime"
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
  `restart_server`、`read_log`、`check_update`、`download_update`、`cancel_update`

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
- 更新需要网络（GitHub + npm registry）
- 首次构建核心约需 10 分钟（依赖安装 + 编译），后续更新利用 pnpm 缓存会快很多
