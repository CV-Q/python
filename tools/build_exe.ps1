param(
    [switch]$NoClean,
    [switch]$NoConfirm,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $ProjectRoot 'venv\Scripts\python.exe'
$SpecFile = Join-Path $ProjectRoot 'poi_fetcher_gui.spec'
$DistDir = Join-Path $ProjectRoot 'dist'

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}
if (-not (Test-Path $SpecFile)) {
    throw "Spec file not found: $SpecFile"
}

$pyArgs = @('-m', 'PyInstaller')
if (-not $NoClean) {
    $pyArgs += '--clean'
}
if (-not $NoConfirm) {
    $pyArgs += '--noconfirm'
}
$pyArgs += $SpecFile

Write-Host "Project root: $ProjectRoot"
Write-Host "Python: $PythonExe"
Write-Host "Spec: $SpecFile"
Write-Host "Command: $PythonExe $($pyArgs -join ' ')"

if ($DryRun) {
    Write-Host 'DryRun enabled, skip packaging.'
    exit 0
}

Push-Location $ProjectRoot
try {
    & $PythonExe @pyArgs
} finally {
    Pop-Location
}

$exePath = Join-Path $DistDir 'poi_fetcher_gui\poi_fetcher_gui.exe'
if (Test-Path $exePath) {
    Write-Host "Build success: $exePath"
} else {
    Write-Host "Build finished. Check dist output: $DistDir"
}
