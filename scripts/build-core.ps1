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

# Bundled toolchain first (Lazy build); fall back to system node/pnpm so a
# Minimal-flavor build can still build the core (core JS is flavor-neutral).
$node = Join-Path $runtime "node.exe"
$pnpm = Join-Path $runtime "pnpm.cmd"
if (Test-Path $node) {
    $env:PATH = "$runtime;$env:PATH"
    $env:COREPACK_HOME = Join-Path $runtime ".corepack"
} else {
    $node = "node"
    $pnpm = "pnpm"
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "node not found on PATH - install Node.js first (or build the Lazy flavor)"
    }
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        Write-Host "  - pnpm not on PATH; enabling via corepack..."
        & corepack enable 2>$null
        if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
            throw "pnpm/corepack not available"
        }
    }
}

# Bundled portable Git on PATH for upstream build scripts (git rev-parse).
$gitCmd = Join-Path $runtime "git\cmd"
if (Test-Path (Join-Path $gitCmd "git.exe")) { $env:PATH = "$gitCmd;$env:PATH" }

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
    # Headless build: pnpm may need to purge an out-of-sync modules dir,
    # which it refuses to do without a TTY unless CI is set. Slow networks
    # (big native tarballs) also need a relaxed fetch timeout/retry budget.
    $env:CI = "true"
    $env:pnpm_config_confirm_modules_purge = "false"
    $env:npm_config_fetch_timeout = "600000"
    $env:npm_config_fetch_retries = "5"
    $env:pnpm_config_fetch_timeout = "600000"
    $env:pnpm_config_fetch_retries = "5"
    # Optional registry mirror (e.g. https://registry.npmmirror.com) for
    # networks where registry.npmjs.org stalls on large native tarballs.
    if ($env:DSH_BUILD_REGISTRY) {
        $env:npm_config_registry = $env:DSH_BUILD_REGISTRY
        $env:pnpm_config_registry = $env:DSH_BUILD_REGISTRY
    }
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
