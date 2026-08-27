@echo off
setlocal
tasklist /FI "IMAGENAME eq DeepSeek Harness.exe" 2>nul | find /I "DeepSeek Harness.exe" >nul && (echo DeepSeek Harness 已在运行，请查看应用窗口。& exit /b 0)
rem 启动 DeepSeek Harness 桌面应用（应用目录入口）
start "" "%~dp0DeepSeek Harness.exe"
exit /b 0