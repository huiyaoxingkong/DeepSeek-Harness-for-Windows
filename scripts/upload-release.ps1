# Upload v<Version> source + release artifacts to GitHub.
#
#   powershell -ExecutionPolicy Bypass -File scripts\upload-release.ps1 -Version 1.0.3
#
# Steps: tag + push source, create the GitHub Release, upload Setup/Update
# exes and SHA256 files. Auth comes from git's credential helper (the same
# credential that git push uses); pass -Token to override. Network calls
# retry with backoff because GitHub can be flaky from some networks.
param(
    [string]$Version = "1.0.3",
    [string]$Tag = "v$Version",
    [string]$Token = "",
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$repo = "huiyaoxingkong/DeepSeek-Harness-for-Windows"
$api = "https://api.github.com/repos/$repo"
$releaseDir = Join-Path $root "release"

function Invoke-Retry([scriptblock]$Action, [int]$Attempts = 5) {
    $delay = 3
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            return & $Action
        } catch {
            if ($i -eq $Attempts) { throw }
            Write-Host "  attempt $i/$Attempts failed ($($_.Exception.Message)); retrying in ${delay}s..."
            Start-Sleep -Seconds $delay
            $delay = [Math]::Min($delay * 2, 60)
        }
    }
}

function Get-GitHubToken {
    if ($Token) { return $Token }
    $input = "protocol=https`nhost=github.com`n`n"
    $out = $input | git credential fill 2>$null
    foreach ($line in ($out -split "`n")) {
        if ($line -match '^password=(.+)$') {
            return $Matches[1].Trim()
        }
    }
    throw "No GitHub credential found: run `"git credential fill`" manually or pass -Token"
}

function Invoke-CurlJson([string]$Method, [string]$Url, [string]$Auth,
                          [string]$JsonBody = "", [string]$DataFile = "") {
    $args = @("-sS", "-L", "--max-time", "1800", "-X", $Method,
              "-H", "Authorization: Bearer $Auth",
              "-H", "Accept: application/vnd.github+json",
              "-H", "User-Agent: DeepSeek-Harness-Desktop/1.0",
              "-H", "X-GitHub-Api-Version: 2022-11-28")
    if ($JsonBody) { $args += @("-H", "Content-Type: application/json", "-d", $JsonBody) }
    if ($DataFile) { $args += @("-H", "Content-Type: application/octet-stream", "--data-binary", "@$DataFile") }
    $args += $Url
    $raw = & curl.exe @args
    if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE" }
    return $raw
}

# ---------------------------------------------------------------- source push
if (-not $SkipPush) {
    Write-Host "=== Pushing source + tag $Tag ===" -ForegroundColor Cyan
    git -C $root add -A
    git -C $root -c user.name="DSH Desktop" -c user.email="dsh-desktop@users.noreply.github.com" `
        commit -m "v${Version}: portable per-instance data dir, dsh-web plugin compatibility, in-app upgrade" `
        --quiet 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "  (commit may already exist, continuing)" }
    Invoke-Retry { git -C $root push origin main }
    $tagExists = (git -C $root tag -l $Tag)
    if (-not $tagExists) {
        git -C $root tag $Tag
        Invoke-Retry { git -C $root push origin $Tag }
    } else {
        Invoke-Retry { git -C $root push origin $Tag }
    }
    Write-Host "  pushed main + $Tag"
} else {
    Write-Host "  -SkipPush: skipping source push"
}

# ---------------------------------------------------------------- release
$token = Get-GitHubToken
Write-Host "=== Creating GitHub Release $Tag ===" -ForegroundColor Cyan

$notes = Join-Path $root "RELEASE_NOTES.md"
$body = if (Test-Path $notes) { Get-Content $notes -Raw } else { "DeepSeek Harness for Windows $Version" }
$payload = @{
    tag_name         = $Tag
    target_commitish = "main"
    name             = "DeepSeek Harness for Windows $Version"
    body             = $body
    draft            = $false
    prerelease       = $false
} | ConvertTo-Json -Compress

$releaseJson = Invoke-Retry { Invoke-CurlJson "POST" "$api/releases" $token $payload }
try {
    $releaseId = ($releaseJson | ConvertFrom-Json).id
} catch {
    # Release may already exist (idempotent re-run): fetch it.
    $get = Invoke-CurlJson "GET" "$api/releases/tags/$Tag" $token
    $releaseId = ($get | ConvertFrom-Json).id
}
if (-not $releaseId) { throw "could not determine release id" }
Write-Host "  release id: $releaseId"

Write-Host "=== Uploading assets ===" -ForegroundColor Cyan
$assets = Get-ChildItem $releaseDir -File | Sort-Object Name
if (-not $assets) { throw "no release artifacts in $releaseDir" }
foreach ($file in $assets) {
    $name = $file.Name
    $escaped = [uri]::EscapeDataString($name)
    $url = "https://uploads.github.com/repos/$repo/releases/$releaseId/assets?name=$escaped"
    Write-Host "  uploading $name ($('{0:N1}' -f ($file.Length / 1MB)) MB)..."
    Invoke-Retry { Invoke-CurlJson "POST" $url $token -DataFile $file.FullName } -Attempts 4
    Write-Host "    done"
}

Write-Host ""
Write-Host "=== Release published ===" -ForegroundColor Green
Write-Host "  https://github.com/$repo/releases/tag/$Tag"
