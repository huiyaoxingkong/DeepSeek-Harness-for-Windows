@echo off
setlocal
rem 停止 DeepSeek Harness 桌面应用及其核心服务器进程（仅本实例）
echo 正在停止 DeepSeek Harness...
taskkill /IM "DeepSeek Harness.exe" /F >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-core.ps1" -CoreDir "%~dp0core"
echo 已停止。
pause
exit /b 0