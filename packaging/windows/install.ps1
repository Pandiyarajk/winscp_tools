# Install SFTP Pilot for the current user. No administrator rights needed.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Program files go to %LOCALAPPDATA%\Programs\SFTP Pilot, your settings to
# %APPDATA%\SFTP Pilot (config.ini, scheduled tasks, history, known_hosts), and
# a Start menu shortcut is created. Running it again upgrades the program and
# keeps your settings.
#
# Author: Pandiyaraj Karuppasamy
# Date: Oct-18-2026
param(
    [string]$InstallDir   = (Join-Path $env:LOCALAPPDATA "Programs\SFTP Pilot"),
    [string]$DataDir      = (Join-Path $env:APPDATA "SFTP Pilot"),
    [string]$StartMenuDir = [Environment]::GetFolderPath("Programs"),
    [switch]$AddToPath,
    [switch]$NoShortcut
)
$ErrorActionPreference = "Stop"

$source = $PSScriptRoot
if (-not (Test-Path (Join-Path $source "sftp-pilot.exe"))) {
    throw "sftp-pilot.exe is not next to this script. Extract the whole zip first, then run install.ps1 from the extracted folder."
}

New-Item -ItemType Directory -Force $InstallDir, $DataDir | Out-Null

if ((Resolve-Path $source).Path -ne (Resolve-Path $InstallDir).Path) {
    try {
        Copy-Item -Path (Join-Path $source "*") -Destination $InstallDir -Recurse -Force
    } catch {
        throw "Could not copy the files into $InstallDir. Close SFTP Pilot (and any scheduled run) and try again. $($_.Exception.Message)"
    }
}

$gui = Join-Path $InstallDir "sftp-pilot-gui.exe"
$cli = Join-Path $InstallDir "sftp-pilot.exe"

# First run: write a starter config next to the data. Never overwrites an existing one.
$config = Join-Path $DataDir "config.ini"
if (-not (Test-Path $config)) {
    Push-Location $DataDir
    try { & $cli --init-config | Out-Null } finally { Pop-Location }
}

if (-not $NoShortcut) {
    New-Item -ItemType Directory -Force $StartMenuDir | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $StartMenuDir "SFTP Pilot.lnk"))
    $link.TargetPath       = $gui
    $link.WorkingDirectory = $DataDir
    $link.Description      = "SFTP Pilot: SFTP transfers and scheduler"
    $link.IconLocation     = "$gui,0"
    $link.Save()
}

if ($AddToPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($userPath -split ";" | Where-Object { $_ })
    if ($parts -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable("Path", (($parts + $InstallDir) -join ";"), "User")
        Write-Host "Added $InstallDir to your PATH (new terminals pick it up)."
    }
}

Write-Host ""
Write-Host "SFTP Pilot is installed."
Write-Host "  Program:   $InstallDir"
Write-Host "  Settings:  $DataDir"
Write-Host ""
Write-Host "Next:"
Write-Host "  1. Edit your server details:  notepad `"$config`""
Write-Host "  2. Start it from the Start menu (SFTP Pilot)."
Write-Host "  3. To run scheduled tasks without the window open:"
Write-Host "       powershell -ExecutionPolicy Bypass -File `"$InstallDir\register-task.ps1`""
Write-Host ""
Write-Host "This tool uploads, overwrites and deletes files on remote servers. See DISCLAIMER.md."
