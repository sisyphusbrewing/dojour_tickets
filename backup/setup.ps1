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
#   upload) and "Sisyphus heartbeat" (every 10 minutes).
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
# Only this Windows user can read the two secret files.
foreach ($f in "$state\restic-pass.txt", "$state\heartbeat-code.txt") {
    icacls $f /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
}

Set-Content "$state\backup.env" "RESTIC_REPOSITORY=$($RepoPath -replace '\\', '\\')"
$env:RESTIC_REPOSITORY = $RepoPath
$env:RESTIC_PASSWORD_FILE = "$state\restic-pass.txt"
if (-not (Test-Path "$RepoPath\config")) { restic init }

$raw = 'https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/backup'
$pull = "foreach (`$f in 'nightly.ps1','heartbeat.ps1') { Invoke-WebRequest -UseBasicParsing ('$raw/' + `$f) -OutFile ('$dir\' + `$f) -ErrorAction SilentlyContinue }; "
Invoke-Expression ($pull)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew
$a = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $dir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$pull & '$dir\nightly.ps1'`""
Register-ScheduledTask -TaskName 'Sisyphus backup' -Action $a -Trigger (New-ScheduledTaskTrigger -Daily -At 3:15am) -Settings $settings -Force | Out-Null

$hb = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $dir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\heartbeat.ps1`""
$every10 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$hbSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Sisyphus heartbeat' -Action $hb -Trigger @($every10, (New-ScheduledTaskTrigger -AtLogOn)) -Settings $hbSettings -Force | Out-Null

$sha = [Security.Cryptography.SHA256]::Create()
$fp = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes((Get-Content "$state\heartbeat-code.txt" -Raw).Trim()))) -replace '-', '').ToLower()
"Check-in code fingerprint (goes in the database, not secret): $fp"
