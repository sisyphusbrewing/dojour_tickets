# One-time setup for the office show PC, so that after a restart or power cut anyone can press the power
# button and the show rig (Companion for the Stream Deck, OBS, Spotify, X AIR Edit) comes back by itself.
# Run once on that PC in PowerShell opened with "Run as administrator":
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((New-Object Net.WebClient).DownloadString('https://sisyphusbrewing.github.io/dojour_tickets/av/pc-setup.ps1')))"
# Safe to run again; it only sets things to the same values. What it does:
#   - never sleeps or hibernates on mains power, and keeps USB awake (Stream Deck, XR18 audio)
#   - Windows Update may not restart while someone is signed in, and active hours cover noon to 2 am
#   - starts Companion, OBS, Spotify and X AIR Edit at sign-in (shortcuts in the Startup folder)
#   - unhides the "users must enter a password" box and opens netplwiz for the one manual auto sign-in step

$ErrorActionPreference = "Stop"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
  Write-Warning "Needs admin: right-click Windows PowerShell, choose Run as administrator, and paste the line again."
  return
}
function Say($msg) { Write-Host "  $msg" }

Write-Host "Power"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 30
# USB selective suspend off, so the Stream Deck and the XR18's USB audio never get put to sleep
powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /setactive SCHEME_CURRENT
Say "never sleeps, screen off after 30 min, USB stays awake"

Write-Host "Windows Update"
$ux = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
New-Item -Force -Path $ux | Out-Null
Set-ItemProperty $ux ActiveHoursStart 12 -Type DWord
Set-ItemProperty $ux ActiveHoursEnd 2 -Type DWord
$au = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
New-Item -Force -Path $au | Out-Null
Set-ItemProperty $au NoAutoRebootWithLoggedOnUsers 1 -Type DWord
Say "no automatic restarts while signed in; active hours noon to 2 am"

Write-Host "Start at sign-in"
$startup = [Environment]::GetFolderPath("Startup")
$menus = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
$desktops = @([Environment]::GetFolderPath("Desktop"), "$env:PUBLIC\Desktop")
$shell = New-Object -ComObject WScript.Shell
function Find-Exe($names, $roots) {
  foreach ($root in $roots | Where-Object { Test-Path $_ }) {
    $hit = Get-ChildItem $root -Recurse -Depth 4 -File -ErrorAction SilentlyContinue |
      Where-Object { $names -contains $_.Name } | Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
}
function Find-Shortcut($pattern) {
  Get-ChildItem ($menus + $desktops | Where-Object { Test-Path $_ }) -Recurse -Filter *.lnk -ErrorAction SilentlyContinue |
    Where-Object { $_.BaseName -like $pattern } | Select-Object -First 1
}
function Add-Startup($name, $target, $arguments = "") {
  $lnk = $shell.CreateShortcut((Join-Path $startup "$name.lnk"))
  $lnk.TargetPath = $target
  $lnk.Arguments = $arguments
  $lnk.WorkingDirectory = Split-Path $target
  $lnk.WindowStyle = 7  # minimized
  $lnk.Save()
  Say "$name -> $target $arguments"
}
$apps = @(
  @{ Name = "Companion"; Shortcut = "*Companion*"; Exe = @("Companion Launcher.exe", "Companion.exe");
     Roots = @("$env:ProgramFiles\Companion", "$env:LOCALAPPDATA\Programs") },
  # --disable-shutdown-check skips OBS's "run in safe mode?" question after a crash or power cut
  @{ Name = "OBS Studio"; Shortcut = "OBS Studio*"; Exe = @("obs64.exe"); Args = "--disable-shutdown-check";
     Roots = @("$env:ProgramFiles\obs-studio") },
  @{ Name = "Spotify"; Shortcut = "Spotify"; Exe = @("Spotify.exe"); Roots = @("$env:APPDATA\Spotify") },
  @{ Name = "X AIR Edit"; Shortcut = "X*AIR*Edit*"; Exe = @("X-AIR-Edit.exe", "X AIR Edit.exe", "X-AIR Edit.exe");
     Roots = @($desktops + "$env:USERPROFILE\Downloads" + "$env:ProgramFiles" + "${env:ProgramFiles(x86)}") }
)
$missing = @()
foreach ($app in $apps) {
  $target = Find-Exe $app.Exe $app.Roots
  if (-not $target) {
    $found = Find-Shortcut $app.Shortcut
    if ($found) { $target = $shell.CreateShortcut($found.FullName).TargetPath }
  }
  if ($target -and (Test-Path $target)) { Add-Startup $app.Name $target $app.Args }
  elseif ($app.Name -eq "Spotify" -and (Get-AppxPackage -Name "SpotifyAB.SpotifyMusic" -ErrorAction SilentlyContinue)) {
    Add-Startup "Spotify" "$env:WINDIR\explorer.exe" "spotify:"
  } else { $missing += $app.Name }
}
if ($missing) { Write-Warning "Not found: $($missing -join ', '). Drag its shortcut into the folder that opens next." ; explorer $startup }

Write-Host "Auto sign-in"
$pl = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device"
New-Item -Force -Path $pl | Out-Null
Set-ItemProperty $pl DevicePasswordLessBuildVersion 0 -Type DWord
Say "In the window that opens: pick your account, untick 'Users must enter a user name and password',"
Say "click OK and type your password twice. Windows then signs in by itself at power on."
Start-Process netplwiz

Write-Host ""
Write-Host "Done. Restart the PC once to check everything comes back on its own."
