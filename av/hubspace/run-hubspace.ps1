# Keeps the Hubspace helper (hubspace.py, http://127.0.0.1:8794) running.
# Started at logon by the "Sisyphus Hubspace helper" task, which runs this local
# file (never a download-and-run line; Defender blocks those, Nov 20 2026).
# Safe to run again: exits if another copy is already running. Restarts the
# helper if it ever stops.
$here = Split-Path $MyInvocation.MyCommand.Path
$log = Join-Path $here 'hubspace.log'
$mutex = New-Object Threading.Mutex($false, 'Global\SisyphusHubspaceHelper')
if (-not $mutex.WaitOne(0)) { exit 0 }
while ($true) {
    if (-not (Get-NetTCPConnection -State Listen -LocalPort 8794 -ErrorAction SilentlyContinue)) {
        if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item $log "$log.old" -Force }
        & py -3 "$here\hubspace.py" *>> $log
    }
    Start-Sleep -Seconds 30
}
