# BetsWin - start the engine and the dashboard together.
#
#   .\start.ps1              live markets
#   .\start.ps1 -Demo        offline fixtures, no network
#   .\start.ps1 -WebPort 3001 -ApiPort 8001
#
# Nothing here kills another process. If a port is taken the script moves to a
# free one and says so, and it pauses on failure rather than closing the window
# before you can read the error.

param(
    [switch]$Demo,
    [int]$ApiPort = 8000,
    [int]$WebPort = 3000
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$engine = $null
$startedEngine = $false

function Fail($message) {
    Write-Host ""
    Write-Host "Cannot start BetsWin" -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    Write-Host ""
    if ($Host.UI.RawUI -and -not [Console]::IsInputRedirected) {
        Write-Host "Press Enter to close..." -ForegroundColor DarkGray
        try { [Console]::ReadLine() | Out-Null } catch { }
    }
    exit 1
}

function Test-PortBusy([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $conn
}

function Get-FreePort([int]$Start) {
    $p = $Start
    for ($i = 0; $i -lt 40; $i++) {
        if (-not (Test-PortBusy $p)) { return $p }
        $p++
    }
    return $Start
}

function Test-EngineAlive([int]$Port) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        return $r.ok -eq $true
    } catch { return $false }
}

# ----------------------------------------------------------- prerequisites

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "Python is not on your PATH.`nInstall Python 3.11 or later, then reopen this terminal."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "Node.js is not on your PATH.`nInstall Node 18 or later, then reopen this terminal."
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Fail "The dashboard's dependencies are not installed. Run this first:`n`n    cd `"$root\frontend`"; npm install"
}
python -c "import fastapi, httpx, pydantic_settings" 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "The engine's Python dependencies are not installed. Run this first:`n`n    cd `"$root\backend`"; pip install -r requirements.txt"
}

$mode = if ($Demo) { "demo fixtures" } else { "live markets" }
Write-Host ""
Write-Host "BetsWin" -NoNewline -ForegroundColor White
Write-Host "  -  $mode" -ForegroundColor DarkGray

$env:DEMO_MODE = if ($Demo) { "true" } else { "false" }

# ------------------------------------------------------------ engine start

if (Test-PortBusy $ApiPort) {
    if (Test-EngineAlive $ApiPort) {
        Write-Host "An engine is already running on port $ApiPort - reusing it." -ForegroundColor Green
        Write-Host "  Stop it first if you wanted a fresh one with different settings." -ForegroundColor DarkGray
    } else {
        $newApi = Get-FreePort ($ApiPort + 1)
        Write-Host "Port $ApiPort is taken by something else; using $newApi instead." -ForegroundColor Yellow
        $ApiPort = $newApi
    }
}

if (-not (Test-EngineAlive $ApiPort)) {
    Write-Host "Starting the arbitrage engine on http://127.0.0.1:$ApiPort ..." -ForegroundColor Cyan
    $engine = Start-Process -FilePath "python" `
        -ArgumentList "-m", "arbengine.main", "--port", "$ApiPort" `
        -WorkingDirectory (Join-Path $root "backend") `
        -PassThru
    $startedEngine = $true

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-EngineAlive $ApiPort) { $ready = $true; break }
        if ($engine.HasExited) {
            Fail "The engine exited while starting up. Run it directly to see the error:`n`n    cd `"$root\backend`"; python -m arbengine.main --port $ApiPort"
        }
    }
    if (-not $ready) {
        Fail "The engine did not respond within 60 seconds.`nCheck $root\backend\logs\scanner.log for the reason."
    }
    Write-Host "Engine ready." -ForegroundColor Green
}

# --------------------------------------------------------- dashboard start

if (Test-PortBusy $WebPort) {
    $newWeb = Get-FreePort ($WebPort + 1)
    Write-Host "Port $WebPort is already in use; the dashboard will use $newWeb instead." -ForegroundColor Yellow
    Write-Host "  (Probably a dashboard you left running.)" -ForegroundColor DarkGray
    $WebPort = $newWeb
}

# Tell the frontend where the engine ended up, in case either port moved.
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$ApiPort"
$env:NEXT_PUBLIC_WS_URL = "ws://127.0.0.1:$ApiPort/ws"

Write-Host ""
Write-Host "Dashboard  ->  http://localhost:$WebPort" -ForegroundColor Green
Write-Host "API        ->  http://127.0.0.1:$ApiPort  (docs at /docs)" -ForegroundColor DarkGray
Write-Host "Press Ctrl-C to stop." -ForegroundColor DarkGray
Write-Host ""

try {
    Set-Location (Join-Path $root "frontend")
    $startedAt = Get-Date
    & npx next dev -p $WebPort
    $status = $LASTEXITCODE
    $ranFor = ((Get-Date) - $startedAt).TotalSeconds

    # A server that ran a while then stopped was shut down deliberately.
    # Only a fast exit means it never managed to start.
    if ($status -ne 0 -and $ranFor -lt 10) {
        Fail "The dashboard failed to start (exit status $status).`nIf it reported a port conflict, pick another port:`n`n    .\start.ps1 -WebPort $($WebPort + 1)$(if ($Demo) { ' -Demo' })"
    }
    Write-Host ""
    Write-Host "Dashboard stopped." -ForegroundColor DarkGray
}
finally {
    if ($startedEngine -and $null -ne $engine -and -not $engine.HasExited) {
        Stop-Process -Id $engine.Id -Force -ErrorAction SilentlyContinue
    }
}
