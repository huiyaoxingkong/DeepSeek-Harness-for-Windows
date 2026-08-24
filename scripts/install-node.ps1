# Downloads a portable Node.js (win-x64) into runtime/ so the app ships
# without requiring a system Node installation.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/install-node.ps1 [-Version 24.16.0]
param(
    [string]$Version = "24.16.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "runtime"
$url = "https://nodejs.org/dist/v$Version/node-v$Version-win-x64.zip"
$zip = Join-Path $env:TEMP "node-v$Version-win-x64.zip"

New-Item -ItemType Directory -Path $target -Force | Out-Null

if (-not (Test-Path (Join-Path $target "node.exe"))) {
    Write-Host "Downloading Node.js v$Version ..."
    Invoke-WebRequest -Uri $url -OutFile $zip
    Write-Host "Extracting ..."
    Expand-Archive -Path $zip -DestinationPath $env:TEMP -Force
    Copy-Item (Join-Path $env:TEMP "node-v$Version-win-x64\*") -Destination $target -Recurse -Force
    Remove-Item (Join-Path $env:TEMP "node-v$Version-win-x64") -Recurse -Force
    Remove-Item $zip -Force
} else {
    Write-Host "node.exe already present, skipping download."
}

& (Join-Path $target "node.exe") --version
Write-Host "Runtime ready at $target"
