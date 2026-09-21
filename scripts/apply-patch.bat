@echo off
rem DeepSeek Harness 1.0.5 增量补丁（双击运行）
rem 默认：若实例正在运行则提示先关闭；加 /stop 可让补丁自行关闭实例后打补丁。
setlocal
cd /d "%~dp0"
set "EXTRA="

echo ============================================================
echo   DeepSeek Harness 1.0.5 增量补丁
echo ============================================================
echo.
echo 补丁会：
echo   * 更新启动器 exe / _internal / 外壳 UI / post-update.bat
echo   * 随包商店插件 dshmarket 1.33.0 -^> 1.50.0（删除旧包）
echo   * 清理与新内核 0.1.6 不兼容的旧 dsh-web 插件
echo   * 修改前自动备份到 patch-backup-*
echo.
echo 实例正在运行时必须先关闭（或在下一步选择让它自动关闭）。
echo.

if /i "%~1"=="/stop" set "EXTRA=-StopApp"
if /i "%~1"=="/dry" set "EXTRA=-DryRun"

if "%EXTRA%"=="" (
  set /p ANSWER=是否让补丁自动关闭正在运行的 DeepSeek Harness？(y/N^) 
  if /i "%ANSWER%"=="y" set "EXTRA=-StopApp"
)

if "%EXTRA%"=="-StopApp" (
  echo.
  echo 将先关闭实例再打补丁。
) else (
  echo.
  echo 只进行校验；若实例正在运行，补丁会提示并退出，不会改动任何文件。
)

echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply-patch.ps1" %EXTRA%
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (
  echo 补丁执行完成。
) else if "%CODE%"=="2" (
  echo 实例正在运行，未做任何改动。请关闭应用后重试，或用「应用补丁-自动关闭实例.bat」。
) else (
  echo 补丁返回代码 %CODE%，请查看上方输出；备份目录在安装目录的 patch-backup-* 下。
)
echo.
pause
exit /b %CODE%
