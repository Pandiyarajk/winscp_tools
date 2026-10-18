# Remove SFTP Pilot for the current user.
#
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1
#
# Removes the program, the Start menu shortcut, the PATH entry and the scheduled
# task. Your settings (config.ini with any passwords in it, tasks, history,
# known_hosts) are KEPT unless you pass -RemoveData. Secrets stored in the Windows
# keyring are not touched; remove them first with: sftp-pilot --forget-secrets
#
# Author: Pandiyaraj Karuppasamy
# Date: Oct-18-2026
param(
    [string]$InstallDir   = (Join-Path $env:LOCALAPPDATA "Programs\SFTP Pilot"),
    [string]$DataDir      = (Join-Path $env:APPDATA "SFTP Pilot"),
    [string]$StartMenuDir = [Environment]::GetFolderPath("Programs"),
    [string]$TaskName     = "SFTP Pilot run-due",
    [switch]$RemoveData
)
$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
}

$link = Join-Path $StartMenuDir "SFTP Pilot.lnk"
if (Test-Path $link) { Remove-Item $link -Force; Write-Host "Removed the Start menu shortcut." }

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$parts = @($userPath -split ";" | Where-Object { $_ })
if ($parts -contains $InstallDir) {
    [Environment]::SetEnvironmentVariable("Path", (($parts | Where-Object { $_ -ne $InstallDir }) -join ";"), "User")
    Write-Host "Removed $InstallDir from your PATH."
}

if (Test-Path $InstallDir) {
    try {
        Remove-Item -Recurse -Force $InstallDir
        Write-Host "Removed $InstallDir."
    } catch {
        Write-Warning "Could not remove $InstallDir (is SFTP Pilot still running?): $($_.Exception.Message)"
    }
}

if ($RemoveData) {
    if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir; Write-Host "Removed your settings in $DataDir." }
} elseif (Test-Path $DataDir) {
    Write-Host "Your settings are kept in $DataDir (use -RemoveData to delete them)."
}
