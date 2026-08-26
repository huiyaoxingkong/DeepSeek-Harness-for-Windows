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
  dsh-plugin-manager / dsh-desktop-launcher 等需要调用 dsh CLI 的插件可用），
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
      "spec": "store/dshmarket-1.21.4.tgz", // 相对应用目录的本地包路径
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
