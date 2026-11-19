# Prints comic checks that Sam approved (Sam, Nov 18 2026: "Need secure
# checks for printing at the taproom for comedians, can only work on my
# approval"). Runs every minute on the office PC from the task "Sisyphus
# checks".
#
# How it stays safe:
# - It only ever gets checks Sam approved. The database won't hand it anything
#   else, and only Sam's owner login can approve (see
#   supabase/migrations/20261119060000_comic_checks.sql).
# - The bank's routing and account numbers and Sam's signature live only on
#   this PC, in %USERPROFILE%\.sisyphus, encrypted by Windows for this one
#   Windows user (DPAPI). They are never sent anywhere; they go on the check
#   as it prints, and the print files are deleted right after.
# - This script is NOT pulled fresh from GitHub each run (the backup scripts
#   are). setup-checks.ps1 installs a copy once, so a change to the repo can't
#   change what this PC does with the bank numbers. Updating it means running
#   setup again at the PC.
# - It refuses a check over the PC's own limit (MaxAmount, $10,000 unless set
#   otherwise at setup) and a routing number whose check digit is wrong.
#
# It proves who it is with the same code as the heartbeat
# (%USERPROFILE%\.sisyphus\heartbeat-code.txt). The anon key below is the
# public one every staff page already carries.
param([switch]$Sample)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$state = "$env:USERPROFILE\.sisyphus"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = "$state\checks.log"
function Log($m) { "$(Get-Date -Format s)  $m" | Add-Content $log }

$api = 'https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/'
$anon = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ'
function Rpc($name, $body) {
    Invoke-RestMethod -Method Post -Uri ($api + $name) -ContentType 'application/json; charset=utf-8' -TimeoutSec 30 `
        -Headers @{ apikey = $anon; Authorization = "Bearer $anon" } `
        -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 5)))
}

function Plain($secure) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

# ABA check digit: a mistyped routing number never prints.
function RoutingOk([string]$r) {
    if ($r -notmatch '^\d{9}$') { return $false }
    $d = $r.ToCharArray() | ForEach-Object { [int]"$_" }
    return ((3 * ($d[0] + $d[3] + $d[6]) + 7 * ($d[1] + $d[4] + $d[7]) + ($d[2] + $d[5] + $d[8])) % 10) -eq 0
}

function FindExe($names) {
    foreach ($n in $names) { if (Test-Path $n) { return $n } }
    return $null
}
$edge = FindExe @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
$sumatra = FindExe @("$env:LOCALAPPDATA\SumatraPDF\SumatraPDF.exe", "$env:ProgramFiles\SumatraPDF\SumatraPDF.exe")

# Turn one check into a PDF and send it to the printer. Returns a note.
function PrintCheck($c, $cfg, [switch]$NoSignature) {
    $routing = Plain $cfg.Routing
    $account = Plain $cfg.Account
    if (-not (RoutingOk $routing)) { throw 'The routing number on this PC does not check out' }
    $sig = $null
    if (-not $NoSignature -and (Test-Path "$state\signature.png")) {
        $sig = 'data:image/png;base64,' + [Convert]::ToBase64String([IO.File]::ReadAllBytes("$state\signature.png"))
    }
    $data = [ordered]@{
        number = $c.number; date = $c.date; pay_to = $c.pay_to; amount = $c.amount; memo = $c.memo; stub = $c.stub
        routing = $routing; account = $account; company = $cfg.Company; address = @($cfg.Address)
        bank_name = $cfg.BankName; bank_city = $cfg.BankCity; signature = $sig
        offset_x = [double]$cfg.OffsetX; offset_y = [double]$cfg.OffsetY; sample = [bool]$c.sample
    }
    $json = ($data | ConvertTo-Json -Compress -Depth 4) -replace '</', '<\/'
    $font = 'data:font/otf;base64,' + [Convert]::ToBase64String([IO.File]::ReadAllBytes("$here\GnuMICR.otf"))
    $html = (Get-Content "$here\check.html" -Raw -Encoding UTF8).Replace('/*DATA*/null', $json).Replace("url('GnuMICR.otf')", "url('$font')")

    $work = "$state\print"
    New-Item -ItemType Directory -Force $work | Out-Null
    $name = [guid]::NewGuid().ToString('n')
    $htmlPath = "$work\$name.html"; $pdfPath = "$work\$name.pdf"
    try {
        [IO.File]::WriteAllText($htmlPath, $html, (New-Object Text.UTF8Encoding $false))
        $p = Start-Process -FilePath $edge -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
            '--headless=new', '--disable-gpu', '--no-pdf-header-footer', '--virtual-time-budget=5000',
            "--user-data-dir=`"$work\edge`"", "--print-to-pdf=`"$pdfPath`"", ('"file:///' + ($htmlPath -replace '\\', '/') + '"'))
        if (-not (Test-Path $pdfPath)) { throw "Edge made no PDF (exit $($p.ExitCode))" }
        $settings = 'noscale'
        if ($cfg.Bin) { $settings += ",bin=$($cfg.Bin)" }
        $q = Start-Process -FilePath $sumatra -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
            '-print-to', "`"$($cfg.Printer)`"", '-print-settings', $settings, '-silent', "`"$pdfPath`"")
        if ($q.ExitCode -ne 0) { throw "The printer refused it (SumatraPDF exit $($q.ExitCode))" }
        return "sent to $($cfg.Printer)"
    } finally {
        # The print files carry the bank numbers and the signature: gone right away.
        Remove-Item -Force -ErrorAction SilentlyContinue $htmlPath, $pdfPath
    }
}

# Positive pay: one line per printed check, for the bank's upload (kept on this PC only).
function PositivePay($c, $cfg) {
    $dir = "$state\positive-pay"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $file = "$dir\checks-$((Get-Date).ToString('yyyy-MM')).csv"
    if (-not (Test-Path $file)) { 'Account,CheckNumber,IssueDate,Amount,Payee' | Set-Content $file -Encoding UTF8 }
    $payee = '"' + ($c.pay_to -replace '"', '""') + '"'
    "$(Plain $cfg.Account),$($c.number),$($c.date),$('{0:0.00}' -f [double]$c.amount),$payee" | Add-Content $file -Encoding UTF8
}

if (-not (Test-Path "$state\checks.xml")) { Log 'not set up yet (run setup-checks.ps1)'; exit 0 }
$cfg = Import-Clixml "$state\checks.xml"
if (-not $edge -or -not $sumatra) { Log 'Edge or SumatraPDF is missing'; exit 1 }

if ($Sample) {
    # Alignment test on plain paper: real bank line, no signature, VOID across it.
    $c = [pscustomobject]@{ number = 0; date = (Get-Date).ToString('yyyy-MM-dd'); pay_to = 'VOID - alignment test'; amount = 0.01
        memo = 'Sample'; stub = 'Sample check, not payable'; sample = $true }
    PrintCheck $c $cfg -NoSignature
    exit 0
}

$code = (Get-Content "$state\heartbeat-code.txt" -Raw).Trim()
try {
    $checks = @(Rpc 'checks_to_print' @{ p_device = 'office-pc'; p_code = $code })
} catch {
    Log "could not ask for checks: $($_.Exception.Message)"; exit 1
}
foreach ($c in $checks) {
    if ($null -eq $c -or -not $c.id) { continue }
    $ok = $false; $note = ''
    try {
        $max = if ($cfg.MaxAmount) { [double]$cfg.MaxAmount } else { 10000 }
        if ([double]$c.amount -gt $max) { throw "Over this PC's limit of `$$max; not printed" }
        $note = PrintCheck $c $cfg
        PositivePay $c $cfg
        $ok = $true
    } catch {
        $note = $_.Exception.Message
    }
    Log "check $($c.number): $(if ($ok) { 'printed' } else { 'NOT printed' }) ($note)"
    try { Rpc 'check_printed' @{ p_device = 'office-pc'; p_code = $code; p_id = $c.id; p_ok = $ok; p_note = $note } | Out-Null }
    catch { Log "could not report check $($c.number): $($_.Exception.Message)" }
}
