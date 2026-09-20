param(
    [string]$Server = "http://100.78.67.81:8766",
    [string]$Executable = "",
    [switch]$Required
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
if (-not $Executable) {
    $Executable = Join-Path $projectRoot "notebook_power_server\NebulaPowerServer.exe"
}
$versionText = Get-Content -LiteralPath (Join-Path $projectRoot "versao.py") -Raw
$versionMatch = [regex]::Match($versionText, 'VERSAO_NEBULA\s*=\s*["'']([0-9]+\.[0-9]+\.[0-9]+)["'']')
if (-not $versionMatch.Success) { throw "Versao da Nebula nao encontrada." }
$version = $versionMatch.Groups[1].Value
$token = $env:NEBULA_POWER_TOKEN
if ([string]::IsNullOrWhiteSpace($token) -or $token.Length -lt 24) {
    throw "Defina NEBULA_POWER_TOKEN com pelo menos 24 caracteres antes do deploy."
}
$auth = @{ "X-Nebula-Power-Token" = $token }

try {
    $health = Invoke-RestMethod -Uri "$($Server.TrimEnd('/'))/health" -Headers $auth -TimeoutSec 5
    if ($health.features -notcontains "auto_update") {
        throw "O hub instalado ainda nao possui atualizacao automatica. Execute o instalador 1.21.0 uma unica vez no notebook."
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Executable).Hash.ToLowerInvariant()
    $headers = @{
        "X-Nebula-Power-Token" = $token
        "X-Nebula-SHA256" = $hash
        "X-Nebula-Version" = $version
    }
    Invoke-RestMethod -Uri "$($Server.TrimEnd('/'))/update" -Method Post `
        -Headers $headers -ContentType "application/octet-stream" -InFile $Executable `
        -TimeoutSec 180 | Out-Null

    $limite = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Milliseconds 700
        try {
            $novoHealth = Invoke-RestMethod -Uri "$($Server.TrimEnd('/'))/health" `
                -Headers $auth -TimeoutSec 3
            if ($novoHealth.version -eq $version) {
                $assistant = Join-Path $projectRoot "Nebula-$version.exe"
                if ((Test-Path -LiteralPath $assistant) -and
                    ($novoHealth.features -contains "assistant_update")) {
                    $assistantHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $assistant).Hash.ToLowerInvariant()
                    Invoke-RestMethod -Uri "$($Server.TrimEnd('/'))/assistant-update" `
                        -Method Post -Headers @{
                            "X-Nebula-Power-Token" = $token
                            "X-Nebula-SHA256" = $assistantHash
                            "X-Nebula-Version" = $version
                        } -ContentType "application/octet-stream" -InFile $assistant `
                        -TimeoutSec 180 | Out-Null
                }
                Write-Host "Hub do notebook atualizado automaticamente para $version."
                exit 0
            }
        } catch {
            # Reinicio em andamento.
        }
    } while ((Get-Date) -lt $limite)
    throw "O pacote foi enviado, mas o hub nao confirmou a versao $version."
} catch {
    if ($Required) { throw }
    Write-Warning $_.Exception.Message
    exit 3
}
