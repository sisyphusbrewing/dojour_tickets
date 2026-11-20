# One-time setup of the nightly backup and the check-in on the office PC
# (Sam, Nov 18 2026). Safe to run again: it keeps an existing password,
# code and backup store.
#   powershell -ExecutionPolicy Bypass -File setup.ps1 [-RepoPath D:\SisyphusBackup\restic]
#
# - installs restic
# - makes the backup store (encrypted; its password is a random file that
#   stays on this PC, %USERPROFILE%\.sisyphus\restic-pass.txt)
# - makes the check-in code and prints its fingerprint, which goes in the
#   database row device_heartbeats 'office-pc' (the code never leaves the PC)
# - adds two Task Scheduler tasks, each pulling the newest script from main
#   before it runs: "Sisyphus backup" (3:15 AM, before the 4 AM recordings
#   upload) and "Sisyphus heartbeat" (every 10 minutes). Each runs a local
#   file; the backup's run-backup.ps1 pulls the newest scripts from main.
param([string]$RepoPath = 'D:\SisyphusBackup\restic')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$state = "$env:USERPROFILE\.sisyphus"
$dir = "$env:USERPROFILE\sisyphus-backup"
New-Item -ItemType Directory -Force $state, $dir, (Split-Path $RepoPath) | Out-Null

winget install -e --id restic.restic --accept-package-agreements --accept-source-agreements --silent
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

function NewSecret { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ([BitConverter]::ToString($b) -replace '-', '').ToLower() }
if (-not (Test-Path "$state\restic-pass.txt")) { Set-Content "$state\restic-pass.txt" (NewSecret) -NoNewline }
if (-not (Test-Path "$state\heartbeat-code.txt")) { Set-Content "$state\heartbeat-code.txt" (NewSecret) -NoNewline }
# (No "at log on" trigger: that one needs admin, and every 10 minutes covers it.)
# Only this Windows user can read the two secret files.
foreach ($f in "$state\restic-pass.txt", "$state\heartbeat-code.txt") {
    icacls $f /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
}

# backup.env: the store's path, plus any other lines already there (the
# database's PG_HOST and PG_USER), which a re-run must not drop.
$keep = @(Get-Content "$state\backup.env" -ErrorAction SilentlyContinue | Where-Object { $_ -notmatch '^RESTIC_REPOSITORY=' })
Set-Content "$state\backup.env" (@("RESTIC_REPOSITORY=$($RepoPath -replace '\\', '\\')") + $keep)
$env:RESTIC_REPOSITORY = $RepoPath
$env:RESTIC_PASSWORD_FILE = "$state\restic-pass.txt"
# winget installs restic as restic_<version>_windows_amd64.exe in its own
# package folder, which isn't always on PATH (found Nov 20 2026). Use the
# newest one there, so a winget upgrade is picked up by itself.
$restic = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\restic.restic*\restic*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $restic) { $restic = (Get-Command restic -ErrorAction Stop).Source }
if (-not (Test-Path "$RepoPath\config")) { & $restic init }

# The scripts are copied here once; after that run-backup.ps1 pulls the newest
# ones from main each night. Each task runs a plain local file (-File), never
# a download-and-run line, which Defender blocks as malware (Nov 20 2026).
$raw = 'https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/backup'
foreach ($f in 'run-backup.ps1', 'nightly.ps1', 'heartbeat.ps1') {
    Invoke-WebRequest -UseBasicParsing "$raw/$f" -OutFile "$dir\$f"
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew
$a = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $dir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\run-backup.ps1`""
Register-ScheduledTask -TaskName 'Sisyphus backup' -Action $a -Trigger (New-ScheduledTaskTrigger -Daily -At 3:15am) -Settings $settings -Force | Out-Null

$hb = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $dir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\heartbeat.ps1`""
$every10 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$hbSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Sisyphus heartbeat' -Action $hb -Trigger $every10 -Settings $hbSettings -Force | Out-Null

$sha = [Security.Cryptography.SHA256]::Create()
$fp = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes((Get-Content "$state\heartbeat-code.txt" -Raw).Trim()))) -replace '-', '').ToLower()
"Check-in code fingerprint (goes in the database, not secret): $fp"
