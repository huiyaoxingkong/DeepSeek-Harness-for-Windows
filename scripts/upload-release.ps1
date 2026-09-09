# Upload v<Version> source + release artifacts to GitHub.
#
#   powershell -ExecutionPolicy Bypass -File scripts\upload-release.ps1 -Version 1.0.4
#
# Steps: tag + push source, create the GitHub Release, upload Setup/Update
# exes and SHA256 files. Auth comes from git's credential helper (the same
# credential that git push uses); pass -Token to override. Network calls
# retry with backoff because GitHub can be flaky from some networks.
param(
    [string]$Version = "1.0.4",
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
    # Headless-friendly path: token from the environment (e.g. read from
    # Windows Credential Manager by the caller) without invoking GCM, which
    # can hang on interactive refresh in non-TTY contexts.
    if ($env:GITHUB_TOKEN) { return $env:GITHUB_TOKEN }
    $input = "protocol=https`nhost=github.com`n`n"
    $out = $input | git credential fill 2>$null
    foreach ($line in ($out -split "`n")) {
        if ($line -match '^password=(.+)$') {
            return $Matches[1].Trim()
        }
    }
    throw "No GitHub credential found: set GITHUB_TOKEN, run `"git credential fill`" manually or pass -Token"
}

function Invoke-CurlJson([string]$Method, [string]$Url, [string]$Auth,
                          [string]$JsonBody = "", [string]$DataFile = "") {
    $args = @("-sS", "-L", "--max-time", "1800", "-X", $Method,
              "-H", "Authorization: Bearer $Auth",
              "-H", "Accept: application/vnd.github+json",
              "-H", "User-Agent: DeepSeek-Harness-Desktop/1.0",
              "-H", "X-GitHub-Api-Version: 2022-11-28")
    $tmpJson = ""
    if ($JsonBody) {
        # PS 5.1 mangles embedded quotes when passing -d to native commands
        # (GitHub answers "Problems parsing JSON"); send the body via file.
        $tmpJson = Join-Path $env:TEMP ("dsh-release-body-" + [guid]::NewGuid().ToString("N") + ".json")
        [System.IO.File]::WriteAllText($tmpJson, $JsonBody,
            (New-Object System.Text.UTF8Encoding($false)))
        $args += @("-H", "Content-Type: application/json", "--data-binary", "@$tmpJson")
    }
    if ($DataFile) { $args += @("-H", "Content-Type: application/octet-stream", "--data-binary", "@$DataFile") }
    $args += $Url
    $raw = & curl.exe @args
    if ($tmpJson) { Remove-Item $tmpJson -Force -ErrorAction SilentlyContinue }
    if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE" }
    return $raw
}

# ---------------------------------------------------------------- source push
if (-not $SkipPush) {
    Write-Host "=== Pushing source + tag $Tag ===" -ForegroundColor Cyan
    git -C $root add -A
    git -C $root -c user.name="DSH Desktop" -c user.email="dsh-desktop@users.noreply.github.com" `
        commit -m "v${Version}: pnpm store self-heal for profile plugins, concurrent shell UI server, MIME/plugin-entry/security fixes" `
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
# Read as UTF-8 explicitly: the notes are BOM-less UTF-8 and PS 5.1 would
# otherwise decode them as ANSI (mojibake body + control chars => GitHub
# rejects with "Invalid request").
$body = if (Test-Path $notes) { Get-Content $notes -Raw -Encoding UTF8 } else { "DeepSeek Harness for Windows $Version" }
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
# Only this version's artifacts: a release\ dir can hold leftovers from
# earlier releases, which must never be attached to the new one.
$assets = Get-ChildItem $releaseDir -File | Sort-Object Name |
    Where-Object { $_.Name -like "DeepSeekHarness-$Version*" -or
                   $_.Name -like "SHA256SUMS-$Version*" }
if (-not $assets) { throw "no release artifacts for $Version in $releaseDir" }
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
