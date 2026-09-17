$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$assets = "C:\NebulaDeploy\MinecraftInstall"
$root = "C:\NebulaMinecraft"
$server = Join-Path $root "Cubbleverse"
$serverStage = Join-Path $root ".staging-Cubbleverse-1.7.42"
$runtime = Join-Path $root "Runtime-Temurin-21"
$runtimeStage = Join-Path $root ".staging-Runtime-Temurin-21"
$backup = "D:\NebulaMinecraftBackups"
$log = Join-Path $assets "resultado-instalacao-cubbleverse.txt"
$javaArchive = Join-Path $assets "OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip"
$pack = Join-Path $assets "COBBLEVERSE-1.7.42.mrpack"
$installer = Join-Path $assets "mrpack-install-windows.exe"
$chunky = Join-Path $assets "Chunky-Fabric-1.4.23.jar"

"Instalação iniciada em $(Get-Date -Format s)" | Set-Content -LiteralPath $log
foreach ($required in @($javaArchive, $pack, $installer, $chunky)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Arquivo necessário ausente: $required"
    }
}
if (Test-Path -LiteralPath $server) {
    throw "Já existe uma instalação do Cubbleverse. Nada foi sobrescrito."
}
if ((Test-Path -LiteralPath $serverStage) -and
    (Get-ChildItem -LiteralPath $serverStage -Force | Select-Object -First 1)) {
    throw "A preparação do Cubbleverse contém arquivos inesperados. Nada foi sobrescrito."
}
if (Test-Path -LiteralPath $runtimeStage) {
    throw "Existe uma extração incompleta do Java. Nada foi sobrescrito."
}

New-Item -ItemType Directory -Path $root, $backup, $serverStage -Force | Out-Null
if (-not (Test-Path -LiteralPath $runtime)) {
    New-Item -ItemType Directory -Path $runtimeStage | Out-Null
    Write-Host "Extraindo Java Temurin 21..."
    Expand-Archive -LiteralPath $javaArchive -DestinationPath $runtimeStage
    $stagedJava = Get-ChildItem -LiteralPath $runtimeStage -Filter java.exe -Recurse |
        Where-Object FullName -Like "*\bin\java.exe" |
        Select-Object -First 1
    if (-not $stagedJava) { throw "java.exe não foi encontrado no pacote Temurin." }
    Move-Item -LiteralPath $runtimeStage -Destination $runtime
}
$java = Get-ChildItem -LiteralPath $runtime -Filter java.exe -Recurse |
    Where-Object FullName -Like "*\bin\java.exe" |
    Select-Object -First 1
$previousErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$javaOutput = & $java.FullName -version 2>&1
$javaExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorPreference
$javaOutput | Tee-Object -FilePath $log -Append
if ($javaExitCode -ne 0) { throw "O Java 21 portátil não iniciou corretamente." }

Write-Host "Instalando o Cubbleverse 1.7.42 para servidor Fabric..."
$previousErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $installer $pack --server-dir $serverStage --server-file fabric-server-launch.jar 2>&1 |
    Tee-Object -FilePath $log -Append
$installerExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorPreference
if ($installerExitCode -ne 0) { throw "O instalador Modrinth retornou erro (código $installerExitCode)." }
if (-not (Test-Path -LiteralPath (Join-Path $serverStage "fabric-server-launch.jar"))) {
    throw "O servidor Fabric não foi criado."
}

$mods = Join-Path $serverStage "mods"
New-Item -ItemType Directory -Path $mods -Force | Out-Null
Copy-Item -LiteralPath $chunky -Destination (Join-Path $mods "Chunky-Fabric-1.4.23.jar")
@{
    modpack = "COBBLEVERSE"
    version = "1.7.42"
    minecraft = "1.21.1"
    fabric_loader = "0.18.4"
    java = $java.FullName
    memory_min = "4G"
    memory_max = "6G"
    chunky = "1.4.23"
    installed_at = (Get-Date -Format s)
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $serverStage "nebula-install.json") -Encoding utf8

Move-Item -LiteralPath $serverStage -Destination $server
"SUCESSO: Cubbleverse e Chunky instalados; mundo ainda não importado." | Add-Content -LiteralPath $log
Write-Host "Cubbleverse 1.7.42, Fabric e Chunky 1.4.23 instalados."
