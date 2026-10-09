$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
if (Get-NetTCPConnection -LocalPort 8000,3000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 or 3000 is already in use. Stop the existing instance first.'
}
New-Item -ItemType Directory -Path data -Force | Out-Null
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$taskNode = (Get-Command node).Source
$taskNext = Join-Path $taskRoot 'frontend/node_modules/next/dist/bin/next'
$backendProcess = Start-Process -FilePath $taskPython -ArgumentList '-m','uvicorn','app.api:app','--host','127.0.0.1','--port','8000','--workers','1' -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'data/backend.log' -RedirectStandardError 'data/backend-error.log'
$frontendProcess = Start-Process -FilePath $taskNode -ArgumentList ('"' + $taskNext + '"'),'start','--hostname','127.0.0.1' -WorkingDirectory (Join-Path $taskRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput 'data/frontend.log' -RedirectStandardError 'data/frontend-error.log'
@{backend=$backendProcess.Id; frontend=$frontendProcess.Id; root=$taskRoot} | ConvertTo-Json | Set-Content -LiteralPath 'data/processes.json'
$taskReady = $false
for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        $null = Invoke-WebRequest -Uri 'http://localhost:3000' -TimeoutSec 2 -UseBasicParsing
        $taskReady = $true
        break
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $taskReady) {
    & (Join-Path $PSScriptRoot 'stop.ps1')
    throw 'Services did not become ready. Inspect data/backend-error.log and data/frontend-error.log.'
}
Write-Host 'Daybreak: http://localhost:3000 | API: http://127.0.0.1:8000/docs'
Write-Host 'Logs: data/. Stop using scripts/stop.ps1.'
