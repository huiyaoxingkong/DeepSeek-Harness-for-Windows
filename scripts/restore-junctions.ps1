# Restore the core's workspace junctions from junctions.json.
#
# The core ships with junctions.json (see scripts\write-junctions-manifest.py)
# describing every pnpm workspace junction as core-relative (link, target)
# pairs. After extraction by a generic archiver the links are empty
# directories, so this script removes them and recreates the junctions with
# mklink /J against the actual install location. Junction creation does not
# need administrator rights. mklink calls are batched per cmd invocation to
# keep startup fast.
#
# Usage: powershell -ExecutionPolicy Bypass -File restore-junctions.ps1 <core-dir>

param(
    [Parameter(Mandatory = $true)][string]$CoreDir
)

$ErrorActionPreference = "Stop"
$manifest = Join-Path $CoreDir "junctions.json"
if (-not (Test-Path $manifest)) {
    Write-Host "restore-junctions: no manifest, nothing to do"
    exit 0
}

$entries = Get-Content $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "restore-junctions: restoring $($entries.Count) junction(s) under $CoreDir"

# Batch by command-line character budget: pnpm store paths can be long and
# cmd's line limit is ~8191 chars.
$MAX = 7000
$created = 0
$chunk = @()
$len = 0
foreach ($e in $entries) {
    $link = Join-Path $CoreDir ($e.link -replace "/", "\")
    $target = Join-Path $CoreDir ($e.target -replace "/", "\")
    if (Test-Path -LiteralPath $link) {
        Remove-Item -LiteralPath $link -Recurse -Force -ErrorAction SilentlyContinue
    }
    $parent = Split-Path -Parent $link
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $cmdLine = "mklink /J `"$link`" `"$target`""
    if ($len + $cmdLine.Length -gt $MAX) {
        cmd /c ($chunk -join " & ") 2>&1 | Out-Null
        $created += $chunk.Count
        $chunk = @()
        $len = 0
    }
    $chunk += $cmdLine
    $len += $cmdLine.Length + 3
}
if ($chunk.Count -gt 0) {
    cmd /c ($chunk -join " & ") 2>&1 | Out-Null
    $created += $chunk.Count
}
Write-Host "restore-junctions: created $created junction(s)"
