# What the "Sisyphus cameras" task runs on the office PC (Nov 20 2026). Made by setup.ps1.
#
# Keeps go2rtc (the program that turns the Wyze cameras into streams for OBS, the deck and
# still pictures) running: starts it, and if it ever stops, starts it again 10 seconds later.
# It only runs local files; it downloads nothing (a task that downloads and runs things hidden
# is what Microsoft Defender blocked on Nov 20 2026). Updates come from running setup.ps1 again.
#
# Log: %USERPROFILE%\.sisyphus\cams.log (starts and stops) and go2rtc.log (go2rtc's own words,
# the last run only; the run before is go2rtc-previous.log).
$dir = $PSScriptRoot
$state = "$env:USERPROFILE\.sisyphus"
$config = "$state\go2rtc.yaml"
$log = "$state\cams.log"
function Log($m) { Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $m) -Encoding UTF8 }

# Another copy of this watcher is already on it: nothing to do.
$me = $PID
$others = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -like '*run-cams.ps1*' }
if ($others) { exit 0 }

while ($true) {
    if (-not (Test-Path $config)) { Log "No settings at $config; run setup.ps1."; Start-Sleep -Seconds 300; continue }
    # A go2rtc started by hand is left alone; just wait for it to end.
    $running = Get-Process go2rtc -ErrorAction SilentlyContinue
    if ($running) { $running | Select-Object -First 1 | ForEach-Object { $_.WaitForExit() }; Start-Sleep -Seconds 10; continue }

    if (Test-Path "$state\go2rtc.log") { Move-Item -Force "$state\go2rtc.log" "$state\go2rtc-previous.log" }
    Log 'Starting go2rtc'
    try {
        $p = Start-Process -FilePath "$dir\go2rtc.exe" -ArgumentList "-config `"$config`"" -WorkingDirectory $dir `
            -NoNewWindow -PassThru -RedirectStandardOutput "$state\go2rtc.log" -RedirectStandardError "$state\go2rtc-errors.log"
        $p.WaitForExit()
        Log "go2rtc stopped (exit code $($p.ExitCode)); starting again in 10 seconds"
    } catch {
        Log "Could not start go2rtc: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 10
}
