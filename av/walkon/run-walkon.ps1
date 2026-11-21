# What the "Sisyphus walk-on songs" task runs on the office PC (Nov 21 2026). Made by setup.ps1.
#
# Keeps the walk-on helper (walkon.py, http://127.0.0.1:8793) running, so START SHOW, the
# WALK-ON key and END SHOW always find it: starts it, and if it ever stops, starts it again
# 10 seconds later. On Fri Nov 20 2026 nothing was listening on 8793 and every START SHOW
# and END SHOW press got "connection refused": setup.ps1 had never been run on the PC, and
# even when it was, its Startup shortcut started the helper once and never again.
# It only runs local files; it downloads nothing (a task that downloads and runs things
# hidden is what Microsoft Defender blocked on Nov 20 2026). Updates come from setup.ps1.
#
# Logs in %USERPROFILE%\.sisyphus: walkon.log (the helper's own lines), walkon-watcher.log
# (this watcher's starts and stops) and walkon-errors.log (what Python says if it crashes).
$dir = $PSScriptRoot
$state = "$env:USERPROFILE\.sisyphus"
$log = "$state\walkon-watcher.log"
New-Item -ItemType Directory -Force $state | Out-Null
function Log($m) { Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $m) -Encoding UTF8 }

# Another copy of this watcher is already on it: nothing to do.
$me = $PID
$others = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -like '*run-walkon.ps1*' }
if ($others) { exit 0 }

# Python is installed for Sam only and is not on the PATH, so look where the installer puts it.
function Find-Python {
    $p = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Name -replace '\D', '') } | Select-Object -Last 1 -ExpandProperty FullName
    if (-not $p) { $p = (Get-Command python -ErrorAction SilentlyContinue).Source }
    $p
}

while ($true) {
    $python = Find-Python
    if (-not $python -or -not (Test-Path "$dir\walkon.py")) {
        Log "Python or walkon.py is missing; run setup.ps1."; Start-Sleep -Seconds 300; continue
    }
    # A copy started by hand (or by setup.ps1) is left alone; just wait for it to end.
    $running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like '*walkon.py*' -and $_.CommandLine -notlike '*--once*' -and $_.CommandLine -notlike '*--connect*' }
    if ($running) {
        $p = Get-Process -Id ($running | Select-Object -First 1).ProcessId -ErrorAction SilentlyContinue
        if ($p) { $p.WaitForExit() }
        Log 'walk-on helper stopped; starting it again in 10 seconds'
        Start-Sleep -Seconds 10; continue
    }

    Log 'Starting the walk-on helper'
    try {
        # python.exe with a hidden window, so a crash's last words land in walkon-errors.log.
        $p = Start-Process -FilePath $python -ArgumentList "`"$dir\walkon.py`"" -WorkingDirectory $dir `
            -WindowStyle Hidden -PassThru -RedirectStandardError "$state\walkon-errors.log" -RedirectStandardOutput "$state\walkon-out.log"
        $p.WaitForExit()
        Log "walk-on helper stopped (exit code $($p.ExitCode)); starting again in 10 seconds"
    } catch {
        Log "Could not start the walk-on helper: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 10
}
