param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$relayProjectRoot = Split-Path -Parent $PSScriptRoot
$relayPython = Join-Path $relayProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $relayPython -PathType Leaf)) {
    throw 'Project Python environment is missing. Follow the README setup commands first.'
}

Push-Location -LiteralPath $relayProjectRoot
try {
    Write-Host "FieldSight spatial simulator: http://127.0.0.1:$Port/simulator"
    Write-Host "FieldSight mission lab: http://127.0.0.1:$Port/"
    Write-Host 'Mock requests only. No physical robot commands. Press Ctrl+C to stop.'
    & $relayPython -m uvicorn relay_gateway.api:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "FieldSight server exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
