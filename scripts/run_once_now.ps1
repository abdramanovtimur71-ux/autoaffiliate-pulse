$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$runner = Join-Path $root "scripts\run_autopulse.ps1"

& $runner
Write-Output "Run completed."
