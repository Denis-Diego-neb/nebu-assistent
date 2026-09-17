$ErrorActionPreference = "Stop"

$computer = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$java = Get-Command java.exe -ErrorAction SilentlyContinue | Select-Object -First 1
$javaVersion = if ($java) {
    try { (& $java.Source -version 2>&1 | Out-String).Trim() } catch { $null }
} else { $null }
$network = Get-NetIPConfiguration | ForEach-Object {
    [ordered]@{
        interface = $_.InterfaceAlias
        ipv4 = @($_.IPv4Address | ForEach-Object IPAddress)
        gateway = @($_.IPv4DefaultGateway | ForEach-Object NextHop)
    }
}

[ordered]@{
    computer = [ordered]@{
        name = $env:COMPUTERNAME
        manufacturer = $computer.Manufacturer
        model = $computer.Model
        windows = $os.Caption
        build = $os.BuildNumber
    }
    cpu = [ordered]@{
        name = $cpu.Name.Trim()
        cores = $cpu.NumberOfCores
        logical_processors = $cpu.NumberOfLogicalProcessors
    }
    memory = [ordered]@{
        total_gb = [math]::Round($computer.TotalPhysicalMemory / 1GB, 2)
        available_gb = [math]::Round($os.FreePhysicalMemory * 1KB / 1GB, 2)
        virtual_total_gb = [math]::Round($os.TotalVirtualMemorySize * 1KB / 1GB, 2)
        virtual_available_gb = [math]::Round($os.FreeVirtualMemory * 1KB / 1GB, 2)
    }
    pagefiles = @(Get-CimInstance Win32_PageFileUsage | ForEach-Object {
        [ordered]@{ path = $_.Name; allocated_mb = $_.AllocatedBaseSize; current_mb = $_.CurrentUsage; peak_mb = $_.PeakUsage }
    })
    logical_disks = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
        [ordered]@{
            drive = $_.DeviceID
            label = $_.VolumeName
            total_gb = [math]::Round($_.Size / 1GB, 1)
            free_gb = [math]::Round($_.FreeSpace / 1GB, 1)
        }
    })
    physical_disks = @(Get-PhysicalDisk -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{
            name = $_.FriendlyName
            media_type = [string]$_.MediaType
            bus_type = [string]$_.BusType
            total_gb = [math]::Round($_.Size / 1GB, 1)
            health = [string]$_.HealthStatus
        }
    })
    video = @(Get-CimInstance Win32_VideoController | ForEach-Object {
        [ordered]@{ name = $_.Name; adapter_ram_gb = [math]::Round($_.AdapterRAM / 1GB, 1) }
    })
    java = [ordered]@{ path = $java.Source; version = $javaVersion }
    network = @($network)
    ssh = [ordered]@{
        state = (Get-Service sshd).Status.ToString()
        startup = (Get-CimInstance Win32_Service -Filter "Name='sshd'").StartMode
    }
} | ConvertTo-Json -Depth 7
