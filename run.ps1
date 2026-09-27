# Tek tuşla demo: simülatör + API (NAC_MODE=simulator). Yalnızca bellek içi fixture için: .\run.ps1 -Mode fixture
param([ValidateSet("simulator", "fixture")][string]$Mode = "simulator", [int]$ApiPort = 8000, [int]$SimPort = 8081)
$ErrorActionPreference = "Stop"
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$env:PYTHONPATH = "$PSScriptRoot\src"
$env:NAC_MODE = $Mode
if (-not $env:PUBLIC_BASE_URL) { $env:PUBLIC_BASE_URL = "http://127.0.0.1:$ApiPort" }
$sim = $null
if ($Mode -eq "simulator") {
  $env:NAC_BASE_URL = "http://127.0.0.1:$SimPort"
  $sim = Start-Process -NoNewWindow -PassThru $py -ArgumentList "-m", "uvicorn", "arrivalguard.simulator.app:app", "--port", "$SimPort", "--log-level", "warning" -WorkingDirectory $PSScriptRoot
  Start-Sleep -Seconds 1
}
Write-Host "Demo:    http://127.0.0.1:$ApiPort/demo"
Write-Host "Konsol:  http://127.0.0.1:$ApiPort/console   API belgesi: /docs   mode=$Mode"
try { & $py -m uvicorn arrivalguard.api.app:create_app --factory --port $ApiPort }
finally { if ($sim) { Stop-Process -Id $sim.Id -Force -ErrorAction SilentlyContinue } }
