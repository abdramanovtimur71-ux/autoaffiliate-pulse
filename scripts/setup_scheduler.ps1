param(
    [string]$TaskName = "AutoAffiliatePulse-Every3Hours",
    [int]$EveryHours = 3,
    [string]$PythonPath = "C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe",
    [string]$ConfigPath = "config.json"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = Join-Path $root "scripts\run_autopulse.ps1"

if (-not (Test-Path $runner)) {
    throw "Runner script not found: $runner"
}

$pwshCmd = (Get-Command pwsh -ErrorAction SilentlyContinue)
$hostPath = if ($pwshCmd) { $pwshCmd.Source } else { "powershell.exe" }

$taskCommand = "`"$hostPath`" -NoProfile -ExecutionPolicy Bypass -File `"$runner`" -PythonPath `"$PythonPath`" -ConfigPath `"$ConfigPath`""

schtasks /Create /F /SC HOURLY /MO $EveryHours /TN $TaskName /TR $taskCommand | Out-Null

Write-Output "Scheduled task created/updated: $TaskName"
Write-Output "Interval: every $EveryHours hour(s)"
Write-Output "Command: $taskCommand"
