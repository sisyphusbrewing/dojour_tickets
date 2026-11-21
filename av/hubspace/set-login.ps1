# Stores Sam's Hubspace login in Windows Credential Locker ("sisyphus-hubspace")
# and logs in once so the helper has a working token. Sam runs it himself; it asks
# for the email, password and, if Hubspace sends one, the emailed code.
# The password goes straight to Credential Locker and is never shown or saved anywhere else.
$here = Split-Path $MyInvocation.MyCommand.Path
$py = Join-Path $here 'hubspace.py'

$email = Read-Host 'Hubspace email'
$secure = Read-Host 'Hubspace password' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$OutputEncoding = New-Object Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'
try {
    "$email`n$([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr))" | py -3 $py --store
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ($LASTEXITCODE -ne 0) { Read-Host 'Something went wrong. Press Enter to close'; exit 1 }

py -3 $py --login
if ($LASTEXITCODE -eq 0) {
    # Restart the helper so it picks up the new login.
    Get-CimInstance Win32_Process -Filter "Name like 'py%.exe'" |
        Where-Object CommandLine -like '*hubspace.py*' | Where-Object CommandLine -notlike '*--*' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}
Read-Host 'Done. Press Enter to close'
