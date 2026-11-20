# What the 3:15 AM "Sisyphus backup" task runs on the office PC (Nov 20 2026).
#
# The task runs this plain local file and nothing else. A task that downloads
# a script from the web and runs it hidden looks like malware to Microsoft
# Defender, which blocked the recordings task that way on Nov 20 2026.
#
# It pulls the newest nightly.ps1 and heartbeat.ps1 from main first, so a fix
# merged there lands without another setup. A download that fails, or that
# isn't valid PowerShell, never replaces the copy that already works.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = $PSScriptRoot
$log = "$env:USERPROFILE\.sisyphus\backup.log"
function Log($text) { Add-Content -Path $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $text" -Encoding UTF8 }

foreach ($f in 'nightly.ps1', 'heartbeat.ps1', 'run-backup.ps1') {
    $new = "$dir\$f.new"
    try {
        Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/main/backup/$f" -OutFile $new -TimeoutSec 60 -ErrorAction Stop
        $errors = $null
        [void][Management.Automation.Language.Parser]::ParseFile($new, [ref]$null, [ref]$errors)
        if ($errors.Count -eq 0) { Move-Item -Force $new "$dir\$f" }
        else { Log "Kept the $f already here: the download wasn't valid PowerShell." }
    } catch { Log "Kept the $f already here: couldn't download the newest one." }
    Remove-Item $new -ErrorAction SilentlyContinue
}

& "$dir\nightly.ps1"
