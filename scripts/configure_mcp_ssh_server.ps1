# Executar uma vez como Administrador no PC que hospeda a Nebula.
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Abra o PowerShell como Administrador e execute este script novamente."
}

$capability = Get-WindowsCapability -Online |
    Where-Object Name -Like "OpenSSH.Server*" |
    Select-Object -First 1
if (-not $capability) {
    throw "O recurso OpenSSH Server nao foi encontrado neste Windows."
}
if ($capability.State -ne "Installed") {
    Add-WindowsCapability -Online -Name $capability.Name | Out-Null
}

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd

$rule = Get-NetFirewallRule -Name "Nebula-MCP-SSH" -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -Name "Nebula-MCP-SSH" `
        -DisplayName "Nebula MCP via SSH" `
        -Direction Inbound -Enabled True -Protocol TCP -Action Allow `
        -LocalPort 22 -Profile Private | Out-Null
}

$service = Get-Service sshd
Write-Host "OpenSSH Server: $($service.Status); inicializacao $($service.StartType)."
Write-Host "Destino do notebook: $env:USERNAME@$env:COMPUTERNAME"
