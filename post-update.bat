@echo off
setlocal
echo 正在恢复核心组件链接...
if exist "%~dp0scripts\restore-junctions.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restore-junctions.ps1" "%~dp0core"
)
rem Refresh the shell UI whenever the live copy is not this release's build:
rem 1.0.4 refreshed only when ui\.version was missing, so every install that
rem already had the marker kept serving the old (buggy) UI after an upgrade.
rem The live folder is kept as ui-backup either way.
set "UI_CURRENT=0"
if exist "%~dp0ui\.version" findstr /x /c:"1.0.5" "%~dp0ui\.version" >nul 2>&1 && set "UI_CURRENT=1"
if "%UI_CURRENT%"=="0" (
  rem One-time snapshot of the pre-upgrade ui (the folder is ~150 KB): the shell
  rem UI is user-editable, so keep a copy the user can fall back to.
  if not exist "%~dp0ui-backup" if exist "%~dp0ui" robocopy "%~dp0ui" "%~dp0ui-backup" /E /NFL /NDL /NJH /NJS /NP >nul
  rem Merge the shipped ui over the live one: files we ship are refreshed,
  rem files the user added (custom.css etc.) are left untouched.
  if exist "%~dp0_internal\ui" robocopy "%~dp0_internal\ui" "%~dp0ui" /E /NFL /NDL /NJH /NJS /NP >nul
  rem Example shell plugins are not shipped since 1.0.5: drop them if present.
  for %%P in (example-status example-pet plugin-dev-kit) do (
    if exist "%~dp0ui\plugins\%%P" rmdir /s /q "%~dp0ui\plugins\%%P" >nul 2>&1
  )
  echo 1.0.5 > "%~dp0ui\.version"
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
