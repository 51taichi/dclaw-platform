$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
python (Join-Path $ScriptDir "dclaw_local.py") @args
exit $LASTEXITCODE
