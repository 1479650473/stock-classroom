# register_daily_task.ps1 - register/repair the daily data update task.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
#
# Key settings:
#   - StartWhenAvailable: if the scheduled time was missed (PC off/asleep),
#     run as soon as the machine is available. Combined with update_daily's
#     "catchup audit" this backfills data missed while the PC was off.
#   - AllowStartIfOnBatteries / DontStopIfGoingOnBatteries: never skip on battery.
#   - ExecutionTimeLimit 10h: full-market run + anti-crawl retries + catchup
#     must not be killed by the old 3h limit.
# Idempotent: Register-ScheduledTask -Force.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot   # scripts/ -> project root
$bat = Join-Path $root 'backend\update_daily.bat'
if (-not (Test-Path $bat)) { throw "not found: $bat" }

$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '17:00'
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 10) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName 'StockClassroom-DailyUpdate' `
    -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

$t = Get-ScheduledTask -TaskName 'StockClassroom-DailyUpdate'
Write-Host "Registered task StockClassroom-DailyUpdate"
Write-Host "  action: $bat"
Write-Host "  trigger: daily 17:00 (missed run will catch up)"
$t.Settings | Select-Object StartWhenAvailable, AllowStartIfOnBatteries,
    StopIfGoingOnBatteries, ExecutionTimeLimit | Format-List