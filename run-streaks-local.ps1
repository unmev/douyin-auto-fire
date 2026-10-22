param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot ".playwright-browsers"
$env:PIP_CACHE_DIR = Join-Path $projectRoot ".pip-cache"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

& $python (Join-Path $projectRoot "scripts\prepare_streak_config.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$arguments = @((Join-Path $projectRoot "run.py"))
if ($DryRun) {
    $arguments += "--dry-run"
}

& $python @arguments
exit $LASTEXITCODE
