# Prints today's taproom menu (menu/print.html, live from GoTab) on the office PC's printer.
# The Stream Deck PRINT MENU key no longer uses this script: it runs the same steps as one plain cmd line
# (PRINT_MENU_COMMAND in av/companion/build_companion_config.py), because Defender flags a PowerShell line
# that downloads a script and runs it as a virus (Oct 28 2026). Kept as a manual fallback: save it on the PC
# and run  powershell -NoProfile -File print-menu.ps1
# Uses Microsoft Edge (built into Windows) and SumatraPDF for silent printing (installed with winget on first run).
# A log of each press is in %TEMP%\sisyphus-menu\print-menu.log.
# Options: -Copies 3 for more than one sheet, -Printer "Name" for a printer other than the Windows default.
param([int]$Copies = 1, [string]$Printer = "")

$ErrorActionPreference = "Stop"
$work = Join-Path $env:TEMP "sisyphus-menu"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$pdf = Join-Path $work "taproom-menu.pdf"
$log = Join-Path $work "print-menu.log"
function Log($msg) { "$(Get-Date -Format s)  $msg" | Add-Content $log }

function First-Existing($paths) { $paths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1 }
$browser = First-Existing @(
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe")
$sumatra = First-Existing @(
  "$env:LOCALAPPDATA\SumatraPDF\SumatraPDF.exe",
  "$env:ProgramFiles\SumatraPDF\SumatraPDF.exe",
  "${env:ProgramFiles(x86)}\SumatraPDF\SumatraPDF.exe")
try {
  if (-not $sumatra) {
    Log "installing SumatraPDF"
    winget install -e --id SumatraPDF.SumatraPDF --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $sumatra = First-Existing @("$env:LOCALAPPDATA\SumatraPDF\SumatraPDF.exe", "$env:ProgramFiles\SumatraPDF\SumatraPDF.exe")
  }
  if (-not $browser) { throw "Edge or Chrome not found" }
  if (-not $sumatra) { throw "SumatraPDF not found and winget could not install it" }

  # Render the page headless to a PDF. Its own profile folder keeps it apart from any open Edge window;
  # the virtual time budget lets the menu feed and fonts load before the page is printed.
  Remove-Item $pdf -ErrorAction SilentlyContinue
  $url = "https://staff.sisyphusbrewing.com/menu/print.html?t=$([DateTimeOffset]::Now.ToUnixTimeSeconds())"
  Start-Process -FilePath $browser -Wait -WindowStyle Hidden -ArgumentList @(
    "--headless=new", "--disable-gpu", "--no-first-run", "--user-data-dir=`"$work\profile`"",
    "--no-pdf-header-footer", "--virtual-time-budget=15000", "--print-to-pdf=`"$pdf`"", $url)
  if (-not (Test-Path $pdf) -or (Get-Item $pdf).Length -lt 20000) { throw "menu PDF was not made (no internet?)" }

  # @(...) around the if keeps a one-item result an array; otherwise "+" below glues every argument
  # into one string and SumatraPDF opens the PDF instead of printing it.
  $target = @(if ($Printer) { "-print-to", "`"$Printer`"" } else { "-print-to-default" })
  Start-Process -FilePath $sumatra -Wait -WindowStyle Hidden -ArgumentList ($target + @("-print-settings", "`"noscale,${Copies}x`"", "-silent", "`"$pdf`""))
  Log "printed $Copies copy(ies) to $(if ($Printer) { $Printer } else { 'default printer' })"
} catch {
  Log "FAILED: $_"
  exit 1
}
