@echo off
chcp 65001 >nul
setlocal
rem 启动 DeepSeek Harness 桌面应用（根目录入口�?set "APP=%~dp0dist\DeepSeek Harness"
if not exist "%APP%\DeepSeek Harness.exe" (
  echo [错误] 未找�?dist\DeepSeek Harness\DeepSeek Harness.exe
  echo 请先运行 build.ps1 构建应用�?  pause
  exit /b 1
)
start "" "%APP%\DeepSeek Harness.exe"
exit /b 0