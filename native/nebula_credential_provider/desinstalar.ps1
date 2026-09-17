$ErrorActionPreference = "Stop"
$providerId = "{B5C61DE8-44CD-4BF6-90D9-283726850FF2}"
Unregister-ScheduledTask -TaskName "Nebula Unlock Agent" -Confirm:$false `
    -ErrorAction SilentlyContinue
Get-Process NebulaUnlockAgent -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -LiteralPath (
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$providerId"
) -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ("Registry::HKEY_CLASSES_ROOT\CLSID\$providerId") `
    -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:ProgramData "Nebula\windows_password.bin") `
    -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:ProgramData "Nebula\unlock.authorized") `
    -Force -ErrorAction SilentlyContinue
Write-Host "Credential Provider desregistrado e credencial removida. Reinicie o Windows."
