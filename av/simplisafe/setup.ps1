# One-time setup of the SimpliSafe deck service on the office PC.
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Installs Python packages, copies alarm.py from main, opens Edge for Sam to sign in to SimpliSafe
# (skipped if a token is already saved), adds a Startup shortcut and starts the service.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = "$env:USERPROFILE\sisyphus-av\simplisafe"
New-Item -ItemType Directory -Force $dir | Out-Null

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
py -3 -m pip install --quiet --upgrade simplisafe-python aiohttp playwright
Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/av/simplisafe/alarm.py' -OutFile "$dir\alarm.py"

if (-not (Test-Path "$env:USERPROFILE\.simplisafe\token.json")) {
    py -3 "$dir\alarm.py" login   # Edge opens; Sam signs in himself
}

$pyw = (py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))").Trim()
$lnk = "$([Environment]::GetFolderPath('Startup'))\SimpliSafe deck service.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pyw; $s.Arguments = "`"$dir\alarm.py`" serve"; $s.WorkingDirectory = $dir; $s.Save()

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*alarm.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Process $pyw -ArgumentList "`"$dir\alarm.py`" serve" -WorkingDirectory $dir
Start-Sleep 8
(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8791/alarm/status').Content
