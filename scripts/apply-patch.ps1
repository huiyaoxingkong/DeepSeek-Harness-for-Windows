# DeepSeek Harness for Windows — 1.0.5 增量补丁应用脚本
#
# 用途：把已安装的 1.0.x 实例更新到修复版 1.0.5（仅应用层，不动 core\ 与 runtime\）：
#   * 替换启动器 exe 与 _internal\（并删除旧版本多出来的文件，例如 cryptography /
#     bcrypt / python3.dll，以及随旧包分发的示例外壳插件 ui\plugins\*）；
#   * 刷新外壳 UI（合并式：随包文件更新，用户自己加的文件保留）；
#   * 替换 post-update.bat（GBK + CRLF + 旧插件清理逻辑）；
#   * 随包商店插件 dshmarket 1.33.0 → 1.50.0，并删除旧的 dshmarket-*.tgz；
#   * 修正 config.json 的商店源（spec 指向 1.50.0、修复乱码标签）；
#   * 清理与新内核（0.1.6）不兼容的旧 dsh-web 插件：先用随包 dsh CLI 卸载（此时清单未改，
#     命令有效），再改 profile 清单（离线也生效，是内核是否加载插件的最终依据）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File apply-patch.ps1                 # 自动找安装目录，检查是否在运行
#   powershell -ExecutionPolicy Bypass -File apply-patch.ps1 -StopApp        # 先关闭实例再打补丁
#   powershell -ExecutionPolicy Bypass -File apply-patch.ps1 -DryRun         # 只报告将要做的改动
#   powershell -ExecutionPolicy Bypass -File apply-patch.ps1 -InstallDir "D:\DeepSeek Harness" -StopApp -NoRestart
#
# 备份：<安装目录>\patch-backup-<版本>-<时间戳>\（exe、_internal、ui、store、
#       post-update.bat、config.json、profile 清单）。回滚 = 把备份内容拷回原位。

param(
    [string]$InstallDir = "",
    [switch]$StopApp,
    [switch]$NoRestart,
    [switch]$DryRun,
    [switch]$RemoveStaleInstallers
)

$ErrorActionPreference = "Stop"
$PatchRoot = $PSScriptRoot
$Payload = Join-Path $PatchRoot "payload"
$Version = "1.0.5"

# 与新内核 0.1.6 不兼容、需要从 profile 中移除的旧 dsh-web 包
$RetiredPlugins = @(
    "@linxin666/dsh-web-ui-all",
    "@linxin666/dsh-chat-recovery",
    "@linxin666/dsh-desktop-launcher",
    "@linxin666/dsh-perf",
    "@linxin666/dsh-client-ui-aionui-panel"
)
$StoreLabel = "dshmarket 插件商店"

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }
function Ok([string]$text) { Write-Host "  [OK]   $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "  [WARN] $text" -ForegroundColor Yellow }
function Fail([string]$text) { Write-Host "  [FAIL] $text" -ForegroundColor Red }

function Resolve-InstallDir([string]$given) {
    if ($given) {
        if (Test-Path (Join-Path $given "DeepSeek Harness.exe")) { return (Resolve-Path $given).Path }
        throw "指定的安装目录里没有 DeepSeek Harness.exe：$given"
    }
    $candidates = @()
    # 补丁放在安装目录内时（常见做法）：上一级就是安装目录
    $candidates += (Split-Path -Parent $PatchRoot)
    $candidates += "C:\DeepSeek Harness"
    $candidates += (Join-Path $env:ProgramFiles "DeepSeek Harness")
    $candidates += "D:\DeepSeek Harness"
    if ($env:USERPROFILE) {
        $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "DeepSeek Harness.lnk"
        if (Test-Path $lnk) {
            try {
                $sh = New-Object -ComObject WScript.Shell
                $target = $sh.CreateShortcut($lnk).TargetPath
                if ($target) { $candidates += (Split-Path -Parent $target) }
            } catch { }
        }
    }
    foreach ($c in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-Path (Join-Path $c "DeepSeek Harness.exe")) { return (Resolve-Path $c).Path }
    }
    throw "未找到安装目录。请用 -InstallDir 指定（例如 -InstallDir `"C:\DeepSeek Harness`"）。"
}

function Get-InstanceExePids([string]$dir) {
    # 只认“这个安装目录里的”启动器进程：多实例机器上，别的实例在运行与本补丁无关，
    # 既不该阻止打补丁，也绝不能被本补丁关掉。
    $pids = @()
    $dirNorm = [System.IO.Path]::GetFullPath($dir).TrimEnd('\')
    foreach ($p in (Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue)) {
        $path = $null
        try { $path = $p.Path } catch { }
        if (-not $path) { continue }
        try {
            $parent = [System.IO.Path]::GetFullPath((Split-Path -Parent $path)).TrimEnd('\')
            if ($parent -eq $dirNorm) { $pids += $p.Id }
        } catch { }
    }
    return $pids
}

function Get-InstanceCorePids([string]$dir) {
    # 与 stop-core.ps1 相同的判定：命令行里出现 <core>\apps\cli\lib\bin.js
    $coreF = [WildcardPattern]::Escape(((Join-Path $dir "core") -replace '\\', '/'))
    $coreB = [WildcardPattern]::Escape((Join-Path $dir "core"))
    try {
        $nodes = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $cl = $_.CommandLine
                $cl -and (($cl -like "*$coreF*apps/cli/lib/bin.js*") -or ($cl -like "*$coreB*apps\cli\lib\bin.js*"))
            }
        return @($nodes | ForEach-Object { $_.ProcessId })
    } catch { return @() }
}

function Get-InstanceProcesses([string]$dir) {
    $found = @()
    foreach ($id in (Get-InstanceExePids $dir)) { $found += "DeepSeek Harness.exe (pid $id)" }
    foreach ($id in (Get-InstanceCorePids $dir)) { $found += "core node (pid $id)" }
    return $found
}

function Stop-Instance([string]$dir) {
    $stopper = Join-Path $dir "stop-core.ps1"
    if (Test-Path $stopper) {
        Say "  调用 stop-core.ps1 关闭本实例内核…"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $stopper -CoreDir (Join-Path $dir "core") | Out-Null
    }
    foreach ($id in (Get-InstanceExePids $dir)) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if ((Get-InstanceProcesses $dir).Count -eq 0) { break }
        Start-Sleep -Milliseconds 500
    }
    return ((Get-InstanceProcesses $dir).Count -eq 0)
}

function Test-Hash([string]$path, [string]$expected) {
    if (-not (Test-Path $path)) { return $false }
    $actual = (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLower()
    return ($actual -eq $expected.ToLower())
}

function Write-JsonFile([string]$path, $object) {
    $text = $object | ConvertTo-Json -Depth 16
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $text, $enc)
}

function Invoke-PluginRemove([string]$dir, [string]$dshHome) {
    $bin = Join-Path $dir "core\apps\cli\lib\bin.js"
    if (-not (Test-Path $bin)) { return @{ ran = $false; reason = "core CLI 不存在" } }
    $node = Join-Path $dir "runtime\node.exe"
    if (-not (Test-Path $node)) { $node = "node" }
    $env:DSH_HOME = $dshHome
    $env:PNPM_HOME = (Join-Path $dir "data")
    Remove-Item Env:CI -ErrorAction SilentlyContinue
    Remove-Item Env:ci -ErrorAction SilentlyContinue
    Remove-Item Env:npm_config_frozen_lockfile -ErrorAction SilentlyContinue
    # 只把清单里确实存在的包交给 CLI：pnpm remove 只要有一个名字不是依赖就会整体失败
    # （ERR_PNPM_CANNOT_REMOVE_MISSING_DEPS，真机实测），旧 preset 装过的包未必全在。
    $present = @()
    $manifestPath = Join-Path $dshHome "profiles\web\package.json"
    if (Test-Path $manifestPath) {
        try {
            $manifest = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
            $depNames = @()
            if ($manifest.dependencies) { $depNames = @($manifest.dependencies.PSObject.Properties.Name) }
            foreach ($name in $RetiredPlugins) { if ($depNames -contains $name) { $present += $name } }
        } catch { }
    }
    if ($present.Count -eq 0) { return @{ ran = $false; reason = "profile 清单里没有已安装的旧插件" } }
    $cliArgs = @("plugin", "--profile", "web", "remove") + $present
    # -ArgumentList 只是把元素用空格拼起来，不做引号处理：安装目录（默认就是
    # "C:\DeepSeek Harness"）含空格时 node 会把脚本路径拆成两段而报
    # "Cannot find module …\DeepSeek"。这里自己给带空格的参数加引号。
    $quoted = @()
    foreach ($a in (@($bin) + $cliArgs)) {
        if ($a -match '\s') { $quoted += ('"' + $a + '"') } else { $quoted += $a }
    }
    Say "  用随包 dsh CLI 卸载旧插件（最多等 15 分钟）…"
    $proc = Start-Process -FilePath $node -ArgumentList ($quoted -join ' ') -WorkingDirectory $dir -NoNewWindow -PassThru
    $timedOut = $false
    try { $proc | Wait-Process -Timeout 900 -ErrorAction Stop } catch { $timedOut = $true }
    if ($timedOut -or -not $proc.HasExited) {
        & taskkill /F /T /PID $proc.Id | Out-Null
        return @{ ran = $true; code = -1; reason = "超时，已杀进程树" }
    }
    return @{ ran = $true; code = $proc.ExitCode; reason = "" }
}

function Update-ProfileManifest([string]$dshHome, [string]$storeTgz) {
    $manifestPath = Join-Path $dshHome "profiles\web\package.json"
    if (-not (Test-Path $manifestPath)) { return @{ changed = $false; reason = "无 web profile" } }
    $json = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
    $changed = $false
    $removedDeps = @()
    $removedBundles = @()
    if ($json.dependencies) {
        foreach ($name in $RetiredPlugins) {
            if ($json.dependencies.PSObject.Properties.Name -contains $name) {
                $json.dependencies.PSObject.Properties.Remove($name)
                $removedDeps += $name
                $changed = $true
            }
        }
        if ($json.dependencies.PSObject.Properties.Name -contains "dshmarket") {
            $want = "file:" + $storeTgz
            $have = [string]$json.dependencies.dshmarket
            $haveNorm = $have -replace '/', '\'
            if ($haveNorm -ne $want) {
                $json.dependencies.dshmarket = $want
                $changed = $true
            }
        }
    }
    $profile = $null
    if ($json.dsh -and $json.dsh.profile) { $profile = $json.dsh.profile }
    if ($profile -and $profile.bundles) {
        $kept = @()
        foreach ($entry in @($profile.bundles)) {
            if ($RetiredPlugins -contains [string]$entry) { $removedBundles += [string]$entry; $changed = $true }
            else { $kept += $entry }
        }
        if ($changed) { $profile.bundles = $kept }
    }
    if ($changed) { Write-JsonFile $manifestPath $json }
    return @{ changed = $changed; deps = $removedDeps; bundles = $removedBundles }
}

function Update-Config([string]$dir, [string]$storeSpec) {
    $cfgPath = Join-Path $dir "config.json"
    if (-not (Test-Path $cfgPath)) { return @{ changed = $false; reason = "无 config.json" } }
    $cfg = [System.IO.File]::ReadAllText($cfgPath) | ConvertFrom-Json
    $changed = $false
    foreach ($src in @($cfg.store_sources)) {
        if (-not $src) { continue }
        if ($src.name -eq "dshmarket") {
            if ([string]$src.spec -ne $storeSpec) { $src.spec = $storeSpec; $changed = $true }
            if ([string]$src.label -ne $StoreLabel) { $src.label = $StoreLabel; $changed = $true }
        }
    }
    if ($cfg.app_version -ne $Version) { $cfg.app_version = $Version; $changed = $true }
    if ($changed) { Write-JsonFile $cfgPath $cfg }
    return @{ changed = $changed }
}

# ------------------------------------------------------------------ main

Say "=== DeepSeek Harness $Version 增量补丁 ===" Cyan
if (-not (Test-Path $Payload)) { throw "补丁不完整：缺少 payload\ 目录（请重新解压）" }

$install = Resolve-InstallDir $InstallDir
Say "安装目录：$install"
if (-not (Test-Path (Join-Path $install "_internal"))) { Warn "_internal\ 不存在（极简包？）——将按 payload 全量写入" }

$running = Get-InstanceProcesses $install
if ($running.Count -gt 0) {
    if (-not $StopApp) {
        Fail "实例正在运行：$($running -join '、')"
        Say "  请先确认页面已保存，然后重新运行并加上 -StopApp（或双击 应用补丁.bat 选择关闭），"
        Say "  也可以在应用里「关闭应用」后再执行本补丁。"
        exit 2
    }
    Say "=== 1. 关闭实例 ===" Cyan
    if (Stop-Instance $install) { Ok "实例已停止" } else { throw "实例仍在运行，补丁中止（未改动任何文件）" }
} else {
    Say "=== 1. 实例未在运行 ===" Cyan
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $install "patch-backup-$Version-$stamp"
$storeTgz = (Get-ChildItem (Join-Path $Payload "store") -Filter "dshmarket-*.tgz" -File |
             Select-Object -First 1)
if (-not $storeTgz) { throw "payload\store 里没有 dshmarket-*.tgz" }
$storeFileName = $storeTgz.Name
$storeSpec = "store/" + $storeFileName

Say "=== 2. 备份到 $backup ===" Cyan
if ($DryRun) {
    Say "  [DryRun] 将备份 exe / _internal / ui / store / post-update.bat / config.json / profile 清单"
} else {
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach ($item in @("DeepSeek Harness.exe", "_internal", "ui", "store", "post-update.bat", "config.json")) {
        $src = Join-Path $install $item
        if (Test-Path $src) {
            Copy-Item -LiteralPath $src -Destination $backup -Recurse -Force
        }
    }
    $profilePath = Join-Path $install "data\.dsh\profiles\web\package.json"
    if (Test-Path $profilePath) {
        New-Item -ItemType Directory -Force -Path (Join-Path $backup "profile") | Out-Null
        Copy-Item -LiteralPath $profilePath -Destination (Join-Path $backup "profile\package.json") -Force
    }
    Ok "备份完成：$backup"
}

Say "=== 3. 应用应用层文件 ===" Cyan
if ($DryRun) {
    Say "  [DryRun] 将镜像 payload\_internal 到安装目录的 _internal（删除旧版多余文件）、"
    Say "           覆盖 exe / ui / post-update.bat、写入 $storeFileName"
} else {
    # _internal 必须“镜像”而不是“合并”：旧版本多出来的文件（cryptography / bcrypt /
    # python3.dll / 示例外壳插件）留着会被一起加载。
    $srcInt = Join-Path $Payload "_internal"
    if (Test-Path $srcInt) {
        $dstInt = Join-Path $install "_internal"
        robocopy $srcInt $dstInt /MIR /XJ /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
        if ($LASTEXITCODE -gt 7) { throw "_internal 同步失败（robocopy 退出码 $LASTEXITCODE）" }
        Ok "_internal 已镜像（多余文件已删除）"
    }
    foreach ($file in @("DeepSeek Harness.exe", "post-update.bat")) {
        $src = Join-Path $Payload $file
        if (Test-Path $src) {
            Copy-Item -LiteralPath $src -Destination (Join-Path $install $file) -Force
            Ok "已更新 $file"
        }
    }
    $srcUi = Join-Path $Payload "ui"
    if (Test-Path $srcUi) {
        robocopy $srcUi (Join-Path $install "ui") /E /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
        if ($LASTEXITCODE -gt 7) { throw "ui 合并刷新失败（robocopy 退出码 $LASTEXITCODE）" }
        Ok "外壳 UI 已合并刷新（用户自己加的文件保留）"
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $install "store") | Out-Null
    Copy-Item -LiteralPath $storeTgz.FullName -Destination (Join-Path (Join-Path $install "store") $storeFileName) -Force
    Ok "已写入 store\$storeFileName"
    Get-ChildItem (Join-Path $install "store") -Filter "dshmarket-*.tgz" -File |
        Where-Object { $_.Name -ne $storeFileName } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Ok "已删除旧商店包 $($_.Name)" }
}

Say "=== 4. 清理与新内核不兼容的旧插件 ===" Cyan
$dshHome = Join-Path $install "data\.dsh"
if (-not (Test-Path (Join-Path $dshHome "profiles\web\package.json"))) {
    Warn "没有 web profile（全新实例），跳过插件清理"
} elseif ($DryRun) {
    Say "  [DryRun] 将执行 dsh plugin remove 并清理 profile 清单"
} else {
    $cli = Invoke-PluginRemove $install $dshHome
    if ($cli.ran -and $cli.code -eq 0) { Ok "dsh CLI 卸载成功" }
    elseif ($cli.ran) { Warn "dsh CLI 卸载未成功（$($cli.reason)$($cli.code)）——清单清理仍会执行" }
    else { Warn "跳过 CLI 卸载：$($cli.reason)" }
    $m = Update-ProfileManifest $dshHome (Join-Path (Join-Path $install "store") $storeFileName)
    if ($m.changed) {
        Ok ("profile 清单已清理：deps=" + ($(if ($m.deps.Count) { $m.deps -join ',' } else { '无' })) `
            + " bundles=" + ($(if ($m.bundles.Count) { $m.bundles -join ',' } else { '无' })))
    } elseif ($m.reason) { Warn "profile 未改动：$($m.reason)" }
    else { Ok "profile 清单无需改动" }
}

Say "=== 5. 修正 config.json ===" Cyan
if ($DryRun) {
    Say "  [DryRun] 将把内置商店源 spec 改为 $storeSpec、修复标签与 app_version"
} else {
    $c = Update-Config $install $storeSpec
    if ($c.changed) { Ok "config.json 已更新（spec=$storeSpec）" } else { Ok "config.json 无需改动" }
}

Say "=== 6. 校验 ===" Cyan
$problems = 0
$manifestFile = Join-Path $PatchRoot "MANIFEST.sha256"
if (Test-Path $manifestFile) {
    $bad = @()
    foreach ($line in Get-Content $manifestFile) {
        if (-not $line.Trim()) { continue }
        $parts = $line -split '\s+', 2
        if ($parts.Count -lt 2) { continue }
        $rel = $parts[1].Trim()
        $target = Join-Path $install ($rel -replace '^payload[\\/]', '')
        if (-not (Test-Hash $target $parts[0])) { $bad += $rel }
    }
    if ($bad.Count -eq 0) { Ok "全部 payload 文件哈希与补丁清单一致" }
    else { Fail "以下文件哈希不一致：$($bad -join ', ')"; $problems++ }
} else { Warn "补丁内没有 MANIFEST.sha256，跳过哈希校验" }

$uiVersion = Join-Path $install "ui\.version"
if ((Test-Path $uiVersion) -and ((Get-Content $uiVersion -Raw).Trim() -eq $Version)) { Ok "ui\.version = $Version" }
else { Fail "ui\.version 不是 $Version"; $problems++ }

if (Test-Path (Join-Path $install "store\$storeFileName")) { Ok "随包商店包 $storeFileName 已就位" }
else { Fail "随包商店包缺失"; $problems++ }

$leftover = @()
foreach ($name in $RetiredPlugins) {
    $manifestPath = Join-Path $dshHome "profiles\web\package.json"
    if (Test-Path $manifestPath) {
        $text = [System.IO.File]::ReadAllText($manifestPath)
        if ($text -like "*$name*") { $leftover += $name }
    }
}
if ($leftover.Count -eq 0) { Ok "profile 中已无旧版 dsh-web 插件" }
else { Warn "profile 清单仍含：$($leftover -join ', ')（启动器还会再清理一次）" }

$oldTgz = Get-ChildItem (Join-Path $install "store") -Filter "dshmarket-*.tgz" -File |
    Where-Object { $_.Name -ne $storeFileName }
if (-not $oldTgz) { Ok "store\ 中只有当前商店包" } else { Warn "store\ 仍有：$(($oldTgz | ForEach-Object { $_.Name }) -join ', ')" }

if ($RemoveStaleInstallers) {
    Get-ChildItem $install -Filter "DeepSeekHarness-*-*.exe" -File |
        Where-Object { $_.Length -gt 50MB } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Ok "已删除遗留安装包 $($_.Name)" }
}

Say ""
if ($problems -gt 0) {
    Fail "补丁应用完成，但有 $problems 项校验未通过；可用备份目录回滚：$backup"
} else {
    Ok "补丁应用完成（备份：$backup）"
}
if ($DryRun) { Say "（DryRun：未改动任何文件）" Yellow }

if (-not $NoRestart) {
    $exe = Join-Path $install "DeepSeek Harness.exe"
    if (Test-Path $exe) {
        Say "正在启动 DeepSeek Harness…" Cyan
        Start-Process -FilePath $exe -WorkingDirectory $install
    }
} else {
    Say "已按 -NoRestart 跳过启动；请手动双击「DeepSeek Harness.exe」。" Cyan
}
exit $(if ($problems -gt 0) { 1 } else { 0 })
