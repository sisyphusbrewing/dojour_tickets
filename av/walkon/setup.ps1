# Sets up walk-on songs on the office PC (Sam, Nov 19 2026: "Before a show we should let
# comics pick a walk up song and we can integrate that into the deck").
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -ClientId <Spotify app Client ID>   # first time
#   powershell -ExecutionPolicy Bypass -File setup.ps1                                      # again later, from main
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Ref <branch>
# Copies walkon.py from GitHub, connects it to Spotify once (Spotify's page opens in the
# browser: sign in to the Spotify account that plays in the showroom and press Agree), shows
# tonight's walk-ons, then starts it hidden with a Startup shortcut so it comes back after
# every restart. Spotify's key is kept only in %USERPROFILE%\.sisyphus\spotify.json.
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
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $python" }

Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/$Ref/av/walkon/walkon.py" -OutFile $script -TimeoutSec 30

# Stop a copy that is already running (it holds port 8793, which the Spotify sign-in needs).
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

$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut(([Environment]::GetFolderPath('Startup')) + '\Sisyphus walk-on songs.lnk')
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$script`""
$shortcut.WorkingDirectory = $dir
$shortcut.Description = 'Plays each comic''s walk-on song from the Stream Deck'
$shortcut.Save()

Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $dir
Start-Sleep -Seconds 4
"Running: " + (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8793/walkon/status -TimeoutSec 10).StatusCode
Get-Content "$state\walkon.log" -Tail 3 -ErrorAction SilentlyContinue
