$ErrorActionPreference = "Stop"

$paths = @(
    "C:\NebulaMinecraft",
    "C:\NebulaMinecraft\Cubbleverse",
    "D:\NebulaMinecraftBackups"
)
$winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
$javaCommands = @(Get-Command java.exe -All -ErrorAction SilentlyContinue | ForEach-Object Source)
$listeners = @(Get-NetTCPConnection -LocalPort 25565 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess)

[ordered]@{
    paths = @($paths | ForEach-Object {
        [ordered]@{ path = $_; exists = Test-Path -LiteralPath $_ }
    })
    winget = $winget.Source
    java_commands = $javaCommands
    port_25565 = $listeners
    free_c_gb = [math]::Round((Get-Volume -DriveLetter C).SizeRemaining / 1GB, 2)
    free_d_gb = [math]::Round((Get-Volume -DriveLetter D).SizeRemaining / 1GB, 2)
} | ConvertTo-Json -Depth 5
