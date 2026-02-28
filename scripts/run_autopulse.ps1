param(
    [string]$PythonPath = "",
    [string]$ConfigPath = "config.json",
    [int]$MaxRetries = 2,
    [int]$RetryDelaySec = 25,
    [int]$LogMaxMB = 5
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

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

$resolvedConfigPath = if ([System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath
}
else {
    Join-Path $root $ConfigPath
}
if (-not (Test-Path $resolvedConfigPath)) {
    $exampleConfig = Join-Path $root "config.example.json"
    if (Test-Path $exampleConfig) {
        Copy-Item -Path $exampleConfig -Destination $resolvedConfigPath -Force
    }
    else {
        throw "Config not found: $resolvedConfigPath and config.example.json is missing"
    }
}

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logFile = Join-Path $logDir "autopulse.log"

if (Test-Path $logFile) {
    $logSizeBytes = (Get-Item $logFile).Length
    $maxBytes = [Math]::Max(1, $LogMaxMB) * 1MB
    if ($logSizeBytes -ge $maxBytes) {
        $archiveName = "autopulse-" + (Get-Date).ToString("yyyyMMdd-HHmmss") + ".log"
        $archivePath = Join-Path $logDir $archiveName
        Move-Item -Path $logFile -Destination $archivePath -Force
    }
}

$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

"[$stamp] START run" | Out-File -FilePath $logFile -Encoding utf8 -Append

try {
    $maxAttempts = [Math]::Max(1, $MaxRetries + 1)
    $finalExitCode = 1

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $attemptStamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        "[$attemptStamp] ATTEMPT $attempt/$maxAttempts" | Out-File -FilePath $logFile -Encoding utf8 -Append

        & $PythonPath "app.py" "--config" $resolvedConfigPath *>> $logFile
        $exitCode = $LASTEXITCODE
        $finalExitCode = $exitCode

        if ($exitCode -eq 0) {
            break
        }

        if ($attempt -lt $maxAttempts) {
            $retryStamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            "[$retryStamp] RETRY_WAIT ${RetryDelaySec}s after exit=$exitCode" | Out-File -FilePath $logFile -Encoding utf8 -Append
            Start-Sleep -Seconds ([Math]::Max(1, $RetryDelaySec))
        }
    }

    $stampOk = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "[$stampOk] END run exit=$finalExitCode" | Out-File -FilePath $logFile -Encoding utf8 -Append
    exit $finalExitCode
}
catch {
    $stampErr = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "[$stampErr] ERROR $($_.Exception.Message)" | Out-File -FilePath $logFile -Encoding utf8 -Append
    exit 1
}
