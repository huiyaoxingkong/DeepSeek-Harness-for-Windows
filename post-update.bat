@echo off
setlocal
echo 正在恢复核心组件链接...
if exist "%~dp0scripts\restore-junctions.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restore-junctions.ps1" "%~dp0core"
)
rem Refresh the default shell UI: pre-1.0.3 installs have no ui\.version
rem marker; keep their ui as backup and install the bundled default.
if not exist "%~dp0ui\.version" (
  if exist "%~dp0ui-backup" rmdir /s /q "%~dp0ui-backup" >nul 2>&1
  if exist "%~dp0ui" rename "%~dp0ui" "ui-backup"
  if exist "%~dp0_internal\ui" robocopy "%~dp0_internal\ui" "%~dp0ui" /E /NFL /NDL /NJH /NJS /NP >nul
  if not exist "%~dp0ui" robocopy "%~dp0ui-backup" "%~dp0ui" /E /NFL /NDL /NJH /NJS /NP >nul
  echo 1.0.3 > "%~dp0ui\.version"
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
