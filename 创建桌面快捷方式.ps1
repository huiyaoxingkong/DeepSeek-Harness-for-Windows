# 创建「DeepSeek Harness」桌面快捷方式（正式启动入口）
# 用法：powershell -ExecutionPolicy Bypass -File 创建桌面快捷方式.ps1

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $scriptDir "dist\DeepSeek Harness"
if (-not (Test-Path (Join-Path $appDir "DeepSeek Harness.exe"))) {
    $appDir = $scriptDir
}

$exe = Join-Path $appDir "DeepSeek Harness.exe"
if (-not (Test-Path $exe)) {
    Write-Host "[错误] 未找到 DeepSeek Harness.exe" -ForegroundColor Red
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "DeepSeek Harness.lnk"

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = $appDir
$lnk.IconLocation = "$exe,0"
$lnk.Description = "DeepSeek Harness Desktop"
$lnk.Save()

Write-Host "已创建桌面快捷方式: $lnkPath" -ForegroundColor Green