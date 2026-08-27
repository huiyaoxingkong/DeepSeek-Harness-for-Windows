# Smoke-test the release SFX packages WITHOUT touching the user's machine:
#   - content check: 7z extracts the payload (config block is not executed)
#   - upgrade dry-run: run the Update exe inside a COPY of the install dir
#     with no-launch.flag (post-update.bat bails out early)
param(
    [string]$Version = "1.0.3",
    [ValidateSet("Lazy", "Minimal")]
    [string]$Flavor = "Lazy"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$release = Join-Path $root "release"
$sevenZip = Join-Path $root "tools\7zip\7z.exe"
$flavorSuffix = if ($Flavor -eq "Minimal") { "-Minimal" } else { "" }
$setupExe = Join-Path $release "DeepSeekHarness-$Version$flavorSuffix-Setup.exe"
$updateExe = Join-Path $release "DeepSeekHarness-$Version$flavorSuffix-Update.exe"
$work = Join-Path $root ".tmp-sfx-test"
if (Test-Path $work) { & cmd /c rmdir /s /q """$work""" | Out-Null }
New-Item -ItemType Directory -Path $work -Force | Out-Null

# 1. payload content checks ------------------------------------------------
Write-Host "=== 1. Setup payload ===" -ForegroundColor Cyan
$setupOut = Join-Path $work "setup-content"
& $sevenZip x $setupExe "-o$setupOut" -y -bso0 -bsp0
if ($LASTEXITCODE -ne 0) { throw "7z cannot open Setup.exe" }
$setupMust = @("DeepSeek Harness.exe", "core\apps\cli\lib\bin.js",
               "store\dshmarket-1.33.0.tgz", "post-install.bat", "ui\index.html",
               "启动 DeepSeek Harness.bat", "停止 DeepSeek Harness.bat",
               "创建桌面快捷方式.ps1", "stop-core.ps1")
if ($Flavor -eq "Lazy") {
    $setupMust += @("runtime\node.exe", "runtime\git\cmd\git.exe", "runtime\git\bin\bash.exe")
} else {
    if (Test-Path (Join-Path $setupOut "runtime")) { throw "Minimal payload must not contain runtime" }
}
foreach ($p in $setupMust) {
    if (-not (Test-Path (Join-Path $setupOut $p))) { throw "Setup payload missing: $p" }
}
# Note: the shipped-core boot check lives in build.ps1 (runs against dist/)
# because console 7z cannot fully extract very long .pnpm paths here, while
# the GUI SFX module (used by real installs) handles them correctly.
# Chinese-named helpers must extract with their exact names (A1: no mojibake)
$badNames = Get-ChildItem $setupOut -Recurse -Force -File |
    Where-Object { $_.Name -match '鍋滄|鍚姩|妗岄潰|閿欒' }
if ($badNames) { throw "Mojibake filenames extracted: $($badNames.Name -join ', ')" }
Write-Host "  setup payload OK (Chinese names intact)"

Write-Host "=== 2. Update payload (must NOT contain data/ui/config/logs) ===" -ForegroundColor Cyan
$updateOut = Join-Path $work "update-content"
& $sevenZip x $updateExe "-o$updateOut" -y -bso0 -bsp0
if ($LASTEXITCODE -ne 0) { throw "7z cannot open Update.exe" }
$updateMust = @("DeepSeek Harness.exe", "core\apps\cli\lib\bin.js",
                "post-update.bat", "_internal\ui\index.html",
                "启动 DeepSeek Harness.bat", "停止 DeepSeek Harness.bat",
                "创建桌面快捷方式.ps1", "stop-core.ps1")
if ($Flavor -eq "Lazy") {
    $updateMust += @("runtime\node.exe", "runtime\git\cmd\git.exe")
} else {
    if (Test-Path (Join-Path $updateOut "runtime")) { throw "Minimal update must not contain runtime" }
}
foreach ($p in $updateMust) {
    if (-not (Test-Path (Join-Path $updateOut $p))) { throw "Update payload missing: $p" }
}
foreach ($forbidden in "config.json", "data", "ui", "logs", "upgrade.bat") {
    if (Test-Path (Join-Path $updateOut $forbidden)) { throw "Update payload must not contain: $forbidden" }
}
Write-Host "  update payload OK (state dirs excluded, bundled UI included)"

# 3. upgrade dry-run on a copy of the install dir --------------------------
# The GUI SFX cannot run non-elevated in an automated test (Windows
# installer-detection UAC), so simulate exactly what it does: extract the
# payload in place (7z.exe handles >MAX_PATH like the GUI module), then run
# post-update.bat (which performs the junction restore and would relaunch).
Write-Host "=== 3. Update dry-run (install-dir copy + no-launch.flag) ===" -ForegroundColor Cyan
$installCopy = Join-Path $work "install-copy"
$realInstall = "D:\Agent-windows\DeepSeekHarness"
if (-not (Test-Path (Join-Path $realInstall "DeepSeek Harness.exe"))) {
    Write-Host "  real install not found; using dist copy instead"
    $realInstall = Join-Path $root "dist\DeepSeek Harness"
}
robocopy $realInstall $installCopy /E /XJ /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "install copy failed ($LASTEXITCODE)" }

# simulate per-instance state that must survive the upgrade
New-Item -ItemType Directory -Path (Join-Path $installCopy "data") -Force | Out-Null
Set-Content -Path (Join-Path $installCopy "data\marker.txt") -Value "instance-data"
Set-Content -Path (Join-Path $installCopy "ui\custom.css") -Value "/* user skin */"
$userConfig = Get-Content (Join-Path $installCopy "config.json") -Raw
Set-Content -Path (Join-Path $installCopy "no-launch.flag") -Value ""

# module check: the update exe must use the GUI SFX module (7z.sfx bytes)
$moduleHead = [IO.File]::ReadAllBytes((Join-Path $root "tools\7zip\7z.sfx"))[0..4095]
$exeHead = [IO.File]::ReadAllBytes($updateExe)[0..4095]
if ([BitConverter]::ToString($moduleHead) -ne [BitConverter]::ToString($exeHead)) {
    throw "update exe was not built from the GUI SFX module"
}
Write-Host "  update exe uses the GUI SFX module"

# extract the payload exactly where the SFX would (overwriting in place)
& $sevenZip x $updateExe "-o$installCopy" -y -bso0 -bsp0
if ($LASTEXITCODE -ne 0) { throw "payload extraction failed ($LASTEXITCODE)" }

Push-Location $installCopy
try {
    & cmd /c "post-update.bat"
    $postExit = $LASTEXITCODE
} finally {
    Pop-Location
}
Write-Host "  post-update exit: $postExit"
Start-Sleep -Seconds 2
if (-not (Test-Path (Join-Path $installCopy "core\apps\cli\lib\bin.js"))) { throw "core missing after update" }
if (-not (Test-Path (Join-Path $installCopy "data\marker.txt"))) { throw "data/ was clobbered!" }
if (-not (Test-Path (Join-Path $installCopy "ui\custom.css"))) { throw "ui/ was clobbered!" }
if ((Get-Content (Join-Path $installCopy "config.json") -Raw) -ne $userConfig) { throw "config.json changed!" }
$links = Get-ChildItem (Join-Path $installCopy "core\apps\cli\node_modules") -Force -Directory `
    | Where-Object { $_.Attributes -match 'ReparsePoint' }
Write-Host "  junctions recreated: $($links.Count)"
if ($links.Count -lt 3) { throw "junction restore did not run!" }
Write-Host ""
Write-Host "=== SFX smoke test PASS ===" -ForegroundColor Green
