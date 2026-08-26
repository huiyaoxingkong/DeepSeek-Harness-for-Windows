# Release builder: 7-Zip self-extracting Setup + in-place Update packages.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\make-release.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\make-release.ps1 -Version 1.0.2 -SkipBuild
#
# Products written to release\:
#   DeepSeekHarness-<ver>-Setup.exe    first install (prompts for a directory)
#   DeepSeekHarness-<ver>-Update.exe   silent in-place upgrade (InstallPath=".")
#   <exe>.sha256 / SHA256SUMS-<ver>.txt
param(
    [string]$Version = "1.0.2",
    [switch]$SkipBuild,
    [int]$Level = 7
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist\DeepSeek Harness"
$release = Join-Path $root "release"
$sevenZip = Join-Path $root "tools\7zip\7z.exe"
# The GUI SFX module extracts >MAX_PATH paths correctly (the console module
# cannot) and runs ExecuteFile even when extraction logs recoverable errors;
# it has no manifest, so the "Update"/"Setup" filename makes Windows ask for
# elevation once — acceptable for an installer/upgrader.
$sfxModule = Join-Path $root "tools\7zip\7z.sfx"

if (-not (Test-Path $sevenZip)) { throw "7z.exe missing: $sevenZip" }
if (-not (Test-Path $sfxModule)) { throw "7z.sfx missing: $sfxModule" }

New-Item -ItemType Directory -Path $release -Force | Out-Null

if (-not $SkipBuild) {
    Write-Host "=== Building app ($Version) ===" -ForegroundColor Cyan
    & (Join-Path $root "build.ps1") -Version $Version
    if (-not $?) { throw "build.ps1 failed" }
}
if (-not (Test-Path (Join-Path $dist "DeepSeek Harness.exe"))) {
    throw "dist app missing; run build.ps1 first"
}

$setupExe = Join-Path $release "DeepSeekHarness-$Version-Setup.exe"
$updateExe = Join-Path $release "DeepSeekHarness-$Version-Update.exe"

function Write-Utf8NoBom([string]$path, [string]$text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $text, $enc)
}

function New-Sfx([string]$cfgPath, [string]$archivePath, [string]$outExe,
                 [string]$module) {
    $sfxBytes = [System.IO.File]::ReadAllBytes($module)
    $cfgBytes = [System.IO.File]::ReadAllBytes($cfgPath)
    $arcBytes = [System.IO.File]::ReadAllBytes($archivePath)
    $out = New-Object byte[] ($sfxBytes.Length + $cfgBytes.Length + $arcBytes.Length)
    [Array]::Copy($sfxBytes, 0, $out, 0, $sfxBytes.Length)
    [Array]::Copy($cfgBytes, 0, $out, $sfxBytes.Length, $cfgBytes.Length)
    [Array]::Copy($arcBytes, 0, $out, $sfxBytes.Length + $cfgBytes.Length, $arcBytes.Length)
    [System.IO.File]::WriteAllBytes($outExe, $out)
    Write-Host "  created $outExe ($('{0:N1}' -f ($out.Length / 1MB)) MB)"
}

# ---------------------------------------------------------------- SFX configs

$workTmp = Join-Path $release ".tmp"
New-Item -ItemType Directory -Path $workTmp -Force | Out-Null

$setupCfg = Join-Path $workTmp "dsh-setup-$Version-cfg.txt"
Write-Utf8NoBom $setupCfg @"
;!@Install@!UTF-8!
Title="DeepSeek Harness $Version 安装"
BeginPrompt="将 DeepSeek Harness $Version 解压安装到以下目录？"
InstallPath="C:\DeepSeek Harness"
ExecuteFile="post-install.bat"
ExecuteParameters=""
RunProgram=""
;!@InstallEnd@!
"@

$updateCfg = Join-Path $workTmp "dsh-update-$Version-cfg.txt"
Write-Utf8NoBom $updateCfg @"
;!@Install@!UTF-8!
Title="DeepSeek Harness $Version 升级"
BeginPrompt=""
InstallPath="."
ExecuteFile="post-update.bat"
ExecuteParameters=""
RunProgram=""
GUIMode="2"
SelfDelete="1"
OverwriteMode="1"
;!@InstallEnd@!
"@

# ---------------------------------------------------------------- archives

$tmpSetup = Join-Path $workTmp "dsh-setup-$Version.7z"
$tmpUpdate = Join-Path $workTmp "dsh-update-$Version.7z"
Remove-Item $tmpSetup, $tmpUpdate -Force -ErrorAction SilentlyContinue

Write-Host "=== Packing Setup archive ===" -ForegroundColor Cyan
# -snl is mandatory: the core contains mutual junctions (vendor/cordis <->
# vendor/include) and 7z follows them by default, enumerating the cycle
# until paths exceed MAX_PATH. Storing links preserves the layout and the
# app self-heals missing links at first launch anyway.
& $sevenZip a -t7z "-mx=$Level" -mmt=on -snl -bso0 -bsp0 $tmpSetup """$dist\*"""
if ($LASTEXITCODE -ne 0) { throw "7z setup archive failed ($LASTEXITCODE)" }

Write-Host "=== Packing Update archive (keeps data/ui/config/logs) ===" -ForegroundColor Cyan
# The update must not clobber per-instance state: root-level data\, the
# user-editable root ui\, config.json, logs and upgrade leftovers stay
# untouched (exact-name exclusions, so _internal\ui still ships).
& $sevenZip a -t7z "-mx=$Level" -mmt=on -snl -bso0 -bsp0 $tmpUpdate """$dist\*""" `
    "-x!data" "-x!ui" "-x!logs" "-x!config.json" "-x!upgrade.bat" `
    "-x!core.backup" "-x!.update" "-x!DeepSeekHarness-*-Update.exe"
if ($LASTEXITCODE -ne 0) { throw "7z update archive failed ($LASTEXITCODE)" }

# ---------------------------------------------------------------- SFX exes

Write-Host "=== Building SFX executables ===" -ForegroundColor Cyan
New-Sfx $setupCfg $tmpSetup $setupExe $sfxModule
New-Sfx $updateCfg $tmpUpdate $updateExe $sfxModule

# ---------------------------------------------------------------- checksums

$sums = @()
foreach ($exe in $setupExe, $updateExe) {
    $hash = (Get-FileHash -Path $exe -Algorithm SHA256).Hash.ToLower()
    $name = Split-Path -Leaf $exe
    $sums += "$hash  $name"
    [System.IO.File]::WriteAllText("$exe.sha256", "$hash  $name`r`n",
        (New-Object System.Text.UTF8Encoding($false)))
}
$sumsPath = Join-Path $release "SHA256SUMS-$Version.txt"
[System.IO.File]::WriteAllLines($sumsPath, $sums,
    (New-Object System.Text.UTF8Encoding($false)))

# Cleanup is best-effort and must never abort the release.
try { Remove-Item $tmpSetup, $tmpUpdate, $setupCfg, $updateCfg -Force -ErrorAction SilentlyContinue } catch {}
try { Remove-Item $workTmp -Recurse -Force -ErrorAction SilentlyContinue } catch {}

Write-Host ""
Write-Host "=== Release artifacts ===" -ForegroundColor Green
Get-ChildItem $release -File | Sort-Object Name | ForEach-Object {
    "  {0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB)
}
Write-Host "SHA256SUMS: $sumsPath"
