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
$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

"[$stamp] START run" | Out-File -FilePath $logFile -Encoding utf8 -Append

try {
    & $PythonPath "app.py" "--config" $resolvedConfigPath *>> $logFile
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
