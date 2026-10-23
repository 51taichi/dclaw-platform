$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonCommand = $null
$PythonPrefix = @()

if ($env:PYTHON) {
    $PythonCommand = $env:PYTHON
}

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $PythonCommand -and $PyLauncher) {
    foreach ($Version in @("3.13", "3.12", "3.11", "3.10")) {
        & $PyLauncher.Source "-$Version" -c "import sys; raise SystemExit(0)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonCommand = $PyLauncher.Source
            $PythonPrefix = @("-$Version")
            break
        }
    }
}

if (-not $PythonCommand) {
    foreach ($Candidate in @("python3.13", "python3.12", "python3.11", "python3.10", "python")) {
        $Python = Get-Command $Candidate -ErrorAction SilentlyContinue
        if (-not $Python) { continue }
        & $Python.Source -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 14) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonCommand = $Python.Source
            break
        }
    }
}

if (-not $PythonCommand) {
    throw "CPython 3.10-3.13 is required."
}

& $PythonCommand @PythonPrefix "$Root\dclaw_agent_devkit.py" doctor --wheelhouse-only
if ($LASTEXITCODE -ne 0) { throw "DevKit wheelhouse verification failed." }

$VenvDir = "$Root\.venv"
& $PythonCommand @PythonPrefix -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { throw "Unable to create the DevKit virtual environment." }

$VenvPython = "$VenvDir\Scripts\python.exe"
& $VenvPython -m pip install `
    --disable-pip-version-check `
    --no-index `
    --find-links "$Root\wheelhouse" `
    --require-hashes `
    -r "$Root\requirements.lock"
if ($LASTEXITCODE -ne 0) { throw "Unable to install bundled DevKit dependencies." }

& $VenvPython "$Root\dclaw_agent_devkit.py" doctor
if ($LASTEXITCODE -ne 0) { throw "DevKit post-install verification failed." }

Write-Output "DevKit ready: $VenvPython"
