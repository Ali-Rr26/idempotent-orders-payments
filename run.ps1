# Starts both services locally, each in its own PowerShell window.
# Usage: .\run.ps1   (creates .venv and installs dependencies on first run)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment in .venv ..."
    py -3 -m venv (Join-Path $root ".venv")
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

$services = @(
    @{ Name = "payment-mock"; Dir = "payment_mock_api"; Port = 5001 },
    @{ Name = "order-api";    Dir = "order_api";        Port = 5000 }
)

foreach ($svc in $services) {
    $dir = Join-Path $root $svc.Dir
    $title = "$($svc.Name) :$($svc.Port)"
    Start-Process powershell -WorkingDirectory $dir -ArgumentList @(
        "-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle = '$title'; & '$python' app.py"
    )
    Write-Host "Started $title"
}

Write-Host "Order API:   http://localhost:5000/health"
Write-Host "Payment Mock: http://localhost:5001/health"
