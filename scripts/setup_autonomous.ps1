param(
    [string]$TaskName = "AutoAffiliatePulse-Every3Hours",
    [int]$EveryHours = 3,
    [string]$PythonPath = "",
    [string]$ConfigPath = "config.json",
    [switch]$RunAsCurrentUser
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

if (-not (Test-Path $ConfigPath)) {
    if (Test-Path "config.example.json") {
        Copy-Item -Path "config.example.json" -Destination $ConfigPath -Force
        Write-Output "Created $ConfigPath from config.example.json"
    }
    else {
        throw "config.example.json not found in project root"
    }
}

$setupScheduler = Join-Path $root "scripts\setup_scheduler.ps1"
$runNow = Join-Path $root "scripts\run_once_now.ps1"

if (-not (Test-Path $setupScheduler)) {
    throw "Missing script: $setupScheduler"
}
if (-not (Test-Path $runNow)) {
    throw "Missing script: $runNow"
}

& $setupScheduler -TaskName $TaskName -EveryHours $EveryHours -PythonPath $PythonPath -ConfigPath $ConfigPath -RunAsCurrentUser:$RunAsCurrentUser
& $runNow

Write-Output "Autonomous mode is enabled."
Write-Output "Task: $TaskName"
Write-Output "Interval: every $EveryHours hour(s)"
