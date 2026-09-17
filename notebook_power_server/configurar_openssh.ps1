$ErrorActionPreference = "Stop"

$log = Join-Path $PSScriptRoot "resultado-acesso-admin.txt"
$publicKeyFile = Join-Path $PSScriptRoot "nebula_notebook_admin.pub"
"Configuração OpenSSH iniciada em $(Get-Date -Format s)" | Set-Content -LiteralPath $log

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$adminRole = [Security.Principal.WindowsBuiltInRole]::Administrator
if (-not $principal.IsInRole($adminRole)) {
    throw "Este instalador precisa ser executado como administrador."
}
if (-not (Test-Path -LiteralPath $publicKeyFile)) {
    throw "A chave pública da Nebula não foi encontrada ao lado do instalador."
}

$capability = Get-WindowsCapability -Online |
    Where-Object Name -Like "OpenSSH.Server*" |
    Select-Object -First 1
if (-not $capability) {
    throw "O recurso OpenSSH Server não está disponível nesta instalação do Windows."
}
if ($capability.State -ne "Installed") {
    Write-Host "Instalando o OpenSSH Server oficial do Windows..."
    try {
        $capability = Add-WindowsCapability -Online -Name $capability.Name
    } catch {
        if ($_.Exception.Message -match "pendente|pending") {
            "REINÍCIO NECESSÁRIO: o Windows possui operações de manutenção pendentes." |
                Add-Content -LiteralPath $log
            Write-Host "O Windows possui operações pendentes. Reinicie o notebook, entre na conta e execute este instalador novamente."
            exit 2
        }
        throw
    }
    if ($capability.RestartNeeded) {
        "REINÍCIO NECESSÁRIO: execute este instalador novamente após reiniciar." |
            Add-Content -LiteralPath $log
        Write-Host "O Windows pediu reinicialização. Reinicie e execute este arquivo novamente."
        exit 2
    }
}

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd -ErrorAction SilentlyContinue

$sshDirectory = Join-Path $env:ProgramData "ssh"
$authorizedKeys = Join-Path $sshDirectory "administrators_authorized_keys"
New-Item -ItemType Directory -Path $sshDirectory -Force | Out-Null
$publicKey = (Get-Content -LiteralPath $publicKeyFile -Raw).Trim()
$existingKeys = if (Test-Path -LiteralPath $authorizedKeys) {
    Get-Content -LiteralPath $authorizedKeys -ErrorAction SilentlyContinue
} else {
    @()
}
if ($publicKey -notin $existingKeys) {
    Add-Content -LiteralPath $authorizedKeys -Value $publicKey -Encoding ascii
}

# OpenSSH recusa o arquivo se usuários comuns puderem alterá-lo. Os SIDs evitam
# depender do idioma usado nos nomes "SYSTEM" e "Administradores" do Windows.
& icacls.exe $authorizedKeys /inheritance:r /grant "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Não foi possível proteger o arquivo de chaves administrativas."
}

Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue |
    Disable-NetFirewallRule
Get-NetFirewallRule -DisplayName "Nebula SSH Server" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "Nebula SSH Server" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 22 `
    -RemoteAddress @("LocalSubnet", "100.64.0.0/10") | Out-Null

$sshd = Join-Path $env:WINDIR "System32\OpenSSH\sshd.exe"
& $sshd -t
if ($LASTEXITCODE -ne 0) {
    throw "A configuração do OpenSSH não passou na validação interna."
}
Restart-Service -Name sshd

@(
    "SUCESSO: OpenSSH instalado e iniciado."
    "Computador: $env:COMPUTERNAME"
    "Usuário que executou: $env:USERNAME"
    "Porta: 22, restrita a LocalSubnet e Tailscale"
) | Add-Content -LiteralPath $log

Write-Host "OpenSSH instalado. A chave da Nebula foi autorizada com sucesso."
Write-Host "A porta 22 está limitada à rede local e ao Tailscale."
