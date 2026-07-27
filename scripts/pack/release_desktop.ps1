# Release DClaw desktop artifacts to domestic OSS. Run from repo root.
$ErrorActionPreference = "Stop"
$ScriptPath = Join-Path $PSScriptRoot "desktop_release.py"
python $ScriptPath @args
