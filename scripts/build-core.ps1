# Builds the dsh core: ensures a git repo (upstream build scripts require
# `git rev-parse HEAD`), installs dependencies with pnpm, and runs the build.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/build-core.ps1
param(
    [string]$CoreDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $CoreDir) { $CoreDir = Join-Path $root "core" }
$runtime = Join-Path $root "runtime"

if (-not (Test-Path (Join-Path $runtime "node.exe"))) {
    throw "runtime\node.exe missing - run scripts\install-node.ps1 first"
}

$env:PATH = "$runtime;$env:PATH"
$env:COREPACK_HOME = Join-Path $runtime ".corepack"
$pnpm = Join-Path $runtime "pnpm.cmd"
if (-not (Test-Path $pnpm)) {
    throw "runtime\pnpm.cmd missing"
}

if (-not (Test-Path (Join-Path $CoreDir "package.json"))) {
    throw "core\package.json missing - place the deepseek-harness source in $CoreDir"
}

Push-Location $CoreDir
try {
    if (-not (Test-Path (Join-Path $CoreDir ".git"))) {
        Write-Host "  - initializing git repo (required by upstream build scripts)..."
        git init -b main | Out-Null
        git add -A
        git -c user.name="dsh-desktop" -c user.email="dsh@local" commit -m "core snapshot" --quiet
    }

    Write-Host "  - pnpm install ..."
    & $pnpm install --node-linker=hoisted --no-frozen-lockfile
    if (-not $?) { throw "pnpm install failed" }

    Write-Host "  - pnpm build ..."
    & $pnpm run build
    if (-not $?) { throw "pnpm build failed" }
} finally {
    Pop-Location
}

Write-Host "  - recording upstream commit info..."
python (Join-Path $PSScriptRoot "write-core-info.py") $CoreDir
if (-not $?) { Write-Warning "write-core-info failed (non-fatal)" }

Write-Host "Core build complete: $CoreDir" -ForegroundColor Green
