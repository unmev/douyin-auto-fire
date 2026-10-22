$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot ".playwright-browsers"
$env:PIP_CACHE_DIR = Join-Path $projectRoot ".pip-cache"

& (Join-Path $projectRoot ".venv\Scripts\python.exe") (Join-Path $projectRoot "scripts\login.py")
exit $LASTEXITCODE
