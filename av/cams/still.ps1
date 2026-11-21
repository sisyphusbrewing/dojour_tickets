# A still picture from one of the Wyze cameras on the office PC (Nov 20 2026), e.g. to check
# that the taproom lights look right after a deck look changes them.
#   powershell -ExecutionPolicy Bypass -File still.ps1 -List                # the camera names
#   powershell -ExecutionPolicy Bypass -File still.ps1 -Cam taproom         # saves a .jpg, prints where
#   powershell -ExecutionPolicy Bypass -File still.ps1 -All                 # one of each camera
# Pictures land in %USERPROFILE%\sisyphus-av\cams\stills\ and the ones older than 7 days are
# removed. It asks go2rtc on this PC only, and never prints camera addresses or keys.
param([string]$Cam = '', [switch]$List, [switch]$All, [int]$Width = 1280)
$ErrorActionPreference = 'Stop'
$api = 'http://127.0.0.1:1984/api'
$out = "$env:USERPROFILE\sisyphus-av\cams\stills"
New-Item -ItemType Directory -Force $out | Out-Null
Get-ChildItem $out -Filter *.jpg | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force

try { $r = Invoke-RestMethod "$api/streams" -TimeoutSec 5; $names = if ($r) { @($r.PSObject.Properties.Name) } else { @() } }
catch { throw 'go2rtc is not answering on this PC. Run setup.ps1, or see %USERPROFILE%\.sisyphus\cams.log' }

if ($List -or (-not $Cam -and -not $All)) {
    if ($names) { "Cameras: " + ($names -join ', ') } else { 'No cameras yet: add them on http://127.0.0.1:1984/add.html (Add > Wyze).' }
    return
}
$want = if ($All) { $names } else { @($Cam) }
foreach ($n in $want) {
    if ($names -notcontains $n) { Write-Warning "No camera named '$n'. Cameras: $($names -join ', ')"; continue }
    $file = Join-Path $out ("{0}-{1:yyyyMMdd-HHmmss}.jpg" -f $n, (Get-Date))
    try {
        Invoke-WebRequest -UseBasicParsing "$api/frame.jpeg?src=$([uri]::EscapeDataString($n))&width=$Width" -OutFile $file -TimeoutSec 30
        if ((Get-Item $file).Length -lt 1000) { throw 'empty picture' }
        $file
    } catch {
        Remove-Item $file -ErrorAction SilentlyContinue
        Write-Warning "No picture from '$n': $($_.Exception.Message)"
    }
}
