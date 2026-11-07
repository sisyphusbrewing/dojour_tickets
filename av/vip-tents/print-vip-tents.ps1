# Prints each show's VIP table tents on the office printer, 90 minutes before
# showtime (Sam, Nov 6 2026). Runs every 10 minutes from Task Scheduler on the
# office PC (DESKTOP-8QOGQGK). Each showtime prints once; tents use the name the
# guest gave on the VIP form, or the name on the order if they didn't answer.
#
# Needs: C:\Sisyphus\vip-tents\key.txt (the PC's private key for the
# vip_tents_for_day lookup), Microsoft Edge, SumatraPDF.
#   Install the task:  powershell -ExecutionPolicy Bypass -File print-vip-tents.ps1 -Install
#   Test without printing:  ... -File print-vip-tents.ps1 -DryRun

param([switch]$Install, [switch]$DryRun, [int]$LeadMinutes = 90)

$ErrorActionPreference = 'Stop'
$Dir      = 'C:\Sisyphus\vip-tents'
$Printer  = 'Brother DCP-L2640DW Printer'
$Url      = 'https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc'
$Anon     = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ'
$Log      = Join-Path $Dir 'print-log.txt'

if ($Install) {
  $action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`""
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 10)
  Register-ScheduledTask -TaskName 'Sisyphus VIP tents' -Action $action -Trigger $trigger -Force `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries) | Out-Null
  Write-Output 'Installed scheduled task "Sisyphus VIP tents" (every 10 minutes).'
  return
}

function Say($m) { $line = "$(Get-Date -Format s)  $m"; Add-Content -Path $Log -Value $line; Write-Output $line }
function Rpc($fn, $body) {
  Invoke-RestMethod -Method Post -Uri "$Url/$fn" -ContentType 'application/json; charset=utf-8' `
    -Headers @{ apikey = $Anon; Authorization = "Bearer $Anon" } -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json)))
}
function Esc($s) { [System.Net.WebUtility]::HtmlEncode([string]$s) }

$key = (Get-Content (Join-Path $Dir 'key.txt') -Raw).Trim()
$us  = [Globalization.CultureInfo]::GetCultureInfo('en-US')
$now = Get-Date
# Shows after midnight still belong to the night before (e.g. a 12:30 AM late show).
$day = $now.ToString('ddd, MMM d', $us)
$rows = @(Rpc 'vip_tents_for_day' @{ p_key = $key; p_day = $day })

foreach ($g in ($rows | Group-Object show_date, show_title)) {
  $first = $g.Group[0]
  if ($first.printed) { continue }
  $timeText = ($first.show_date -split '•')[1].Trim()            # "7:00 PM"
  $start = [datetime]::ParseExact("$($now.ToString('yyyy-MM-dd')) $timeText", 'yyyy-MM-dd h:mm tt', $us)
  if ($now -lt $start.AddMinutes(-$LeadMinutes) -or $now -gt $start.AddMinutes(30)) { continue }

  $slug  = ($first.show_date -replace '[^A-Za-z0-9]+', '-').Trim('-').ToLower()
  $html  = Join-Path $Dir "$slug.html"; $pdf = Join-Path $Dir "$slug.pdf"
  $foot  = "SISYPHUS &nbsp;&middot;&nbsp; $(Esc $first.show_title) &nbsp;&middot;&nbsp; $(Esc $first.show_date)"
  $pages = foreach ($t in ($g.Group | Sort-Object tent_name)) {
    $name = [string]$t.tent_name; $occ = [string]$t.occasion
    if ($occ -match '^(birthday|anniversary|bachelorette|retirement|graduation)') { $occ = "Happy $occ" }
    $size = if ($name.Length -le 10) { 96 } elseif ($name.Length -le 16) { 78 } elseif ($name.Length -le 24) { 60 } else { 46 }
    $half = "<div class='eyebrow'>Reserved for</div><div class='name' style='font-size:${size}px'>$(Esc $name)</div><div class='occ'>$(Esc $occ)</div><div class='show'>$foot</div>"
    "<div class='page'><div class='half top'>$half</div><div class='fold'></div><div class='half bottom'>$half</div></div>"
  }
  @"
<!doctype html><html><head><meta charset='utf-8'><style>
@page { size: letter landscape; margin: 0 } * { box-sizing: border-box } body { margin: 0; font-family: 'Segoe UI', Arial, sans-serif; color: #2b2929 }
.page { width: 11in; height: 8.5in; position: relative; overflow: hidden; page-break-after: always; break-after: page }
.half { position: absolute; left: 0; right: 0; height: 4.25in; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: .35in .6in }
.top { top: 0; transform: rotate(180deg) } .bottom { bottom: 0 }
.fold { position: absolute; left: .3in; right: .3in; top: 4.25in; border-top: 1px dashed #bbb }
.eyebrow { font-weight: 700; letter-spacing: .3em; text-transform: uppercase; font-size: 16px; color: #4a6c86 }
.name { font-weight: 700; line-height: 1.05; margin: 10px 0 8px; word-break: break-word }
.occ { font-size: 24px; color: #4a6c86; font-weight: 600; min-height: 30px }
.show { margin-top: 14px; font-size: 15px; color: #918f90; letter-spacing: .04em }
</style></head><body>$($pages -join '')</body></html>
"@ | Set-Content -Path $html -Encoding UTF8

  $edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  & $edge --headless --disable-gpu --no-pdf-header-footer "--print-to-pdf=$pdf" ("file:///" + ($html -replace '\\', '/')) | Out-Null
  Start-Sleep -Seconds 3
  if (-not (Test-Path $pdf)) { Say "PDF failed for $($first.show_date)"; continue }

  if ($DryRun) { Say "DRY RUN: would print $($g.Count) tents for $($first.show_title) $($first.show_date) ($pdf)"; continue }
  $sumatra = @("$env:LOCALAPPDATA\SumatraPDF\SumatraPDF.exe", "$env:ProgramFiles\SumatraPDF\SumatraPDF.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  & $sumatra -print-to $Printer -print-settings 'fit,landscape' -silent $pdf
  Rpc 'vip_tents_printed' @{ p_key = $key; p_show_date = $first.show_date; p_show_title = $first.show_title } | Out-Null
  Say "Printed $($g.Count) tents for $($first.show_title) $($first.show_date)"
}
