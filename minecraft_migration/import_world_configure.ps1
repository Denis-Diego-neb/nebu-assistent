$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$server = "C:\NebulaMinecraft\Cubbleverse"
$outerBackup = "C:\NebulaDeploy\Mundo cobbleverse Aternos.zip"
$backupDirectory = "D:\NebulaMinecraftBackups"
$backupCopy = Join-Path $backupDirectory "Mundo cobbleverse Aternos-original.zip"
$importStage = "C:\NebulaMinecraft\.world-import-Cubbleverse"
$nestedWorldZip = Join-Path $backupDirectory ".world-import-Cubbleverse.zip"
$worldTarget = Join-Path $server "world"

if (-not (Test-Path -LiteralPath $server)) { throw "Servidor Cubbleverse nao encontrado." }
if (-not (Test-Path -LiteralPath $outerBackup)) { throw "Backup do Aternos nao encontrado." }
if (Test-Path -LiteralPath $worldTarget) { throw "A pasta world ja existe; importacao cancelada para nao sobrescrever dados." }
if (Test-Path -LiteralPath $importStage) {
    # Somente a pasta temporaria fixa desta importacao e removida ao retomar.
    Remove-Item -LiteralPath $importStage -Recurse -Force
}

New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$sourceHash = (Get-FileHash -LiteralPath $outerBackup -Algorithm SHA256).Hash
if (-not (Test-Path -LiteralPath $backupCopy)) {
    Write-Host "Copiando backup original para o HD de 1 TB..."
    Copy-Item -LiteralPath $outerBackup -Destination $backupCopy
}
$copyHash = (Get-FileHash -LiteralPath $backupCopy -Algorithm SHA256).Hash
if ($copyHash -ne $sourceHash) { throw "A copia de seguranca no HD nao corresponde ao arquivo original." }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($outerBackup)
try {
    $worldEntry = $archive.Entries | Where-Object FullName -EQ "Mundo cobbleverse Aternos/world.zip" | Select-Object -First 1
    if (-not $worldEntry) { throw "world.zip nao encontrado dentro do backup do Aternos." }

    Write-Host "Extraindo o mundo..."
    if ((Test-Path -LiteralPath $nestedWorldZip) -and ((Get-Item -LiteralPath $nestedWorldZip).Length -ne $worldEntry.Length)) {
        Remove-Item -LiteralPath $nestedWorldZip -Force
    }
    if (-not (Test-Path -LiteralPath $nestedWorldZip)) {
        [IO.Compression.ZipFileExtensions]::ExtractToFile($worldEntry, $nestedWorldZip, $false)
    }

    foreach ($name in @("server.properties", "ops.json", "whitelist.json", "banned-ips.json", "banned-players.json")) {
        $entryName = "Mundo cobbleverse Aternos/$name"
        $entry = $archive.Entries | Where-Object FullName -EQ $entryName | Select-Object -First 1
        if ($entry) {
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $server $name), $true)
        }
    }
}
finally {
    $archive.Dispose()
}

New-Item -ItemType Directory -Path $importStage | Out-Null
$worldArchive = [IO.Compression.ZipFile]::OpenRead($nestedWorldZip)
try {
    $destinationRoot = [IO.Path]::GetFullPath($importStage + [IO.Path]::DirectorySeparatorChar)
    foreach ($entry in $worldArchive.Entries) {
        $relativeName = $entry.FullName.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $destination = [IO.Path]::GetFullPath((Join-Path $importStage $relativeName))
        if (-not $destination.StartsWith($destinationRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Entrada insegura encontrada no ZIP: $($entry.FullName)"
        }
        if ([string]::IsNullOrEmpty($entry.Name)) {
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            continue
        }
        $parent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $inputStream = $entry.Open()
        $outputStream = [IO.File]::Create($destination)
        try { $inputStream.CopyTo($outputStream) }
        finally {
            $outputStream.Dispose()
            $inputStream.Dispose()
        }
    }
}
finally {
    $worldArchive.Dispose()
}
$extractedWorld = Join-Path $importStage "world"
if (-not (Test-Path -LiteralPath (Join-Path $extractedWorld "level.dat"))) {
    throw "O mundo extraido nao contem level.dat. A importacao foi interrompida."
}
Move-Item -LiteralPath $extractedWorld -Destination $worldTarget
Remove-Item -LiteralPath $nestedWorldZip -Force
Remove-Item -LiteralPath $importStage -Force

function Set-ServerProperty {
    param([string]$Path, [string]$Name, [string]$Value)
    $lines = [Collections.Generic.List[string]](Get-Content -LiteralPath $Path)
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([regex]::Escape($Name))=") {
            $lines[$index] = "$Name=$Value"
            $found = $true
        }
    }
    if (-not $found) { $lines.Add("$Name=$Value") }
    Set-Content -LiteralPath $Path -Value $lines -Encoding ascii
}

$properties = Join-Path $server "server.properties"
Set-ServerProperty $properties "server-ip" ""
Set-ServerProperty $properties "server-port" "25565"
Set-ServerProperty $properties "query.port" "25565"
Set-ServerProperty $properties "online-mode" "false"
Set-ServerProperty $properties "enforce-secure-profile" "false"
Set-ServerProperty $properties "pause-when-empty-seconds" "-1"
Set-ServerProperty $properties "motd" "Cubbleverse Nebula - Radmin"
Set-Content -LiteralPath (Join-Path $server "eula.txt") -Value "eula=true" -Encoding ascii

$startScript = @'
$ErrorActionPreference = "Stop"
$server = "C:\NebulaMinecraft\Cubbleverse"
$java = "C:\NebulaMinecraft\Runtime-Temurin-21\jdk-21.0.12.1+1-jre\bin\java.exe"
Set-Location -LiteralPath $server
& $java -Xms4G -Xmx6G -XX:+UseG1GC -jar "fabric-server-launch.jar" nogui
exit $LASTEXITCODE
'@
Set-Content -LiteralPath (Join-Path $server "start_server.ps1") -Value $startScript -Encoding utf8

$oldRule = Get-NetFirewallRule -DisplayName "Nebula Minecraft Radmin" -ErrorAction SilentlyContinue
if ($oldRule) { Remove-NetFirewallRule -DisplayName "Nebula Minecraft Radmin" }
New-NetFirewallRule -DisplayName "Nebula Minecraft Radmin" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 25565 -InterfaceAlias "Radmin VPN" -RemoteAddress "26.0.0.0/8" -Profile Any | Out-Null

$worldFiles = (Get-ChildItem -LiteralPath $worldTarget -Recurse -File | Measure-Object).Count
$worldBytes = (Get-ChildItem -LiteralPath $worldTarget -Recurse -File | Measure-Object Length -Sum).Sum
@{
    imported_at = (Get-Date -Format s)
    source_sha256 = $sourceHash
    backup_sha256 = $copyHash
    world_files = $worldFiles
    world_bytes = $worldBytes
    memory_min = "4G"
    memory_max = "6G"
    address = "26.167.19.80:25565"
    chunky_generation_started = $false
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $server "nebula-world-import.json") -Encoding utf8

Write-Host "Mundo importado, backup verificado e servidor configurado para 6 GB e Radmin."
