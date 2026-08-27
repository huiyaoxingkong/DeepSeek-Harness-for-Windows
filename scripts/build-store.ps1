# Build the bundled store plugin package (dshmarket) from the local source
# archive dsh-market-main.zip into app/store/dshmarket-<version>.tgz.
#
# The published store package is a build product (lib/ + client/ are built by
# `npm run build` via prepack), so the raw source cannot be installed as-is.
# This script compiles it with the bundled Node/pnpm toolchain and packs the
# npm tarball, with the runtime dependency closure bundled into the tarball
# (bundleDependencies) — enabling the store in the app then needs no network.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\build-store.ps1
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$zip = Join-Path $root "dsh-market-main.zip"
$outDir = Join-Path $root "app\store"

if (-not (Test-Path $zip)) {
    if ($Force) { throw "dsh-market-main.zip not found at $zip" }
    Write-Host "build-store: dsh-market-main.zip not found, skipping." -ForegroundColor DarkGray
    exit 0
}

$work = Join-Path (Join-Path $root "dist") ".store-build"
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Path $work -Force | Out-Null

Write-Host "=== build-store: extracting dsh-market-main.zip ===" -ForegroundColor Cyan
Expand-Archive -Path $zip -DestinationPath (Join-Path $work "src") -Force
$src = Join-Path $work "src\dsh-market-main"
if (-not (Test-Path (Join-Path $src "package.json"))) { throw "unexpected archive layout: $src has no package.json" }

# Bundled Node toolchain (runtime/), fall back to system when not present.
$nodeDir = Join-Path $root "runtime"
$node = Join-Path $nodeDir "node.exe"
$pnpm = Join-Path $nodeDir "pnpm.cmd"
$npm = Join-Path $nodeDir "npm.cmd"
if (-not (Test-Path $node)) { $node = "node"; $pnpm = "pnpm"; $npm = "npm" }
else { $env:PATH = $nodeDir + [IO.Path]::PathSeparator + $env:PATH }

Write-Host "=== build-store: pnpm install (dev toolchain, scripts off) ===" -ForegroundColor Cyan
# Relaxed fetch budget for slow networks (large native tarballs).
$env:npm_config_fetch_timeout = "600000"
$env:npm_config_fetch_retries = "5"
$env:pnpm_config_fetch_timeout = "600000"
$env:pnpm_config_fetch_retries = "5"
Push-Location $src
try {
    # --shamefully-hoist: npm pack needs the bundled deps at the top-level
    # node_modules, not inside the pnpm virtual store. The source zip may
    # carry a lockfile older than its package.json — never freeze it.
    & $pnpm install --ignore-scripts --shamefully-hoist --no-frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "pnpm install failed (exit $LASTEXITCODE)" }

    Write-Host "=== build-store: bundling runtime dependencies (offline enable) ===" -ForegroundColor Cyan
    # Runtime closure: js-yaml -> argparse, undici (no deps). Bundled so the app
    # can `pnpm add <tarball>` with zero registry traffic.
    $runtimeDeps = @("js-yaml", "argparse", "undici")
    foreach ($d in $runtimeDeps) {
        if (-not (Test-Path (Join-Path $src "node_modules\$d"))) {
            throw "node_modules\$d missing after install"
        }
    }
    $patchJs = Join-Path $work "patch-bundle.js"
    @"
const fs = require('fs')
const p = 'package.json'
const j = JSON.parse(fs.readFileSync(p, 'utf8'))
j.bundleDependencies = ['js-yaml', 'argparse', 'undici']
fs.writeFileSync(p, JSON.stringify(j, null, 2))
"@ | Set-Content $patchJs -Encoding UTF8
    & $node $patchJs
    if ($LASTEXITCODE -ne 0) { throw "package.json patch failed" }

    Write-Host "=== build-store: npm pack (prepack builds lib + client, preflight) ===" -ForegroundColor Cyan
    & $npm pack --pack-destination $work
    if ($LASTEXITCODE -ne 0) { throw "npm pack failed (exit $LASTEXITCODE)" }
}
finally {
    Pop-Location
}

$tgz = Get-ChildItem (Join-Path $work "*.tgz") | Select-Object -First 1
if (-not $tgz) { throw "npm pack produced no tarball" }
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
Copy-Item $tgz.FullName (Join-Path $outDir $tgz.Name) -Force
$size = [math]::Round($tgz.Length / 1KB)
Write-Host "build-store: bundled -> app\store\$($tgz.Name) (${size} KB)" -ForegroundColor Green
Remove-Item $work -Recurse -Force
