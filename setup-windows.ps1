$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirements = Join-Path $projectRoot "server\requirements.txt"
$webPath = Join-Path $projectRoot "web"

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Install-WingetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$DisplayName
    )

    Write-Host "Installing $DisplayName..." -ForegroundColor Cyan
    & winget install --exact --id $Id --source winget --silent `
        --accept-package-agreements --accept-source-agreements --disable-interactivity

    if ($LASTEXITCODE -ne 0) {
        throw "$DisplayName installation failed (winget exit code: $LASTEXITCODE)."
    }

    Refresh-ProcessPath
}

function Get-BunPath {
    $command = Get-Command bun -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:USERPROFILE ".bun\bin\bun.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\bun.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $packageRoot) {
        $packageBun = Get-ChildItem -LiteralPath $packageRoot -Filter "bun.exe" -File -Recurse `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($packageBun) {
            return $packageBun.FullName
        }
    }

    return $null
}

function Test-Endpoint {
    param([Parameter(Mandatory = $true)][string]$Uri)

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "")
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget was not found. Install App Installer from Microsoft Store, then run this script again."
}

Write-Host "=== Karaoke Engine setup ===" -ForegroundColor Green
Write-Host "Project: $projectRoot"

$python311Ready = $false
try {
    & py -3.11 --version *> $null
    $python311Ready = ($LASTEXITCODE -eq 0)
} catch {
    $python311Ready = $false
}

if (-not $python311Ready) {
    Install-WingetPackage -Id "Python.Python.3.11" -DisplayName "Python 3.11"
}

$bunPath = Get-BunPath
if (-not $bunPath) {
    Install-WingetPackage -Id "Oven-sh.Bun" -DisplayName "Bun"
    $bunPath = Get-BunPath
}
if (-not $bunPath) {
    throw "Bun was installed but bun.exe could not be located. Close PowerShell, reopen it, and run this script again."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Install-WingetPackage -Id "Gyan.FFmpeg" -DisplayName "FFmpeg"
}

$recreateVenv = $false
if (Test-Path -LiteralPath $venvPython) {
    $venvVersion = (& $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($venvVersion -ne "3.11") {
        $recreateVenv = $true
    }
} elseif (Test-Path -LiteralPath $venvPath) {
    $recreateVenv = $true
}

if ($recreateVenv) {
    $backupName = ".venv-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    $backupPath = Join-Path $projectRoot $backupName
    Write-Host "Backing up the existing virtual environment to $backupName" -ForegroundColor Yellow
    Move-Item -LiteralPath $venvPath -Destination $backupPath
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the Python 3.11 virtual environment..." -ForegroundColor Cyan
    & py -3.11 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Python virtual environment."
    }
}

$requirementsHash = Get-Sha256 -Path $requirements
$requirementsState = Join-Path $venvPath ".requirements.sha256"
$installedHash = ""
if (Test-Path -LiteralPath $requirementsState) {
    $installedHash = (Get-Content -LiteralPath $requirementsState -Raw).Trim()
}

$pythonDependenciesReady = $false
if ($installedHash -eq $requirementsHash) {
    & $venvPython -c "import fastapi, uvicorn, demucs, soundfile, torch" *> $null
    $pythonDependenciesReady = ($LASTEXITCODE -eq 0)
}

if (-not $pythonDependenciesReady) {
    Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
    & $venvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
    Set-Content -LiteralPath $requirementsState -Value $requirementsHash -NoNewline
}

$webEnvExample = Join-Path $webPath ".env.example"
$webEnv = Join-Path $webPath ".env"
if (-not (Test-Path -LiteralPath $webEnv)) {
    Copy-Item -LiteralPath $webEnvExample -Destination $webEnv
}

$packageJson = Join-Path $webPath "package.json"
$packageHash = Get-Sha256 -Path $packageJson
$nodeModules = Join-Path $webPath "node_modules"
$webState = Join-Path $nodeModules ".package.sha256"
$installedPackageHash = ""
if (Test-Path -LiteralPath $webState) {
    $installedPackageHash = (Get-Content -LiteralPath $webState -Raw).Trim()
}

if (-not (Test-Path -LiteralPath $nodeModules) -or $installedPackageHash -ne $packageHash) {
    Write-Host "Installing Web dependencies..." -ForegroundColor Cyan
    Push-Location $webPath
    try {
        & $bunPath install
        if ($LASTEXITCODE -ne 0) { throw "Bun dependency installation failed." }
        Set-Content -LiteralPath $webState -Value $packageHash -NoNewline
    } finally {
        Pop-Location
    }
}

$serverPath = Join-Path $projectRoot "server"
$apiCommand = @"
Set-Location -LiteralPath '$serverPath'
Write-Host 'Karaoke API: http://localhost:8000' -ForegroundColor Green
& '$venvPython' -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
"@

$webCommand = @"
Set-Location -LiteralPath '$webPath'
Write-Host 'Karaoke Web: http://localhost:3000' -ForegroundColor Green
& '$bunPath' dev
"@

$apiEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($apiCommand))
$webEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($webCommand))

Write-Host "Starting services..." -ForegroundColor Green
$apiRunning = Test-Endpoint -Uri "http://127.0.0.1:8000/api/health"
$webRunning = Test-Endpoint -Uri "http://127.0.0.1:3000"

if (-not $apiRunning) {
    Start-Process powershell.exe -WindowStyle Normal -ArgumentList @("-NoExit", "-EncodedCommand", $apiEncoded)
}
if (-not $webRunning) {
    Start-Process powershell.exe -WindowStyle Normal -ArgumentList @("-NoExit", "-EncodedCommand", $webEncoded)
}
if (-not $apiRunning -or -not $webRunning) {
    Start-Sleep -Seconds 4
}
Start-Process "http://localhost:3000"

Write-Host "Setup complete: http://localhost:3000" -ForegroundColor Green
