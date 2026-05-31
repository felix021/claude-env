$ErrorActionPreference = "Stop"

$HomeDir = [Environment]::GetFolderPath("UserProfile")
$InstallDir = Join-Path $HomeDir ".local\bin"
$AppDir = Join-Path $HomeDir ".local\share\claude-env"
$Target = Join-Path $InstallDir "claude-env.cmd"
$SourceUrl = if ($env:CLAUDE_ENV_URL) {
    $env:CLAUDE_ENV_URL
} else {
    "https://github.com/felix021/claude-env/archive/refs/heads/main.zip"
}

function Test-PythonExe {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    & $Path --version *> $null
    return ($LASTEXITCODE -eq 0)
}

function Find-PythonFromPath {
    foreach ($Entry in ($env:Path -split ";")) {
        if (-not $Entry) { continue }
        $Candidate = Join-Path $Entry "python.exe"
        if (Test-PythonExe $Candidate) {
            return $Candidate
        }
    }
    return $null
}

$PythonCommand = $null

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py -3 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $PythonCommand = "py -3"
    }
}

if (-not $PythonCommand) {
    $Found = Find-PythonFromPath
    if ($Found) {
        $PythonCommand = $Found
    }
}

while (-not $PythonCommand) {
    Write-Host "No working Python found in PATH."
    Write-Host "Install Python 3 first: winget install Python.Python.3.12"
    Write-Host ""
    $UserPath = Read-Host "Or enter the full path to python.exe (e.g. C:\Python310\python.exe)"
    if ($UserPath -and (Test-PythonExe $UserPath)) {
        $PythonCommand = $UserPath
    } else {
        Write-Host "That path does not work. Try again or press Ctrl+C to exit." -ForegroundColor Red
    }
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

if ($env:CLAUDE_ENV_SOURCE_DIR) {
    $SourcePackage = Join-Path $env:CLAUDE_ENV_SOURCE_DIR "claude_env"
    Remove-Item -Recurse -Force $AppDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    Copy-Item -Recurse -Force $SourcePackage $AppDir
} else {
    $Temp = Join-Path ([System.IO.Path]::GetTempPath()) ("claude-env-" + [guid]::NewGuid())
    $Archive = Join-Path $Temp "claude-env.zip"
    New-Item -ItemType Directory -Force -Path $Temp | Out-Null
    try {
        Invoke-WebRequest -Uri $SourceUrl -OutFile $Archive
        Expand-Archive -Path $Archive -DestinationPath $Temp
        $SourceRoot = Get-ChildItem -Path $Temp -Directory | Where-Object { $_.Name -ne "__MACOSX" } | Select-Object -First 1
        if (-not $SourceRoot) {
            Write-Error "Downloaded archive did not contain a source directory."
        }
        Remove-Item -Recurse -Force $AppDir -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
        Copy-Item -Recurse -Force (Join-Path $SourceRoot.FullName "claude_env") $AppDir
    } finally {
        Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
    }
}

$Launcher = @"
@echo off
set "PYTHONPATH=$AppDir;%PYTHONPATH%"
$PythonCommand -m claude_env %*
"@
Set-Content -Path $Target -Value $Launcher -Encoding ASCII

Write-Output "installed $Target"

# Run one-time storage migration (v1 -> v2: move url/token from providers.json to env/)
$Env:CLAUDE_ENV_HOME = $HomeDir
$migrateScript = "import sys; sys.path.insert(0, '$AppDir'); from claude_env.cli import migrate_storage_v1_to_v2; migrate_storage_v1_to_v2()"
$Py = Get-Command py -ErrorAction SilentlyContinue
if ($Py) {
    & py -3 -c $migrateScript 2>$null
} else {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($Python) {
        & python -c $migrateScript 2>$null
    }
}
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathEntries = @()
if ($UserPath) {
    $PathEntries = $UserPath -split ";" | Where-Object { $_ }
}
if ($PathEntries -notcontains $InstallDir) {
    $NewUserPath = if ($UserPath) { "$InstallDir;$UserPath" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
    Write-Output "prepended $InstallDir to your user PATH."
} elseif ($PathEntries[0] -ne $InstallDir) {
    $Remaining = $PathEntries | Where-Object { $_ -ne $InstallDir }
    $NewUserPath = @($InstallDir) + $Remaining -join ";"
    [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
    Write-Output "moved $InstallDir to the front of your user PATH."
}
$env:Path = "$InstallDir;$env:Path"
