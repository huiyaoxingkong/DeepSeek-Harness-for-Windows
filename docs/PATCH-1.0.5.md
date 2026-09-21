# 1.0.5 增量补丁（为已安装实例制作）

**补丁包**：`release/DeepSeekHarness-1.0.5-Patch.zip`（约 14.5 MB，含 `SHA256` 文件）
**适用对象**：已安装的 1.0.x 实例（本机就是 `D:\Agent-windows\DeepSeekHarness`）
**不包含**：`core\`（约 2.7 GB 内核）与 `runtime\`（便携 Node / Git）——实例已有，补丁只更新应用层。

## 为什么需要补丁

1.0.5 的四个安装包（455.7 / 371 MB）是**全量**升级：对已经装好内核的实例来说，重新下载
450 MB 只为替换 ~30 MB 的应用层文件。本补丁把这一层单独打出来，用于：

* 把正在用的实例升级到**修复版 1.0.5**（旧版 dsh-web 插件清理、商店包 1.50.0、UI 修复、
  卡死点加固）；
* 在不同机器/实例上复现同一份修复，而无需重新下载内核。

补丁内容与 GitHub Release v1.0.5 的四个安装包**同源**（`dist\DeepSeek Harness`，已通过
`smoke-release.ps1` 冒烟），并由 `MANIFEST.sha256` 逐文件校验。

## 补丁做什么

| # | 动作 | 说明 |
| --- | --- | --- |
| 1 | 替换 `DeepSeek Harness.exe` + `_internal\` | **镜像**同步：旧版多出来的文件会被删除，例如 `cryptography` / `bcrypt` / `python3.dll`，以及旧包随附的示例外壳插件 `ui\plugins\*` |
| 2 | 合并刷新外壳 UI | `app.js` / `index.html` / `i18n.js` / `.version` 更新；用户自加文件（`custom.css` 等）保留 |
| 3 | 替换 `post-update.bat` | 严格 GBK + CRLF，含升级期旧插件清理 |
| 4 | 商店包 1.33.0 → 1.50.0 | 写入 `store\dshmarket-1.50.0.tgz`，删除 `dshmarket-1.21.4.tgz` / `1.33.0.tgz` |
| 5 | 清理旧 dsh-web 插件 | `@linxin666/dsh-web-ui-all`、`dsh-chat-recovery`、`dsh-desktop-launcher`、`dsh-perf`、`dsh-client-ui-aionui-panel`：先让随包 dsh CLI 卸载（只传清单里确实存在的名字），再改 profile 清单（离线也生效） |
| 6 | 修正 `config.json` | 商店源 spec → `store/dshmarket-1.50.0.tgz`、修复乱码标签、`app_version = 1.0.5`；其它配置（端口、主题、语言、引导状态）原样保留 |

## 使用

```
# 1) 解压补丁
Expand-Archive release\DeepSeekHarness-1.0.5-Patch.zip -DestinationPath C:\patch

# 2) 关掉要打补丁的实例后运行（或用 -StopApp 让补丁自己关）
powershell -ExecutionPolicy Bypass -File C:\patch\apply-patch.ps1 -InstallDir "D:\Agent-windows\DeepSeekHarness"
powershell -ExecutionPolicy Bypass -File C:\patch\apply-patch.ps1 -InstallDir "..." -StopApp   # 自动关闭实例
powershell -ExecutionPolicy Bypass -File C:\patch\apply-patch.ps1 -InstallDir "..." -DryRun    # 只看会改什么
```

也可以直接双击补丁目录里的 `应用补丁.bat`（会询问是否自动关闭实例），或
`应用补丁-自动关闭实例.bat`。补丁**只认 `-InstallDir` 指向的那个实例**：别的实例在运行
既不会阻止打补丁，也绝不会被本补丁关掉。

## 备份与回滚

写入前把 `DeepSeek Harness.exe`、`_internal\`、`ui\`、`store\`、`post-update.bat`、
`config.json`、profile 清单复制到 `<安装目录>\patch-backup-1.0.5-<时间戳>\`。
回滚：关闭应用 → 把备份内容拷回安装目录覆盖 → 启动。

## 验收

`scripts\test-patch.ps1` 会把补丁应用到一个**真实实例的副本**（不触碰运行中的实例）并逐项校验，
两个场景全部通过（39 项）：

| 场景 | 校验点 |
| --- | --- |
| A 离线（无 core CLI） | exe/_internal 完全镜像、旧依赖与示例插件被删、UI 合并且用户文件保留、`ui\.version`、store 只剩 1.50.0、config spec/标签/版本、profile 依赖移除与 dshmarket 重指向、内核 bundle 保留、备份完整、`-DryRun` 不改动文件、重复应用幂等 |
| B CLI（core/runtime 以 junction 指向真实构建） | `dsh plugin --profile web remove …` 执行成功，旧包文件与清单条目都被移除，测试用 junction 已清理、真实 core 未被改动 |

```
powershell -ExecutionPolicy Bypass -File scripts\test-patch.ps1
# PATCH TEST: ALL PASS
```

构建与校验命令：

```
powershell -ExecutionPolicy Bypass -File scripts\make-patch.ps1 -Version 1.0.5   # 生成 zip + MANIFEST
python scripts\fix-script-encodings.py --check                                   # 脚本编码不变量
```

## 已知边界

* 补丁不改内核：实例内核需已是 0.1.6-alpha.2（或用户自行升级）。若内核更旧，请用
  「核心更新」页或 `-Update.exe` 全量升级。
* 补丁不联网也能完成清单级清理；只有 Node/pnpm 可用时才会真正删除 `node_modules` 里的旧包
  （失败不影响清单清理，启动器随后还会再清一次）。
* 极简包（无 `runtime\`）同样适用。
