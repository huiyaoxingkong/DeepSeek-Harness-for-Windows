# One-click build: portable Node runtime -> core build -> PyInstaller exe -> dist/
#
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1 [-SkipCoreBuild] [-SkipPyInstaller]
param(
    [switch]$SkipCoreBuild,
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== DeepSeek Harness Desktop build ===" -ForegroundColor Cyan

# 1. portable Node runtime
& (Join-Path $PSScriptRoot "scripts\install-node.ps1")
if (-not $?) { throw "install-node failed" }

# 2. build the core (git init + pnpm install + pnpm build)
if (-not $SkipCoreBuild) {
    & (Join-Path $PSScriptRoot "scripts\build-core.ps1")
    if (-not $?) { throw "build-core failed" }
}

# 2b. build the bundled store plugin from the local source archive
& (Join-Path $PSScriptRoot "scripts\build-store.ps1")
if (-not $?) { throw "build-store failed" }

# 3. PyInstaller
if (-not $SkipPyInstaller) {
    Write-Host "=== Packaging launcher exe ===" -ForegroundColor Cyan
    python -m PyInstaller --noconfirm --clean --distpath (Join-Path $root "dist\pyinstaller") `
        --workpath (Join-Path $root "dist\.build") `
        (Join-Path $root "app\dsh-desktop.spec")
    if (-not $?) { throw "PyInstaller failed" }
}

# 4. assemble the final app folder
Write-Host "=== Assembling dist\DeepSeek Harness ===" -ForegroundColor Cyan
$dist = Join-Path $root "dist\DeepSeek Harness"
$pkg = Join-Path $root "dist\pyinstaller\DeepSeek Harness"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Path $dist -Force | Out-Null

Copy-Item (Join-Path $pkg "*") -Destination $dist -Recurse -Force

Write-Host "  - copying runtime (portable Node.js)..."
robocopy (Join-Path $root "runtime") (Join-Path $dist "runtime") /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "robocopy runtime failed ($LASTEXITCODE)" }

Write-Host "  - copying core (built dsh source, junction-aware)..."
if (-not $SkipCoreBuild) {
    robocopy (Join-Path $root "core") (Join-Path $dist "core") /E /XJ /MT:32 /NFL /NDL /NJH /NJS /NC /NS /NP `
        /XD .git .dsh-build | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy core failed ($LASTEXITCODE)" }
    python (Join-Path $PSScriptRoot "scripts\relink.py") (Join-Path $root "core") (Join-Path $dist "core")
    if (-not $?) { throw "relink core junctions failed" }
    python (Join-Path $PSScriptRoot "scripts\write-junctions-manifest.py") (Join-Path $dist "core")
    if (-not $?) { throw "write-junctions-manifest failed" }
    New-Item -ItemType Directory -Path (Join-Path $dist "scripts") -Force | Out-Null
    Copy-Item (Join-Path $PSScriptRoot "scripts\restore-junctions.ps1") (Join-Path $dist "scripts") -Force
} else {
    Write-Host "  - core copy skipped (use -SkipCoreBuild only when core already present)"
}

New-Item -ItemType Directory -Path (Join-Path $dist "logs") -Force | Out-Null

Write-Host "  - copying shell UI (user-editable web files)..."
robocopy (Join-Path $root "app\ui") (Join-Path $dist "ui") /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "robocopy ui failed ($LASTEXITCODE)" }

Write-Host "  - copying bundled store plugin packages..."
robocopy (Join-Path $root "app\store") (Join-Path $dist "store") /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "robocopy store failed ($LASTEXITCODE)" }

$config = @{
    api_key       = ""
    base_url      = ""
    port          = 3080
    auto_start    = $false
    open_browser  = $false
    core_dir      = "core"
    runtime_dir   = "runtime"
    app_version   = "1.0.1"
    last_updated_core = ""
    store_sources = @(
        @{
            name     = "dshmarket"
            label    = "dshmarket 插件商店"
            spec     = "store/dshmarket-1.21.4.tgz"
            homepage = "https://github.com/dsh-market/dsh-market"
            catalog  = "https://awesome-dsh-plugin.com/plugins.json"
            builtin  = $true
        }
    )
}
if (-not (Test-Path (Join-Path $dist "config.json"))) {
    $config | ConvertTo-Json | Set-Content (Join-Path $dist "config.json") -Encoding UTF8
}

Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Green
Write-Host "App folder: $dist"
Write-Host "Launch:     $dist\DeepSeek Harness.exe"
