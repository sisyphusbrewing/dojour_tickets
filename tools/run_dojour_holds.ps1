# Runs the Dojour "Website Hold" job on the office PC (Windows Task Scheduler,
# every 4 hours). Dojour refuses hold requests from GitHub's servers but accepts
# them from the venue's own network, so this has to run here (Sam, Nov 9 2026).
#
# Each run downloads a fresh copy of the repo's main branch (no git needed),
# then runs dojour_holds.py with APPLY=1. Counts come from the public
# website_hold_counts feed, so no secret database key lives on this PC.
# The Dojour login is C:\SisyphusHolds\dojour_state.json (made once by Sam).
# Output goes to C:\SisyphusHolds\logs\holds-<date>.log.

$ErrorActionPreference = "Stop"
$Root   = "C:\SisyphusHolds"
$Python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$Logs   = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Log = Join-Path $Logs ("holds-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Say($text) { Add-Content -Path $Log -Value ("[" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "] " + $text) }

try {
    $zip = Join-Path $env:TEMP "dojour_tickets_main.zip"
    $tmp = Join-Path $Root "download"
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/sisyphusbrewing/dojour_tickets/archive/refs/heads/main.zip" -OutFile $zip
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp | Select-Object -First 1
    $repo = Join-Path $Root "repo"
    if (Test-Path $repo) { Remove-Item -Recurse -Force $repo }
    Move-Item $src.FullName $repo
    Say "Downloaded fresh copy of main"
} catch {
    # Keep going with the last good copy if GitHub can't be reached.
    Say ("Download failed, using the last copy: " + $_.Exception.Message)
    $repo = Join-Path $Root "repo"
}

$env:DOJOUR_STATE = Join-Path $Root "dojour_state.json"
$env:APPLY = "1"
$env:PYTHONIOENCODING = "utf-8"
Remove-Item Env:SUPABASE_KEY -ErrorAction SilentlyContinue
Push-Location $repo
try {
    & $Python dojour_holds.py *>> $Log
    Say ("Finished with exit code " + $LASTEXITCODE)
} finally {
    Pop-Location
}
