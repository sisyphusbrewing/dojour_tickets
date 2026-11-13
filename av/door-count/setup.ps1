# Sets up the Stream Deck's "guests still to come" count on the office PC (Sam, Nov 13 2026).
#   powershell -ExecutionPolicy Bypass -File setup.ps1            # from main
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Ref <branch>
# Copies door_count.py from GitHub, reads the door once to prove the sign-in works, then
# starts it hidden and adds a Startup shortcut so it comes back after every restart.
# It uses the "recorder" staff login that the recordings job already saved on this PC
# (%USERPROFILE%\.sisyphus\recordings.env), so there is no password to type. Safe to run again.
param([string]$Ref = 'main')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = "$env:USERPROFILE\sisyphus-av\door-count"
$state = "$env:USERPROFILE\.sisyphus"
$script = "$dir\door_count.py"
New-Item -ItemType Directory -Force $dir, $state | Out-Null

if (-not (Select-String -Path "$state\recordings.env" -Pattern '^RECORDER_PASSWORD=.+' -Quiet -ErrorAction SilentlyContinue)) {
    throw "No recorder login saved in $state\recordings.env. Run av\recordings\setup.ps1 first."
}

# Python is installed for Sam only and is not on the PATH, so look where the installer puts it.
$python = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object { [int]($_.Directory.Name -replace '\D', '') } | Select-Object -Last 1 -ExpandProperty FullName
if (-not $python) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw 'Python 3 not found on this PC.' }
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'   # the same Python with no window
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $python" }

Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/$Ref/av/door-count/door_count.py" -OutFile $script -TimeoutSec 30

# Read the door once in the open. A wrong password or no internet stops here with the reason.
"What the START SHOW key would say right now:"
& $python $script --once
if ($LASTEXITCODE -ne 0) { throw 'The test reading failed; nothing was started.' }

# Stop a copy that is already running, so there is only ever one writing to the deck.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*door_count.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut(([Environment]::GetFolderPath('Startup')) + '\Sisyphus door count.lnk')
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$script`""
$shortcut.WorkingDirectory = $dir
$shortcut.Description = 'Guests still to come, for the Stream Deck START SHOW key'
$shortcut.Save()

Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $dir
Start-Sleep -Seconds 8
"Running. Last lines of $state\door-count.log:"
Get-Content "$state\door-count.log" -Tail 3 -ErrorAction SilentlyContinue
