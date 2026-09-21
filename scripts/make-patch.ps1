# 生成 1.0.5 增量补丁包（release\DeepSeekHarness-1.0.5-Patch.zip）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\make-patch.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\make-patch.ps1 -Version 1.0.5 -SkipZip
#
# 补丁内容 = 已完成冒烟测试的 dist\DeepSeek Harness 里的“应用层”文件：
#   DeepSeek Harness.exe / _internal / ui / store\dshmarket-<ver>.tgz / post-update.bat
# 不含 core\（2.7GB 内核，实例已有）与 runtime\（便携 Node/Git，实例已有）。

param(
    [string]$Version = "1.0.5",
    [string]$Source = "",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Source) { $Source = Join-Path $root "dist\DeepSeek Harness" }
$dist = $Source
$patchDir = Join-Path $root "release\patch\DeepSeekHarness-$Version-Patch"
$payload = Join-Path $patchDir "payload"
$zipPath = Join-Path $root "release\DeepSeekHarness-$Version-Patch.zip"
$sevenZip = Join-Path $root "tools\7zip\7z.exe"

function Utf8NoBom([string]$path, [string]$text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $text, $enc)
}

Write-Host "=== 1. 检查来源构建 ===" -ForegroundColor Cyan
foreach ($item in @("DeepSeek Harness.exe", "_internal", "ui", "post-update.bat", "store")) {
    if (-not (Test-Path (Join-Path $dist $item))) { throw "来源缺少 $item：$dist（先运行 build.ps1）" }
}
$tgz = Get-ChildItem (Join-Path $dist "store") -Filter "dshmarket-*.tgz" -File
if ($tgz.Count -ne 1) { throw "store\ 里应恰好有 1 个 dshmarket-*.tgz，实际 $($tgz.Count) 个" }
$storeName = $tgz[0].Name
Write-Host "  来源：$dist"
Write-Host "  商店包：$storeName ($([math]::Round($tgz[0].Length/1MB,1)) MB)"

# post-update.bat 必须是严格 GBK + CRLF（cmd 解析前提）
$batRaw = [System.IO.File]::ReadAllBytes((Join-Path $dist "post-update.bat"))
if ($batRaw[0] -eq 0xEF -and $batRaw[1] -eq 0xBB) { throw "post-update.bat 带 BOM（cmd 会读成乱码）" }
$batText = [System.Text.Encoding]::GetEncoding(936).GetString($batRaw)
if ($batText.Contains([char]0xFFFD)) { throw "post-update.bat 含替换字符（cmd 会丢失行边界）" }
$crlf = ([regex]::Matches($batText, "`r`n")).Count
$lf = ([regex]::Matches($batText, "`n")).Count
if ($crlf -ne $lf) { throw "post-update.bat 不是全 CRLF（会破坏 cmd 解析）" }
Write-Host "  post-update.bat：GBK + CRLF OK（$crlf 行）" -ForegroundColor Green

Write-Host "=== 2. 组装补丁目录 ===" -ForegroundColor Cyan
if (Test-Path $patchDir) { Remove-Item -LiteralPath $patchDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $payload | Out-Null
Copy-Item -LiteralPath (Join-Path $dist "DeepSeek Harness.exe") -Destination $payload -Force
Copy-Item -LiteralPath (Join-Path $dist "post-update.bat") -Destination $payload -Force
robocopy (Join-Path $dist "_internal") (Join-Path $payload "_internal") /E /XJ /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "_internal 复制失败（$LASTEXITCODE）" }
robocopy (Join-Path $dist "ui") (Join-Path $payload "ui") /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "ui 复制失败（$LASTEXITCODE）" }
New-Item -ItemType Directory -Force -Path (Join-Path $payload "store") | Out-Null
Copy-Item -LiteralPath $tgz[0].FullName -Destination (Join-Path (Join-Path $payload "store") $storeName) -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "apply-patch.ps1") -Destination $patchDir -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "apply-patch.bat") -Destination (Join-Path $patchDir "应用补丁.bat") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "apply-patch.bat") -Destination (Join-Path $patchDir "应用补丁-自动关闭实例.bat") -Force
# 自动关闭实例的变体：启动参数里直接带 /stop
$autoBat = Join-Path $patchDir "应用补丁-自动关闭实例.bat"
$autoText = [System.Text.Encoding]::GetEncoding(936).GetString([System.IO.File]::ReadAllBytes($autoBat))
$autoText = $autoText -replace 'apply-patch\.ps1" %EXTRA%', 'apply-patch.ps1" -StopApp'
[System.IO.File]::WriteAllBytes($autoBat, [System.Text.Encoding]::GetEncoding(936).GetBytes($autoText))

Write-Host "=== 3. 生成 MANIFEST.sha256 ===" -ForegroundColor Cyan
$lines = New-Object System.Collections.Generic.List[string]
$files = Get-ChildItem -LiteralPath $payload -Recurse -File | Sort-Object FullName
foreach ($f in $files) {
    $rel = $f.FullName.Substring($payload.Length).TrimStart('\')
    $hash = (Get-FileHash -Algorithm SHA256 -Path $f.FullName).Hash.ToLower()
    $lines.Add("$hash  $rel")
}
Utf8NoBom (Join-Path $patchDir "MANIFEST.sha256") ($lines -join "`r`n")
$totalMb = [math]::Round((($files | Measure-Object -Sum Length).Sum) / 1MB, 1)
Write-Host "  $($files.Count) 个文件，$totalMb MB"

Write-Host "=== 4. 生成补丁说明 ===" -ForegroundColor Cyan
$exeHash = (Get-FileHash -Algorithm SHA256 -Path (Join-Path $payload "DeepSeek Harness.exe")).Hash.ToLower()
$storeHash = (Get-FileHash -Algorithm SHA256 -Path (Join-Path (Join-Path $payload "store") $storeName)).Hash.ToLower()
$notes = @"
# DeepSeek Harness for Windows $Version 增量补丁

**适用**：已安装 1.0.x 的实例（含内核 0.1.6-alpha.2 或可自行升级到该内核的实例）
**只更新应用层**：不动 `core\`（内核）与 `runtime\`（便携 Node / Git），也不动 `data\` 用户数据。
**构建来源**：`dist\DeepSeek Harness`（与 GitHub Release v$Version 的 4 个安装包同一份构建，已通过冒烟测试）

## 补丁做什么

| # | 内容 |
| --- | --- |
| 1 | 替换 `DeepSeek Harness.exe` 与 `_internal\`（**镜像**：旧版本多出来的文件会被删除，例如 `cryptography` / `bcrypt` / `python3.dll`，以及随旧包分发的示例外壳插件 `ui\plugins\*`） |
| 2 | 合并刷新外壳 UI（`ui\app.js` / `index.html` / `i18n.js` / `.version`）：随包文件更新，用户自己加的文件（如 `custom.css`）保留 |
| 3 | 替换 `post-update.bat`（严格 GBK + CRLF；新增升级期旧插件清理） |
| 4 | 随包商店插件 `dshmarket 1.33.0 → 1.50.0`，并删除旧的 `store\dshmarket-*.tgz` |
| 5 | 清理与新内核 0.1.6 不兼容的旧 dsh-web 插件：`@linxin666/dsh-web-ui-all`、`dsh-chat-recovery`、`dsh-desktop-launcher`、`dsh-perf`、`dsh-client-ui-aionui-panel`（先用随包 dsh CLI 卸载，再改 profile 清单——清单是离线也生效的最终依据） |
| 6 | 修正 `config.json` 的内置商店源：spec 指向 `store/$storeName`、修复乱码标签、`app_version = $Version` |

## 使用

1. 把 `DeepSeekHarness-$Version-Patch.zip` 解压到**任意位置**（例如桌面），或直接解压到安装目录内。
2. 双击 `应用补丁.bat`：
   * 若实例正在运行，它会提示先关闭应用（不会改动任何文件），或选择让它自动关闭；
   * 双击 `应用补丁-自动关闭实例.bat` 则直接关闭实例后打补丁。
3. 也可以命令行指定目录：

```
powershell -ExecutionPolicy Bypass -File apply-patch.ps1 -InstallDir "C:\DeepSeek Harness" -StopApp
powershell -ExecutionPolicy Bypass -File apply-patch.ps1 -InstallDir "C:\DeepSeek Harness" -DryRun
```

## 备份与回滚

补丁写入前会把 `DeepSeek Harness.exe`、`_internal\`、`ui\`、`store\`、`post-update.bat`、
`config.json` 与 profile 清单备份到 `<安装目录>\patch-backup-$Version-<时间戳>\`。
回滚：关闭应用，把备份目录里的内容拷回安装目录（覆盖），再启动应用即可。

## 校验

* 补丁内 `MANIFEST.sha256` 覆盖全部 payload 文件，应用脚本在最后逐个校验哈希；
* 关键哈希：
  * `DeepSeek Harness.exe` = `$exeHash`
  * `store\$storeName` = `$storeHash`
* 应用完成后脚本会检查：UI 版本、商店包、旧插件是否已从 profile 消失、旧商店包是否已删除。

## 说明

* 极简包（无 `runtime\`）同样适用；补丁不含运行时。
* 补丁不联网也能完成清单级清理；若本机有可用 Node，脚本还会额外执行一次
  `dsh plugin --profile web remove …` 把旧包文件真正卸载（失败不影响清单清理，启动器随后还会再清一次）。
"@
Utf8NoBom (Join-Path $patchDir "补丁说明.md") $notes

Write-Host "=== 5. 压缩 ===" -ForegroundColor Cyan
if ($SkipZip) {
    Write-Host "  已按 -SkipZip 跳过；补丁目录：$patchDir"
    return
}
if (-not (Test-Path $sevenZip)) { throw "缺少 7z.exe：$sevenZip" }
if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
& $sevenZip a -tzip -mx=9 -bso0 -bsp0 $zipPath (Join-Path $patchDir "*") | Out-Null
if ($LASTEXITCODE -ne 0) { throw "7z 压缩失败（$LASTEXITCODE）" }
$zipMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
$zipHash = (Get-FileHash -Algorithm SHA256 -Path $zipPath).Hash.ToLower()
Write-Host "  补丁包：$zipPath（$zipMb MB）" -ForegroundColor Green
Write-Host "  SHA256：$zipHash"
Utf8NoBom "$zipPath.sha256" "$zipHash  $(Split-Path -Leaf $zipPath)`r`n"
