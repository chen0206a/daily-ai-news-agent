$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { python -m venv .venv }
& '.venv/Scripts/python.exe' -m pip install -r backend/requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed' }
& '.venv/Scripts/python.exe' -m pip install --no-deps -e './backend[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Backend install failed' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Push-Location frontend
try {
    npm ci --cache ../.npm-cache
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
Write-Host 'Ready. Configure .env, then run scripts/start.ps1.'
