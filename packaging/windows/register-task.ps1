# Run SFTP Pilot's scheduled tasks from Windows Task Scheduler.
#
#   powershell -ExecutionPolicy Bypass -File register-task.ps1            # every 5 minutes
#   powershell -ExecutionPolicy Bypass -File register-task.ps1 -Minutes 15
#   powershell -ExecutionPolicy Bypass -File register-task.ps1 -Remove
#
# The task starts sftp-pilot-gui.exe --run-due, which has no console window, so
# nothing flashes on screen. It runs the tasks that are due and exits (see the
# README for the exit codes). By default it runs while you are logged on. To run
# when nobody is logged on, use an elevated PowerShell and pass -RunWhenLoggedOff
# (Windows refuses that registration without administrator rights).
#
# Author: Pandiyaraj Karuppasamy
# Date: Oct-18-2026
param(
    [string]$InstallDir = $PSScriptRoot,
    [string]$DataDir    = (Join-Path $env:APPDATA "SFTP Pilot"),
    [string]$TaskName   = "SFTP Pilot run-due",
    [int]$Minutes       = 5,
    [switch]$RunWhenLoggedOff,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed '$TaskName'."
    } else {
        Write-Host "'$TaskName' is not registered."
    }
    return
}

if ($Minutes -lt 1) { throw "-Minutes must be at least 1." }
$exe = Join-Path $InstallDir "sftp-pilot-gui.exe"
$config = Join-Path $DataDir "config.ini"
if (-not (Test-Path $exe))    { throw "Cannot find $exe. Pass -InstallDir, or run this from the installed folder." }
if (-not (Test-Path $config)) { throw "Cannot find $config. Run install.ps1 first, or pass -DataDir." }

$action  = New-ScheduledTaskAction -Execute $exe -Argument "-c `"$config`" --run-due" -WorkingDirectory $DataDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)

if ($RunWhenLoggedOff) {
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
            -Principal $principal -Force | Out-Null
    } catch {
        throw "Windows refused to register a task that runs when nobody is logged on: $($_.Exception.Message) Open PowerShell with 'Run as administrator' and run this again."
    }
    $mode = "whether or not you are logged on"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    $mode = "while you are logged on"
}

Write-Host "Registered '$TaskName': every $Minutes minute(s), $mode."
Write-Host "Settings: $config"
Write-Host "See what it did:  & `"$(Join-Path $InstallDir 'sftp-pilot.exe')`" -c `"$config`" --history"
Write-Host "Check the result: Get-ScheduledTaskInfo '$TaskName'   (LastTaskResult 0 = ok, 1 = a task failed, 2 = config error)"
Write-Host "Remove it:        powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Remove"
