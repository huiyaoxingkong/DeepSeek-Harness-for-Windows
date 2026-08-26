@echo off
setlocal
echo 正在恢复核心组件链接...
if exist "%~dp0scripts\restore-junctions.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restore-junctions.ps1" "%~dp0core"
)
rem 冒烟测试标记：存在 no-launch.flag 时不建快捷方式、不启动
if exist "%~dp0no-launch.flag" exit /b 0
echo 正在创建桌面快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\DeepSeek Harness.lnk'); $lnk.TargetPath = '%~dp0DeepSeek Harness.exe'; $lnk.WorkingDirectory = '%~dp0'; $lnk.IconLocation = '%~dp0DeepSeek Harness.exe,0'; $lnk.Description = 'DeepSeek Harness'; $lnk.Save()"
if exist "%~dp0upgrade.bat" del /q "%~dp0upgrade.bat"
echo 升级完成，正在启动 DeepSeek Harness...
start "" "%~dp0DeepSeek Harness.exe"
if exist "%~dp0upgrading.flag" del /q "%~dp0upgrading.flag"
exit /b 0
