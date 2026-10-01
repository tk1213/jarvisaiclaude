# Registers the daily JARVIS backup in Windows Task Scheduler. Run it through backup-schedule.bat.
# The task runs backup.py --auto at 12:00 and 10 minutes after logging on; a run missed while the computer was off
# happens as soon as it's back on. --auto does nothing once today's backup is done, so it backs up once a day.
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$name = 'JARVIS Backup'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Removed the '$name' task."
    exit 0
}

$backend = Join-Path $PSScriptRoot 'backend'
$pythonw = Join-Path $backend '.venv\Scripts\pythonw.exe'  # pythonw: no console window pops up
if (-not (Test-Path $pythonw)) {
    Write-Host "Not found: $pythonw (set up backend\.venv first - see README.md)"
    exit 1
}
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m app.scripts.backup --auto' -WorkingDirectory $backend
$daily = New-ScheduledTaskTrigger -Daily -At '12:00'
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = 'PT10M'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $daily, $logon -Settings $settings -Principal $principal `
    -Description 'JARVIS daily backup: code, backend\.env, jarvis.db, catalog.db (app.scripts.backup)' -Force | Out-Null

Write-Host "Set up '$name': once a day (12:00, or after logging on / as soon as the computer is back on)."
Write-Host 'Making the first backup now...'
Start-ScheduledTask -TaskName $name
Start-Sleep -Seconds 20
$info = Get-ScheduledTaskInfo -TaskName $name
Write-Host "Last run: $($info.LastRunTime)  result: $($info.LastTaskResult) (0 = OK, 267009 = still running)"
Write-Host 'Backups and backup.log are in the BACKUP_DIR folder (default D:\JarvisClaudeBackup).'
