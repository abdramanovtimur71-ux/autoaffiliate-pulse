param(
    [string]$PythonPath = "",
    [string]$ConfigPath = "config.json"
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
        $PythonPath = "C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe"
    }
}

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logFile = Join-Path $logDir "autopulse.log"
$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

"[$stamp] START run" | Out-File -FilePath $logFile -Encoding utf8 -Append

try {
    & $PythonPath "app.py" "--config" $ConfigPath *>> $logFile
    $exitCode = $LASTEXITCODE
    $stampOk = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "[$stampOk] END run exit=$exitCode" | Out-File -FilePath $logFile -Encoding utf8 -Append
    exit $exitCode
}
catch {
    $stampErr = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "[$stampErr] ERROR $($_.Exception.Message)" | Out-File -FilePath $logFile -Encoding utf8 -Append
    throw
}
