$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskFile = Join-Path $taskRoot 'data/processes.json'
if (-not (Test-Path -LiteralPath $taskFile)) { Write-Host 'No process record.'; exit }
$taskProcesses = Get-Content -LiteralPath $taskFile -Raw | ConvertFrom-Json
foreach ($taskPid in @($taskProcesses.backend, $taskProcesses.frontend)) {
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskPid" -ErrorAction SilentlyContinue
    if ($taskProcess -and ($taskProcess.CommandLine.Contains($taskRoot) -or $taskProcess.ExecutablePath.StartsWith($taskRoot))) {
        # Windows venv launchers may own a separate python child. Stop only verified project children.
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $taskPid" -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.CommandLine -and $_.CommandLine.Contains($taskRoot)) { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
        }
        Stop-Process -Id $taskPid
        Write-Host "Stopped project process $taskPid"
    }
}
