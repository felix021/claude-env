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

function Get-PythonCommand {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3 --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return "py -3"
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return "python"
        }
    }

    return $null
}

$PythonCommand = Get-PythonCommand
if (-not $PythonCommand) {
    Write-Error "Python 3 is required. Install it with: winget install Python.Python.3.12"
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
