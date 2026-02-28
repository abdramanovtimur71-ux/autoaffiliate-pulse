param(
    [string]$TaskName = "AutoAffiliatePulse-Every3Hours",
    [int]$EveryHours = 3,
    [string]$PythonPath = "",
    [string]$ConfigPath = "config.json",
    [switch]$RunAsCurrentUser
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = Join-Path $root "scripts\run_autopulse.ps1"

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonPath = $venvPython
    }
    else {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd) {
            $PythonPath = $pythonCmd.Source
        }
        else {
            throw "Python not found. Install Python 3.10+ or create .venv"
        }
    }
}

$resolvedConfigPath = Join-Path $root $ConfigPath

if (-not (Test-Path $runner)) {
    throw "Runner script not found: $runner"
}

$pwshCmd = (Get-Command pwsh -ErrorAction SilentlyContinue)
$hostPath = if ($pwshCmd) { $pwshCmd.Source } else { "powershell.exe" }

$launcherDir = Join-Path $env:ProgramData "AutoAffiliatePulse"
if (-not (Test-Path $launcherDir)) {
    New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
}

$launcherPath = Join-Path $launcherDir "run_task.ps1"
$launcherContent = @"
`$ErrorActionPreference = "Stop"
& '$runner' -PythonPath '$PythonPath' -ConfigPath '$resolvedConfigPath'
"@
Set-Content -Path $launcherPath -Value $launcherContent -Encoding utf8

$taskCommand = "`"$hostPath`" -NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""

function New-ScheduledTaskEntry {
    param(
        [string]$Mode
    )

    if ($Mode -eq "system") {
        schtasks /Create /F /SC HOURLY /MO $EveryHours /TN $TaskName /TR $taskCommand /RU SYSTEM | Out-Null
    }
    else {
        schtasks /Create /F /SC HOURLY /MO $EveryHours /TN $TaskName /TR $taskCommand | Out-Null
    }

    return ($LASTEXITCODE -eq 0)
}

function Get-TaskRunMode {
    param(
        [string]$Mode
    )

    if ($Mode -eq "system") {
        return "SYSTEM (works without user logon)"
    }
    return "current interactive user"
}

function Finalize-SetupOutput {
    param(
        [string]$Mode
    )

    Write-Output "Scheduled task created/updated: $TaskName"
    Write-Output "Interval: every $EveryHours hour(s)"
    Write-Output "Run account: $(Get-TaskRunMode -Mode $Mode)"
    Write-Output "Command: $taskCommand"
}

if ($RunAsCurrentUser) {
    if (-not (New-ScheduledTaskEntry -Mode "user")) {
        throw "Failed to create task for current user"
    }
    Finalize-SetupOutput -Mode "user"
}
else {
    if (New-ScheduledTaskEntry -Mode "system") {
        Finalize-SetupOutput -Mode "system"
    }
    else {
        Write-Warning "SYSTEM mode is unavailable (likely no admin rights). Falling back to current user mode."
        if (-not (New-ScheduledTaskEntry -Mode "user")) {
            throw "Failed to create task in both SYSTEM and current user modes"
        }
        Finalize-SetupOutput -Mode "user"
    }
}
