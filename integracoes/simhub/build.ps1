[CmdletBinding()]
param(
    [switch] $Deploy
)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$simHubCandidates = @(
    'C:\Program Files (x86)\SimHub',
    'C:\Program Files\SimHub'
)
$simHubDirectory = $simHubCandidates | Where-Object {
    Test-Path -LiteralPath (Join-Path $_ 'SimHub.Plugins.dll')
} | Select-Object -First 1
if (-not $simHubDirectory) {
    throw 'SimHub não está instalado. Instale-o primeiro e execute este script novamente.'
}

& dotnet build (Join-Path $projectDirectory 'NebulaSimHub.csproj') --configuration Release "-p:SimHubDir=$simHubDirectory"
if ($LASTEXITCODE -ne 0) {
    throw 'A compilação do plugin do SimHub falhou.'
}
$output = Join-Path $projectDirectory 'bin\Release\net48\NebulaSimHub.dll'
if ($Deploy) {
    if (Get-Process SimHubWPF -ErrorAction SilentlyContinue) {
        throw 'Feche o SimHub antes de instalar o plugin NebulaSimHub.'
    }
    Copy-Item -LiteralPath $output -Destination (Join-Path $simHubDirectory 'NebulaSimHub.dll') -Force
    Write-Host 'Plugin instalado. Abra o SimHub e habilite Nebula RPM Telemetry em Settings > Plugins.'
} else {
    Write-Host "Plugin compilado: $output"
}
