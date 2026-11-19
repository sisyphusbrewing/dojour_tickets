# Office PC check-in (Sam, Nov 18 2026). Runs every 10 minutes from the task
# "Sisyphus heartbeat" and at the end of each nightly backup. It tells the
# database "the PC is on", and Sam gets an email when it goes quiet for 30
# minutes (schedule_notify.py).
#
# It also puts the power settings back to never sleep and never hibernate,
# every time, because they have been changed back before (Sam: "someone
# probably changed it back thinking they were being helpful").
#
# The PC proves who it is with a random code in %USERPROFILE%\.sisyphus\heartbeat-code.txt;
# the database only has its fingerprint. The anon key below is the public one
# every staff page already carries.
param([object]$BackupOk = $null, [string]$Note = '')
$ErrorActionPreference = 'Continue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

foreach ($setting in 'standby-timeout-ac', 'hibernate-timeout-ac') { powercfg /change $setting 0 | Out-Null }

$url = 'https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/device_heartbeat'
$anon = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ'
$code = (Get-Content "$env:USERPROFILE\.sisyphus\heartbeat-code.txt" -Raw).Trim()
if (-not $Note) {
    $c = Get-PSDrive C
    $Note = "up $([math]::Round(((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalHours)) h, C: $([math]::Round($c.Free / 1GB)) GB free"
}
$body = @{ p_device = 'office-pc'; p_code = $code; p_note = $Note }
if ($null -ne $BackupOk -and "$BackupOk" -ne '') { $body.p_backup_ok = [bool]::Parse("$BackupOk") }
try {
    $ok = Invoke-RestMethod -Method Post -Uri $url -ContentType 'application/json' -TimeoutSec 30 `
        -Headers @{ apikey = $anon; Authorization = "Bearer $anon" } -Body ($body | ConvertTo-Json)
    if (-not $ok) { "$(Get-Date -Format s)  heartbeat refused (code doesn't match)" | Add-Content "$env:USERPROFILE\.sisyphus\heartbeat.log" }
} catch {
    "$(Get-Date -Format s)  heartbeat failed: $($_.Exception.Message)" | Add-Content "$env:USERPROFILE\.sisyphus\heartbeat.log"
}
