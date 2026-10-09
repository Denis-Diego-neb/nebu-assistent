param(
    # IPs que podem usar o Ollama deste notebook. Sem valor, usa
    # NEBULA_OLLAMA_CLIENTS (separados por vírgula) ou o PC gamer na LAN e no
    # Tailscale. Use -Clientes "" para fechar a porta para todos os aparelhos.
    [string[]]$Clientes = $null
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Proteger o Ollama exige uma sessao administrativa. Abra PROTEGER-OLLAMA.cmd."
}

$porta = 11434
# O mesmo nome é consultado por iniciar_servicos_notebook.ps1 antes de abrir o
# Ollama para a rede.
$regraBloqueio = "Nebula Ollama - bloquear outros aparelhos"
$regraPc = "Nebula Ollama - PC"

function ConvertTo-NumeroIp([string]$ip) {
    $bytes = ([System.Net.IPAddress]::Parse($ip)).GetAddressBytes()
    return [long]$bytes[0] * 16777216 + [long]$bytes[1] * 65536 + [long]$bytes[2] * 256 + [long]$bytes[3]
}

function ConvertTo-TextoIp([long]$numero) {
    return "{0}.{1}.{2}.{3}" -f (($numero -shr 24) -band 255), (($numero -shr 16) -band 255),
        (($numero -shr 8) -band 255), ($numero -band 255)
}

function Get-FaixasBloqueadas([string[]]$Liberados) {
    # Todo o IPv4 menos o loopback e os IPs liberados, em faixas "inicio-fim".
    # O bloqueio vence qualquer permissão, inclusive a regra que o Windows cria
    # para o ollama.exe quando alguém clica em "Permitir acesso".
    $livres = @(@{ Inicio = (ConvertTo-NumeroIp "127.0.0.0"); Fim = (ConvertTo-NumeroIp "127.255.255.255") })
    foreach ($ip in $Liberados) {
        $numero = ConvertTo-NumeroIp $ip
        $livres += @{ Inicio = $numero; Fim = $numero }
    }
    $faixas = @()
    $proximo = [long]0
    foreach ($livre in ($livres | Sort-Object { $_.Inicio })) {
        if ($livre.Inicio -gt $proximo) {
            $fim = $livre.Inicio - 1
            $faixas += if ($fim -eq $proximo) { ConvertTo-TextoIp $proximo } else {
                "$(ConvertTo-TextoIp $proximo)-$(ConvertTo-TextoIp $fim)"
            }
        }
        if ($livre.Fim + 1 -gt $proximo) { $proximo = $livre.Fim + 1 }
    }
    if ($proximo -le 4294967295) {
        $faixas += "$(ConvertTo-TextoIp $proximo)-255.255.255.255"
    }
    # O PC fala com o notebook por IPv4; no IPv6 só o loopback (::1) passa.
    return $faixas + @("::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff")
}

if ($null -eq $Clientes) {
    $configurado = [Environment]::GetEnvironmentVariable("NEBULA_OLLAMA_CLIENTS", "User")
    $Clientes = if ($configurado) { $configurado -split "[,;\s]+" } else {
        @("192.168.15.12", "100.92.82.41")
    }
}
$Clientes = @($Clientes | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() })
foreach ($ip in $Clientes) {
    $endereco = $null
    if (-not [System.Net.IPAddress]::TryParse($ip, [ref]$endereco) -or
        $endereco.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        $ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or
        $ip.StartsWith("127.") -or $ip -eq "0.0.0.0") {
        throw "Endereco de cliente invalido para o Ollama: '$ip'. Use IPv4 do PC, como 192.168.15.12."
    }
}

# Os próprios endereços do notebook também ficam de fora do bloqueio: a Nebula
# local pode chamar o Ollama pelo IP da LAN.
$locais = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    ForEach-Object { $_.IPAddress } | Where-Object { $_ -notlike "169.254.*" })

Get-NetFirewallRule -DisplayName "Nebula Ollama*" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $regraBloqueio -Direction Inbound -Action Block `
    -Protocol TCP -LocalPort $porta -Profile Any `
    -RemoteAddress (Get-FaixasBloqueadas (@($Clientes) + $locais | Select-Object -Unique)) | Out-Null
if ($Clientes) {
    New-NetFirewallRule -DisplayName $regraPc -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $porta -Profile Any -RemoteAddress $Clientes | Out-Null
    [Environment]::SetEnvironmentVariable("NEBULA_OLLAMA_CLIENTS", ($Clientes -join ","), "User")
    Write-Host "Ollama protegido: a porta $porta aceita somente $($Clientes -join ', ')."
} else {
    Write-Host "Ollama fechado para a rede: nenhum outro aparelho alcanca a porta $porta."
}

$ouvindo = @(Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { $_.LocalAddress } | Select-Object -Unique)
if ($ouvindo) {
    Write-Host "O Ollama escuta em: $($ouvindo -join ', ')."
}
