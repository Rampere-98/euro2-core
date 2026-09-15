# Registers euro2-core as a Windows scheduled task that starts at logon and restarts if it
# stops, so the catalog, prices and news keep updating without anyone touching it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -Uninstall
#
# Requires Docker Desktop to start with Windows (Settings -> General) for PostgreSQL.

param([switch]$Uninstall)

$TaskName = "euro2-core"
$Root = Split-Path -Parent $PSScriptRoot
$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) { throw "uv not found on PATH" }

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task $TaskName"
    exit 0
}

$Action = New-ScheduledTaskAction -Execute $Uv -Argument "run python -m euro2core serve" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Trigger.Delay = "PT1M"  # give Docker Desktop a minute to bring PostgreSQL up
$Settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "euro2-core registered as task '$TaskName': API + app at http://localhost:8000/app/ and the scheduler run at every logon."
