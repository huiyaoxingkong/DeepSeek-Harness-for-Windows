# 增量补丁验收测试：把 release\patch\DeepSeekHarness-<ver>-Patch 应用到一个
# 真实实例的“副本”上，逐项校验，不触碰正在运行的实例。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\test-patch.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\test-patch.ps1 -LiveInstance "C:\DeepSeek Harness"
#   powershell -ExecutionPolicy Bypass -File scripts\test-patch.ps1 -PatchZip release\DeepSeekHarness-1.0.5-Patch.zip
#
# 两个场景：
#   A 离线场景：无 core CLI —— 校验文件镜像/UI 合并/商店包/配置/清单清理/备份/幂等/DryRun；
#   B CLI 场景：core 与 runtime 用 junction 指向真实构建 —— 校验
#     `dsh plugin --profile web remove …` 真的把旧包卸载掉。
param(
    [string]$PatchZip = "",
    [string]$LiveInstance = "D:\Agent-windows\DeepSeekHarness",
    [string]$Version = "1.0.5",
    [switch]$Keep
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist\DeepSeek Harness"
$python = Join-Path $root "tools\python-full\pkg\tools\python.exe"
$sevenZip = Join-Path $root "tools\7zip\7z.exe"
$scratchRoot = Join-Path $root ".tmp-patch-test"
$scratch = Join-Path $scratchRoot "DeepSeek Harness"
# 解压目录必须在 scratchRoot 之外：场景 A 开始时会整体清理 scratchRoot
$extractRoot = Join-Path $root ".tmp-patch-extract"
$fail = 0

function Check([string]$name, [bool]$ok, [string]$detail = "") {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor Green }
    else { Write-Host "  FAIL  $name  -- $detail" -ForegroundColor Red; $script:fail++ }
}
function HashOf([string]$p) {
    if (Test-Path -LiteralPath $p) { (Get-FileHash -Algorithm SHA256 -Path $p).Hash.ToLower() } else { "missing" }
}
function Remove-Scratch([string]$path) {
    # 用启动器自带的长路径安全删除：pnpm 生成的路径普遍超过 MAX_PATH
    if (-not (Test-Path $path)) { return }
    & $python -c "import sys; sys.path.insert(0, sys.argv[1]); import homes; homes.remove_tree(sys.argv[2])" `
        (Join-Path $root "app") $path | Out-Null
}

# ---------------------------------------------------------------- 0. 定位补丁
if ($PatchZip) {
    $extract = $extractRoot
    Remove-Scratch $extract
    New-Item -ItemType Directory -Force -Path $extract | Out-Null
    & $sevenZip x $PatchZip "-o$extract" -y -bso0 -bsp0 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "解压补丁失败（$LASTEXITCODE）" }
    $patch = $extract
} else {
    $patch = Join-Path $root "release\patch\DeepSeekHarness-$Version-Patch"
    if (-not (Test-Path (Join-Path $patch "payload"))) {
        Write-Host "补丁目录不存在，先运行 make-patch.ps1 -SkipZip" -ForegroundColor Yellow
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "make-patch.ps1") -Version $Version -SkipZip | Out-Null
    }
}
$payload = Join-Path $patch "payload"
Write-Host "补丁：$patch" -ForegroundColor Cyan
Check "补丁含 payload 与 MANIFEST" ((Test-Path $payload) -and (Test-Path (Join-Path $patch "MANIFEST.sha256"))) $patch
Check "补丁含 apply-patch.ps1 与双击入口" ((Test-Path (Join-Path $patch "apply-patch.ps1")) -and (Test-Path (Join-Path $patch "应用补丁.bat")))
Check "补丁不含 core / runtime / data" ((-not (Test-Path (Join-Path $payload "core"))) -and (-not (Test-Path (Join-Path $payload "runtime"))) -and (-not (Test-Path (Join-Path $payload "data"))))

# ---------------------------------------------------------------- 1. 副本
Write-Host "=== A. 离线场景（真实实例副本，无 core CLI） ===" -ForegroundColor Cyan
Remove-Scratch $scratchRoot
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$source = if (Test-Path (Join-Path $LiveInstance "DeepSeek Harness.exe")) { $LiveInstance } else { $dist }
Write-Host "  复制自：$source"
foreach ($item in @("DeepSeek Harness.exe", "_internal", "ui", "store", "post-update.bat", "post-install.bat",
                    "config.json", "stop-core.ps1", "cacert.pem", "dsh.ico")) {
    if (Test-Path (Join-Path $source $item)) { Copy-Item -LiteralPath (Join-Path $source $item) -Destination $scratch -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path (Join-Path $scratch "scripts") | Out-Null
Copy-Item -LiteralPath (Join-Path $source "scripts\restore-junctions.ps1") -Destination (Join-Path $scratch "scripts") -Force

$profileDir = Join-Path $scratch "data\.dsh\profiles\web"
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
$liveManifest = Join-Path $LiveInstance "data\.dsh\profiles\web\package.json"
if (Test-Path $liveManifest) {
    Copy-Item -LiteralPath $liveManifest -Destination $profileDir -Force
} else {
    $seed = [ordered]@{
        name = "dsh-profile-web"; private = $true
        dependencies = [ordered]@{ dshmarket = "file:" + (Join-Path $scratch "store\dshmarket-1.33.0.tgz")
                                   "@linxin666/dsh-web-ui-all" = "0.3.2" }
        dsh = @{ profile = @{ bundles = @("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "dshmarket", "@linxin666/dsh-web-ui-all") } }
    }
    [System.IO.File]::WriteAllText((Join-Path $profileDir "package.json"), ($seed | ConvertTo-Json -Depth 10),
                                   (New-Object System.Text.UTF8Encoding($false)))
}
Set-Content -Path (Join-Path $scratch "ui\custom.css") -Value "/* user skin must survive */"
$storeBefore = @((Get-ChildItem (Join-Path $scratch "store")).Name)

$log = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $patch "apply-patch.ps1") -InstallDir $scratch -NoRestart 2>&1
$code = $LASTEXITCODE
$log | Where-Object { $_ -match "\[OK\]|\[WARN\]|\[FAIL\]" } | ForEach-Object { "    $_" }
Check "补丁退出码 0" ($code -eq 0) "exit=$code"
Check "exe 已替换为补丁内构建" ((HashOf (Join-Path $scratch "DeepSeek Harness.exe")) -eq (HashOf (Join-Path $payload "DeepSeek Harness.exe")))
$intCount = (Get-ChildItem (Join-Path $scratch "_internal") -Recurse -File).Count
$payCount = (Get-ChildItem (Join-Path $payload "_internal") -Recurse -File).Count
Check "_internal 完全镜像（旧版多余文件已删）" ($intCount -eq $payCount) "$intCount vs $payCount"
Check "旧版 cryptography / bcrypt 已删除" ((-not (Test-Path (Join-Path $scratch "_internal\cryptography"))) -and (-not (Test-Path (Join-Path $scratch "_internal\bcrypt"))))
Check "随旧包分发的示例外壳插件已删除" (-not (Test-Path (Join-Path $scratch "_internal\ui\plugins")))
Check "用户自加的 ui 文件保留" (Test-Path (Join-Path $scratch "ui\custom.css"))
Check "外壳 UI 已刷新" ((HashOf (Join-Path $scratch "ui\index.html")) -eq (HashOf (Join-Path $payload "ui\index.html")))
Check "ui\.version = $Version" (((Get-Content (Join-Path $scratch "ui\.version") -Raw).Trim()) -eq $Version)
$storeNow = @((Get-ChildItem (Join-Path $scratch "store")).Name)
Check "store 只保留当前商店包" (($storeNow.Count -eq 1) -and ($storeNow[0] -eq "dshmarket-1.50.0.tgz")) (($storeBefore -join ",") + " -> " + ($storeNow -join ","))
$cfg = [System.IO.File]::ReadAllText((Join-Path $scratch "config.json")) | ConvertFrom-Json
Check "config 商店源已指向随包版本" ($cfg.store_sources[0].spec -eq "store/dshmarket-1.50.0.tgz") $cfg.store_sources[0].spec
Check "config 标签已修正（非乱码）" (($cfg.store_sources[0].label -like "dshmarket*") -and ($cfg.store_sources[0].label.Length -gt 9)) $cfg.store_sources[0].label
Check "config app_version = $Version" ($cfg.app_version -eq $Version) $cfg.app_version
$prof = [System.IO.File]::ReadAllText((Join-Path $profileDir "package.json")) | ConvertFrom-Json
$depNames = @($prof.dependencies.PSObject.Properties.Name)
Check "旧版 dsh-web-ui-all 已从 profile 依赖移除" (-not ($depNames -contains "@linxin666/dsh-web-ui-all")) ($depNames -join ",")
Check "profile 里 dshmarket 已重指向随包 tgz" ([string]$prof.dependencies.dshmarket -like "*dshmarket-1.50.0.tgz") ([string]$prof.dependencies.dshmarket)
Check "内核自身 bundle 未被误删" (@($prof.dsh.profile.bundles) -contains "@deepseek-ai/dsh-base")
$backups = @(Get-ChildItem $scratch -Directory -Filter "patch-backup-*")
Check "已生成备份目录" ($backups.Count -ge 1)
if ($backups.Count -ge 1) {
    Check "备份含旧 exe / store / config / profile 清单" (
        (Test-Path (Join-Path $backups[0].FullName "DeepSeek Harness.exe")) -and
        (Test-Path (Join-Path $backups[0].FullName "config.json")) -and
        (Test-Path (Join-Path $backups[0].FullName "profile\package.json")))
}
$beforeDry = HashOf (Join-Path $scratch "config.json")
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $patch "apply-patch.ps1") -InstallDir $scratch -NoRestart -DryRun | Out-Null
Check "DryRun 不改动任何文件" ((HashOf (Join-Path $scratch "config.json")) -eq $beforeDry)
$log2 = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $patch "apply-patch.ps1") -InstallDir $scratch -NoRestart 2>&1
Check "重复应用补丁幂等（退出码 0）" ($LASTEXITCODE -eq 0) "exit=$LASTEXITCODE"

# ---------------------------------------------------------------- 2. CLI 场景
Write-Host "=== B. CLI 场景（core / runtime 以 junction 指向真实构建） ===" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $dist "core\apps\cli\lib\bin.js"))) {
    Write-Host "  跳过：dist 里没有可用的 core（先运行 build.ps1）" -ForegroundColor Yellow
} else {
    cmd /c mklink /J "$scratch\core" "$dist\core" | Out-Null
    $liveRuntime = Join-Path $source "runtime"
    if (Test-Path (Join-Path $liveRuntime "node.exe")) { cmd /c mklink /J "$scratch\runtime" "$liveRuntime" | Out-Null }
    Check "core CLI 就位" (Test-Path (Join-Path $scratch "core\apps\cli\lib\bin.js"))
    $seed = [ordered]@{
        name = "dsh-profile-web"; private = $true
        dependencies = [ordered]@{ dshmarket = "file:" + (Join-Path $scratch "store\dshmarket-1.50.0.tgz")
                                   "@linxin666/dsh-chat-recovery" = "latest" }
        dsh = @{ profile = @{ bundles = @("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "dshmarket", "@linxin666/dsh-chat-recovery") } }
    }
    [System.IO.File]::WriteAllText((Join-Path $profileDir "package.json"), ($seed | ConvertTo-Json -Depth 10),
                                   (New-Object System.Text.UTF8Encoding($false)))
    $log3 = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $patch "apply-patch.ps1") -InstallDir $scratch -NoRestart 2>&1
    $log3 | Where-Object { $_ -match "CLI|\[WARN\]|\[FAIL\]" } | ForEach-Object { "    $_" }
    Check "CLI 场景补丁退出码 0" ($LASTEXITCODE -eq 0) "exit=$LASTEXITCODE"
    if (Test-Path (Join-Path $scratch "runtime\node.exe")) {
        Check "dsh CLI 卸载执行成功" (($log3 -join "`n") -match "dsh CLI 卸载成功")
        $after = [System.IO.File]::ReadAllText((Join-Path $profileDir "package.json")) | ConvertFrom-Json
        Check "CLI 已把旧包文件卸载掉" (-not (Test-Path (Join-Path $profileDir "node_modules\@linxin666\dsh-chat-recovery")))
        Check "CLI 后清单里也没有旧包" (-not (@($after.dependencies.PSObject.Properties.Name) -contains "@linxin666/dsh-chat-recovery"))
    } else {
        Write-Host "  （无 runtime\node.exe，跳过 CLI 卸载断言）" -ForegroundColor Yellow
    }
    cmd /c rmdir "$scratch\core" | Out-Null
    cmd /c rmdir "$scratch\runtime" | Out-Null
    Check "测试用 junction 已清理" (-not (Test-Path (Join-Path $scratch "core\apps")))
}

# ---------------------------------------------------------------- 3. 收尾
if (-not $Keep) {
    Remove-Scratch $scratchRoot
    Remove-Scratch $extractRoot
}
Write-Host ""
if ($fail -eq 0) { Write-Host "PATCH TEST: ALL PASS" -ForegroundColor Green } else { Write-Host "PATCH TEST: $fail FAILED" -ForegroundColor Red }
exit $(if ($fail -eq 0) { 0 } else { 1 })
