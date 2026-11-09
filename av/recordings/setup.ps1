# One-time setup of show recordings on the office PC (Sam, Nov 4 2026).
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -RecorderPassword <password> [-ObsDir C:\Users\Sam\Videos]
# Installs ffmpeg + rclone, signs rclone in to Google Drive as sam@ (a browser opens; Sam clicks Allow),
# saves the settings to %USERPROFILE%\.sisyphus\recordings.env, copies split_and_share.py from main and
# adds a 4 AM daily Task Scheduler task "Sisyphus recordings". Safe to run again.
param([Parameter(Mandatory = $true)][string]$RecorderPassword, [string]$ObsDir = "$env:USERPROFILE\Videos")
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = "$env:USERPROFILE\sisyphus-av\recordings"
$state = "$env:USERPROFILE\.sisyphus"
New-Item -ItemType Directory -Force $dir, $state | Out-Null

foreach ($pkg in @('Gyan.FFmpeg', 'Rclone.Rclone')) {
    winget install -e --id $pkg --accept-package-agreements --accept-source-agreements --silent
}
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
# tzdata: Windows has no time zone database, so Python can't read
# America/Chicago without it and the script crashes (found Nov 9 2026).
py -3 -m pip install --quiet --upgrade requests tzdata

# Google Drive remote "gdrive" (full drive scope so it can make share links and delete old files).
if (-not ((rclone listremotes) -match '^gdrive:')) {
    rclone config create gdrive drive scope=drive   # opens the browser for sam@ to allow
}
rclone mkdir "gdrive:Sisyphus Recordings"

Set-Content -Path "$state\recordings.env" -Value @("RECORDER_PASSWORD=$RecorderPassword", "OBS_DIR=$ObsDir")
Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/av/recordings/split_and_share.py' -OutFile "$dir\split_and_share.py"

# Every morning at 4 AM, pulling the newest script first so fixes land without another setup.
$run = "Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/av/recordings/split_and_share.py' -OutFile '$dir\split_and_share.py' -ErrorAction SilentlyContinue; " +
       "py -3 '$dir\split_and_share.py' *>> '$state\recordings.log'"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -Command `"$run`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 4am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName 'Sisyphus recordings' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

py -3 "$dir\split_and_share.py" --dry-run
