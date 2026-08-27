param([string]$CoreDir = "")
# Stop this instance's core server node processes (matched by core-dir path in the command line).
$ErrorActionPreference = "SilentlyContinue"
$coreF = ($CoreDir -replace '\\', '/').TrimEnd('/')
$coreB = $CoreDir.TrimEnd('\')
$ef = [WildcardPattern]::Escape($coreF)
$eb = [WildcardPattern]::Escape($coreB)
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Where-Object {
    $cl = $_.CommandLine
    if (-not $cl) { return $false }
    ($cl -like "*$ef*apps/cli/lib/bin.js*") -or ($cl -like "*$eb*apps\cli\lib\bin.js*")
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }