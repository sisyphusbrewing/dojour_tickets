# Sets up the Wyze cameras on the office PC (Sam, Nov 20 2026: "Do Wyze cams integrate?" ... "Yeah set that up").
#   powershell -ExecutionPolicy Bypass -File setup.ps1              # first time, and again to update
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Ref <branch>
#
# What it does: installs go2rtc, a free one-file program that talks to Wyze cameras directly
# over the club network (no Wyze app, no Docker, no cloud video). Each camera becomes a stream
# the PC can use: OBS (Media Source rtsp://127.0.0.1:8554/<name>), a still picture for checking
# the lights (still.ps1), and the deck.
#
# Everything listens on this PC only (127.0.0.1), so nothing is reachable from either Wi-Fi,
# including the guest network, and Windows Firewall needs no new rule.
#
# Sam's Wyze login: the first time, the go2rtc page opens in the browser. Sam picks Add > Wyze
# and types his Wyze email, password, API ID and API key there himself (the key is made once at
# developer-api-console.wyze.com), then ticks the cameras. go2rtc keeps them in
# %USERPROFILE%\.sisyphus\go2rtc.yaml on this PC only. Claude never opens that file.
#
# A task, "Sisyphus cameras", starts it at sign-in and brings it back if it stops. Per the Nov 20
# 2026 Defender lesson the task only runs the local file run-cams.ps1; nothing is downloaded by the
# task itself. Safe to run again: the camera list and login in go2rtc.yaml are kept.
param([string]$Ref = 'main')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = "$env:USERPROFILE\sisyphus-av\cams"
$state = "$env:USERPROFILE\.sisyphus"
$config = "$state\go2rtc.yaml"
New-Item -ItemType Directory -Force $dir, $state, "$dir\stills" | Out-Null

# 1. The helper scripts, from GitHub.
foreach ($f in 'run-cams.ps1', 'still.ps1') {
    Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/$Ref/av/cams/$f" -OutFile "$dir\$f" -TimeoutSec 30
}

# 2. go2rtc itself, the newest release from its makers (github.com/AlexxIT/go2rtc).
#    A download that isn't a Windows program never replaces a copy that works.
$zip = "$env:TEMP\go2rtc_win64.zip"; $unz = "$env:TEMP\go2rtc_win64"
Invoke-WebRequest -UseBasicParsing 'https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_win64.zip' -OutFile $zip -TimeoutSec 120
Remove-Item -Recurse -Force $unz -ErrorAction SilentlyContinue
Expand-Archive -Force $zip $unz
$exe = Get-ChildItem $unz -Recurse -Filter go2rtc*.exe | Select-Object -First 1
if (-not $exe) { throw 'The go2rtc download had no program in it; nothing was changed.' }
$head = [IO.File]::ReadAllBytes($exe.FullName)[0..1]
if ($head[0] -ne 0x4D -or $head[1] -ne 0x5A) { throw 'The go2rtc download is not a Windows program; nothing was changed.' }

# Stop the running copy (the task's watcher first, so it doesn't restart the old one mid-copy).
Stop-ScheduledTask -TaskName 'Sisyphus cameras' -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like '*run-cams.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-Process go2rtc -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
Copy-Item -Force $exe.FullName "$dir\go2rtc.exe"
"Installed: " + (& "$dir\go2rtc.exe" -version 2>&1 | Select-Object -First 1)

# 3. Settings, written only if there are none yet (the file later holds Sam's cameras and login).
if (-not (Test-Path $config)) {
@'
# go2rtc settings for the Sisyphus office PC (made by av/cams/setup.ps1).
# Everything listens on this PC only. The Wyze login and cameras get added below by the
# go2rtc page (Add > Wyze). This file stays on this PC; it never goes in the repo.
api:
  listen: "127.0.0.1:1984"
rtsp:
  listen: "127.0.0.1:8554"
webrtc:
  listen: "127.0.0.1:8555"
srtp:
  listen: ""
log:
  level: info
streams:
'@ | Set-Content -Path $config -Encoding ASCII
    "Wrote fresh settings to $config"
} else {
    "Kept the existing settings in $config"
}
# Only Sam's own login can read the settings file.
icacls $config /inheritance:r /grant:r "${env:USERNAME}:(F)" /grant:r "SYSTEM:(F)" | Out-Null

# 4. The task: at sign-in, and every 15 minutes as a backup (it does nothing if already running).
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $dir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\run-cams.ps1`""
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$every15 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Sisyphus cameras' -Action $action -Trigger $atLogon, $every15 -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'Sisyphus cameras'

# 5. Check it answers, then show the cameras (or open the page to add them).
$ok = $false
foreach ($i in 1..15) {
    Start-Sleep -Seconds 1
    try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:1984/api -TimeoutSec 3 | Out-Null; $ok = $true; break } catch {}
}
if (-not $ok) { throw "go2rtc did not start. See $state\cams.log" }
"go2rtc is running on this PC (http://127.0.0.1:1984)."
& "$dir\still.ps1" -List
$r = Invoke-RestMethod http://127.0.0.1:1984/api/streams -TimeoutSec 5
if (-not $r -or -not $r.PSObject.Properties.Name) {
    "No cameras yet: opening the go2rtc page. Pick Add, then Wyze, and sign in there."
    Start-Process 'http://127.0.0.1:1984/add.html'
}
