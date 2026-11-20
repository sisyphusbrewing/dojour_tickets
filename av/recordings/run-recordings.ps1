# What the 4 AM "Sisyphus recordings" task runs on the office PC (Nov 20 2026).
#
# Why this file exists: the task used to be one long hidden PowerShell line that
# downloaded split_and_share.py from GitHub and ran it. On Nov 20 2026 Microsoft
# Defender judged that line to be malware ("download something from the web and
# run it hidden" is what real malware does), stopped the task before it started,
# and no recording was cut or sent that night. Nothing told anyone. The same
# steps live here in a plain file the task points at, so the task's own command
# is just "run this file".
#
# It still pulls the newest split_and_share.py first, so a fix merged to main
# lands without another setup. A download that fails, or that isn't Python,
# never replaces the copy that already works.
#
# By hand:  powershell -ExecutionPolicy Bypass -File run-recordings.ps1 [--dry-run] [--redo "file.mp4"]
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = $PSScriptRoot
$state = "$env:USERPROFILE\.sisyphus"
$log = "$state\recordings.log"
New-Item -ItemType Directory -Force $state | Out-Null

# The log is plain UTF-8, written only through Log below. Windows PowerShell's
# own redirection writes a different encoding (UTF-16), and on Nov 20 2026 one
# line added by hand in UTF-8 made the whole file unreadable. An old log in that
# encoding is put aside once, not deleted, and a fresh one starts.
if (Test-Path $log) {
    $f = [IO.File]::OpenRead($log); $b0 = $f.ReadByte(); $b1 = $f.ReadByte(); $f.Close()
    if ($b0 -eq 0xFF -and $b1 -eq 0xFE) { Move-Item -Force $log "$state\recordings-old-utf16.log" }
}
function Log { process { Add-Content -Path $log -Value "$_" -Encoding UTF8 } }
# Python prints names with accents; keep them readable in the log.
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

"--- $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') recordings run starting" | Log

$script = "$dir\split_and_share.py"
$new = "$dir\split_and_share.new.py"
try {
    Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/av/recordings/split_and_share.py' -OutFile $new -TimeoutSec 60 -ErrorAction Stop
    py -3 -m py_compile $new 2>&1 | Log
    if ($LASTEXITCODE -eq 0) { Move-Item -Force $new $script }
    else { "Kept the script already here: the download wasn't valid Python." | Log }
}
catch { "Kept the script already here: couldn't download the newest one ($($_.Exception.GetType().Name))." | Log }
Remove-Item $new -ErrorAction SilentlyContinue

py -3 $script @args 2>&1 | Log
$code = $LASTEXITCODE
"--- $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') recordings run ended (exit $code)" | Log
exit $code
