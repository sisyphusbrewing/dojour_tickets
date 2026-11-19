# One-time setup of check printing on the office PC (Sam, Nov 18 2026).
# Run it at the PC, as the same Windows user as the backup, after
# backup\setup.ps1 (it uses the same check-in code):
#
#   powershell -ExecutionPolicy Bypass -File setup-checks.ps1
#
# Sam types the bank details here, at the PC. They are saved only on this PC,
# encrypted by Windows for this Windows user, and are never sent anywhere.
# Run it again to change anything (printer, limit, bank, signature) or to
# install a newer checks.ps1; it asks before replacing what's saved.
#
# What it does:
# - installs SumatraPDF (prints the check PDF at exact size, no shrinking)
# - copies checks.ps1, check.html and the MICR font from GitHub to this PC
#   once, and runs that copy from then on (see the note in checks.ps1)
# - asks for the bank name, routing and account number (each typed twice),
#   the printer, the PC's own limit per check, and the signature image
# - prints a VOID alignment sample on plain paper
# - adds the task "Sisyphus checks" (every minute)
param([string]$Ref = 'main')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$state = "$env:USERPROFILE\.sisyphus"
$dir = "$env:USERPROFILE\sisyphus-checks"
if (-not (Test-Path "$state\heartbeat-code.txt")) { throw 'Run backup\setup.ps1 first (it makes the check-in code).' }
New-Item -ItemType Directory -Force $dir | Out-Null

winget install -e --id SumatraPDF.SumatraPDF --accept-package-agreements --accept-source-agreements --silent

$raw = "https://raw.githubusercontent.com/sisyphusbrewing/dojour_tickets/$Ref/backup/checks"
foreach ($f in 'checks.ps1', 'check.html', 'GnuMICR.otf', 'GnuMICR-COPYING.txt') {
    Invoke-WebRequest -UseBasicParsing "$raw/$f" -OutFile "$dir\$f"
}
$e = $null
[Management.Automation.Language.Parser]::ParseFile("$dir\checks.ps1", [ref]$null, [ref]$e) | Out-Null
if ($e.Count) { throw "checks.ps1 has a mistake in it: $($e[0].Message)" }
"Installed check printing from ${Ref}:"
Get-FileHash "$dir\*" -Algorithm SHA256 | ForEach-Object { "  $($_.Hash.Substring(0,16))  $(Split-Path -Leaf $_.Path)" }

function Plain($secure) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}
function RoutingOk([string]$r) {
    if ($r -notmatch '^\d{9}$') { return $false }
    $d = $r.ToCharArray() | ForEach-Object { [int]"$_" }
    return ((3 * ($d[0] + $d[3] + $d[6]) + 7 * ($d[1] + $d[4] + $d[7]) + ($d[2] + $d[5] + $d[8])) % 10) -eq 0
}
function AskTwice($label, $test, $why) {
    while ($true) {
        $a = Read-Host "$label" -AsSecureString
        $b = Read-Host "$label again" -AsSecureString
        $pa = Plain $a
        if ($pa -ne (Plain $b)) { 'Those two did not match. Once more.'; continue }
        if (-not (& $test $pa)) { $why; continue }
        return $a
    }
}
function Ask($label, $default) {
    $v = Read-Host ("$label" + $(if ($default) { " [$default]" } else { '' }))
    if ($v) { $v } else { $default }
}

$old = $null
if (Test-Path "$state\checks.xml") { $old = Import-Clixml "$state\checks.xml" }
$keepBank = $old -and ((Read-Host 'Bank details are already saved. Keep them? (Y/n)') -notmatch '^[nN]')

$cfg = [ordered]@{}
$cfg.Company = Ask 'Name on the checks (as on the bank account)' $(if ($old) { $old.Company } else { 'Sisyphus Brewing' })
$cfg.Address = @((Ask 'Address line 1' $(if ($old) { $old.Address[0] } else { '712 Ontario Ave W' })),
                 (Ask 'Address line 2' $(if ($old) { $old.Address[1] } else { 'Minneapolis, MN 55403' })))
if ($keepBank) {
    $cfg.BankName = $old.BankName; $cfg.BankCity = $old.BankCity; $cfg.Routing = $old.Routing; $cfg.Account = $old.Account
} else {
    $cfg.BankName = Ask 'Bank name (printed on the check)' ''
    $cfg.BankCity = Ask 'Bank city, state' ''
    $cfg.Routing = AskTwice 'Routing number (9 digits, bottom left of a paper check)' { param($v) RoutingOk $v } 'That is not a valid routing number. Check the digits.'
    $cfg.Account = AskTwice 'Account number' { param($v) $v -match '^[0-9-]{4,17}$' } 'Digits only (dashes ok), 4 to 17 of them.'
}

'Printers on this PC:'
$printers = @(Get-Printer | Select-Object -ExpandProperty Name)
for ($i = 0; $i -lt $printers.Count; $i++) { "  $($i + 1). $($printers[$i])" }
# Checks get their own small Brother with MICR toner (Sam, Nov 18 2026: "I do
# print a lot", so the office Brother keeps its normal toner). Name it with
# "Check" in Windows, or it is found by model (TN760-size: HL-L2350/2370/2390/2395).
$guess = ($printers | Where-Object { $_ -match 'Check' } | Select-Object -First 1)
if (-not $guess) { $guess = ($printers | Where-Object { $_ -match 'L2350|L2370|L2390|L2395' } | Select-Object -First 1) }
$pick = Ask 'Which one prints checks (number)' $(if ($guess) { [array]::IndexOf($printers, $guess) + 1 } else { 1 })
$cfg.Printer = $printers[[int]$pick - 1]
$cfg.Bin = Ask 'Paper tray: Enter for the main tray, or type "Manual" to print only from the manual feed slot' $(if ($old) { $old.Bin } else { '' })
$cfg.MaxAmount = [double](Ask 'Most this PC will ever print on one check, in dollars' $(if ($old) { $old.MaxAmount } else { 10000 }))
$cfg.OffsetX = [double](Ask 'Nudge right, inches (0 unless the sample was off)' $(if ($old) { $old.OffsetX } else { 0 }))
$cfg.OffsetY = [double](Ask 'Nudge down, inches' $(if ($old) { $old.OffsetY } else { 0 }))

$sig = Ask 'Signature image (scan of Sam signing on white paper; Enter to keep the current one)' ''
if ($sig) {
    Add-Type -AssemblyName System.Drawing
    $img = [Drawing.Image]::FromFile((Resolve-Path $sig))
    $img.Save("$state\signature.png", [Drawing.Imaging.ImageFormat]::Png)
    $img.Dispose()
    "Saved the signature. You may want to delete $sig now."
}

[pscustomobject]$cfg | Export-Clixml "$state\checks.xml"
foreach ($f in "$state\checks.xml", "$state\signature.png") {
    if (Test-Path $f) { icacls $f /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null }
}

$task = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $dir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dir\checks.ps1`""
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Sisyphus checks' -Action $task -Trigger $every -Settings $set -Force | Out-Null

if ((Read-Host 'Print a VOID alignment sample on plain paper now? (Y/n)') -notmatch '^[nN]') {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\checks.ps1" -Sample
    'Hold the sample over a sheet of check stock against a window. If the check lines up, you are done.'
    'If not, run this again and set the nudge.'
}
'Check printing is on. Checks print here a minute after Sam approves them.'
