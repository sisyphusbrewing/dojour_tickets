# One-time setup of show recordings on the office PC (Sam, Nov 4 2026).
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -RecorderPassword <password> [-ObsDir C:\Users\Sam\Videos]
# Installs ffmpeg + rclone, signs rclone in to Google Drive as sam@ (a browser opens; Sam clicks Allow),
# saves the settings to %USERPROFILE%\.sisyphus\recordings.env, copies split_and_share.py and
# run-recordings.ps1 from main and adds a 4 AM daily Task Scheduler task "Sisyphus recordings" that runs
# run-recordings.ps1. Safe to run again.
param([Parameter(Mandatory = $true)][string]$RecorderPassword, [string]$ObsDir = "$env:USERPROFILE\Videos", [string]$StageFrame)
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
# faster-whisper (+ the CUDA wheels for the RTX 3070) finds the sets from the host's intros when nobody
# pressed the stage timer.
py -3 -m pip install --quiet --upgrade requests tzdata faster-whisper nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"

# Google Drive remote "gdrive" (full drive scope so it can make share links and delete old files).
if (-not ((rclone listremotes) -match '^gdrive:')) {
    rclone config create gdrive drive scope=drive   # opens the browser for sam@ to allow
}
rclone mkdir "gdrive:Sisyphus Recordings"

Set-Content -Path "$state\recordings.env" -Value @("RECORDER_PASSWORD=$RecorderPassword", "OBS_DIR=$ObsDir")
foreach ($f in 'split_and_share.py', 'run-recordings.ps1') {
    Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/av/recordings/$f" -OutFile "$dir\$f"
}

# The camera check compares each show 5 minutes in against a known-good stage frame. Re-run with -StageFrame
# <a recording where the camera was on the stage> after moving the camera.
if ($StageFrame) {
    ffmpeg -v error -y -ss 300 -i $StageFrame -frames:v 1 -vf 'scale=320:180,format=gray' "$state\stage-reference.png"
}

# Every morning at 4 AM the task runs run-recordings.ps1, which pulls the newest split_and_share.py first so
# fixes land without another setup. The task's own command must stay this plain "run that file": until
# Nov 20 2026 it was one hidden line that downloaded the script and ran it, and Microsoft Defender stopped
# it as malware, so that night's show was never cut or sent.
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\run-recordings.ps1`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 4am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName 'Sisyphus recordings' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

py -3 "$dir\split_and_share.py" --dry-run
