# Nightly backup on the office PC (Sam, Nov 18 2026: "Can we use my PC
# currently as a back up?"). Runs at 3:15 AM from the Task Scheduler task
# "Sisyphus backup", which pulls this file from main first, so a fix here
# reaches the PC without anyone touching it. backup/setup.ps1 sets it up.
#
# What it keeps, as restic snapshots on the PC's second drive (the 2 TB
# Seagate, D:): the show recordings and clips, the OBS and Companion
# settings, the Companion backups in Downloads, a copy of this repo and a
# dump of the staff database.
# restic keeps every night for two weeks, a week for two months and a month
# for a year, and stores each file only once, so 30 nights of the same
# recordings take the space of one.
#
# When it's done it tells the database whether it worked (device_heartbeat),
# and Sam gets an email if it failed or stops running (schedule_notify.py).
# The log says counts and sizes only, never file contents.

$ErrorActionPreference = 'Continue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$state = "$env:USERPROFILE\.sisyphus"
$conf = Get-Content "$state\backup.env" -ErrorAction Stop | ConvertFrom-StringData
$env:RESTIC_REPOSITORY = $conf.RESTIC_REPOSITORY
$env:RESTIC_PASSWORD_FILE = "$state\restic-pass.txt"
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$log = "$state\backup.log"
# winget installs restic as restic_<version>_windows_amd64.exe in its own
# package folder, which isn't always on PATH (found Nov 20 2026). Use the
# newest one there, so a winget upgrade is picked up by itself.
$restic = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\restic.restic*\restic*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $restic) { $restic = (Get-Command restic -ErrorAction Stop).Source }
$problems = @()
function Say($text) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $text" | Add-Content $log }

Say 'Backup starting.'

# A fresh copy of the repo (it's public, so no login is needed).
$staging = "$state\backup-staging"
New-Item -ItemType Directory -Force $staging | Out-Null
try {
    Invoke-WebRequest -UseBasicParsing 'https://github.com/sisyphusbrewing/dojour_tickets/archive/refs/heads/main.zip' -OutFile "$staging\dojour_tickets-main.zip"
} catch { $problems += 'repo download failed' }

# The staff database (tickets, schedule, clock, pay sheet, ...), with the
# read-only "backup_reader" login Sam OKed on Nov 18 2026. Its password is
# only in db-pass.txt on this PC. -Fc is pg_dump's own format, which
# pg_restore can put back whole or one table at a time.
$pgDump = "$env:USERPROFILE\sisyphus-backup\pgsql\bin\pg_dump.exe"
if ($conf.PG_HOST -and (Test-Path $pgDump) -and (Test-Path "$state\db-pass.txt")) {
    $env:PGPASSWORD = (Get-Content "$state\db-pass.txt" -Raw).Trim()
    $env:PGSSLMODE = 'require'
    & $pgDump -h $conf.PG_HOST -p 5432 -U $conf.PG_USER -d postgres -n public -Fc --no-owner --no-privileges -f "$staging\supabase-public.dump" 2>> $log
    if ($LASTEXITCODE -ne 0) { $problems += 'database dump failed' }
    else { Say "Database dump $([math]::Round((Get-Item "$staging\supabase-public.dump").Length / 1MB, 1)) MB." }
    Remove-Item Env:PGPASSWORD
} else { Say 'Database dump skipped (not set up yet).' }

# What to keep. A folder that isn't there is skipped, not an error.
$paths = @(@(
    "$env:USERPROFILE\Videos",               # OBS recordings + "Sisyphus clips"
    "$env:APPDATA\obs-studio",               # OBS scenes, profiles, settings
    "$env:APPDATA\companion",                # Stream Deck / Companion config
    "$state",                                # these settings + logs (the restic password stays out, below)
    $staging
) | Where-Object { Test-Path $_ })
$paths += Get-ChildItem "$env:USERPROFILE\Downloads\*" -File -Include 'companion-backup-*', 'sisyphus-deck-merged-*', 'companion-live-*' -ErrorAction SilentlyContinue | ForEach-Object FullName

$out = & $restic backup --tag nightly --exclude "$state\restic-pass.txt" --exclude "$state\heartbeat-code.txt" --exclude "$state\db-pass.txt" --exclude "$env:APPDATA\obs-studio\logs" --exclude "$env:APPDATA\obs-studio\crashes" @paths 2>&1
if ($LASTEXITCODE -ne 0) { $problems += "restic backup exit $LASTEXITCODE"; Say ($out | Select-Object -Last 5 | Out-String) }
else { Say (($out | Select-String 'Added to the repository|processed') -join ' | ') }

# Keep 14 nights, 8 weeks, 12 months; drop the rest.
& $restic forget --tag nightly --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune 2>&1 | Add-Content $log
if ($LASTEXITCODE -ne 0) { $problems += 'restic forget/prune failed' }

# Sundays: read back a slice of the stored data to prove it's still good.
if ((Get-Date).DayOfWeek -eq 'Sunday') {
    & $restic check --read-data-subset=5% 2>&1 | Add-Content $log
    if ($LASTEXITCODE -ne 0) { $problems += 'restic check found a problem' }
}

$drive = Get-PSDrive -Name ($conf.RESTIC_REPOSITORY.Substring(0, 1)) -ErrorAction SilentlyContinue
$freeGb = if ($drive) { [math]::Round($drive.Free / 1GB) } else { -1 }
$snaps = (& $restic snapshots --json 2>$null | ConvertFrom-Json).Count
if ($freeGb -ge 0 -and $freeGb -lt 100) { $problems += "backup drive has only $freeGb GB free" }

$ok = $problems.Count -eq 0
$note = if ($ok) { "$snaps snapshots, $freeGb GB free" } else { ($problems -join '; ') + " ($snaps snapshots, $freeGb GB free)" }
Say "Backup finished. ok=$ok. $note"
& "$PSScriptRoot\heartbeat.ps1" -BackupOk $ok -Note $note
