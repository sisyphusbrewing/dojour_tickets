# Sets up walk-on songs on the office PC (Sam, Nov 19 2026: "Before a show we should let
# comics pick a walk up song and we can integrate that into the deck").
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -ClientId <Spotify app Client ID>   # first time
#   powershell -ExecutionPolicy Bypass -File setup.ps1                                      # again later, from main
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Ref <branch>
# Copies walkon.py from GitHub, connects it to Spotify once (Spotify's page opens in the
# browser: sign in to the Spotify account that plays in the showroom and press Agree), shows
# tonight's walk-ons, then has the "Sisyphus walk-on songs" task keep it running (at sign-in,
# checked every 15 minutes, restarted within seconds if it stops; Nov 21 2026: the old Startup
# shortcut started it once and never again, and it was not running on Fri Nov 20's shows). Spotify's key is kept only in %USERPROFILE%\.sisyphus\spotify.json.
# The Spotify app (developer.spotify.com > Dashboard) needs the Redirect URI
# http://127.0.0.1:8793/callback and "Web API". Safe to run again.
param([string]$Ref = 'main', [string]$ClientId = '')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = "$env:USERPROFILE\sisyphus-av\walkon"
$state = "$env:USERPROFILE\.sisyphus"
$script = "$dir\walkon.py"
New-Item -ItemType Directory -Force $dir, $state | Out-Null

# Python is installed for Sam only and is not on the PATH, so look where the installer puts it.
$python = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object { [int]($_.Directory.Name -replace '\D', '') } | Select-Object -Last 1 -ExpandProperty FullName
if (-not $python) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw 'Python 3 not found on this PC.' }

Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/$Ref/av/walkon/walkon.py" -OutFile $script -TimeoutSec 30

# Stop a copy that is already running (it holds port 8793, which the Spotify sign-in needs).
# Its watcher goes first, or it would start the helper again in the middle of this.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*run-walkon.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*walkon.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 1

if ($ClientId) {
    "Connecting Spotify: sign in on the page that opens and press Agree."
    & $python $script --connect $ClientId
    if ($LASTEXITCODE -ne 0) { throw 'Spotify was not connected; nothing was started.' }
} elseif (-not (Test-Path "$state\spotify.json")) {
    "Spotify is not connected yet (run again with -ClientId). The deck keys still work, with house music only."
}

"Tonight's walk-ons:"
& $python $script --once
if ($LASTEXITCODE -ne 0) { throw 'Could not read tonight''s walk-ons; nothing was started.' }

# The old Startup shortcut started it once at sign-in and never again; the task replaces it.
$oldShortcut = ([Environment]::GetFolderPath('Startup')) + '\Sisyphus walk-on songs.lnk'
if (Test-Path $oldShortcut) { Remove-Item $oldShortcut -Force; "Removed the old Startup shortcut." }

# The task runs the local run-walkon.ps1 (never a download-and-run line; Defender blocks those).
Copy-Item -Force "$PSScriptRoot\run-walkon.ps1" "$dir\run-walkon.ps1" -ErrorAction SilentlyContinue
if (-not (Test-Path "$dir\run-walkon.ps1")) {
    Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/$Ref/av/walkon/run-walkon.ps1" -OutFile "$dir\run-walkon.ps1" -TimeoutSec 30
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $dir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\run-walkon.ps1`""
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$every15 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Sisyphus walk-on songs' -Action $action -Trigger $atLogon, $every15 -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'Sisyphus walk-on songs'

$ok = $false
foreach ($i in 1..20) {
    Start-Sleep -Seconds 1
    try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8793/walkon/status -TimeoutSec 3 | Out-Null; $ok = $true; break } catch {}
}
if (-not $ok) { throw "The walk-on helper did not start. See $state\walkon.log and walkon-errors.log" }
"Running on http://127.0.0.1:8793"
Get-Content "$state\walkon.log" -Tail 3 -ErrorAction SilentlyContinue
