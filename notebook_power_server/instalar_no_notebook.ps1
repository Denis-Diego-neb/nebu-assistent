param(
    [string]$PowerToken = $env:NEBULA_POWER_TOKEN
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($PowerToken) -or $PowerToken.Length -lt 24) {
    throw "Defina NEBULA_POWER_TOKEN ou informe -PowerToken com pelo menos 24 caracteres."
}
$log = Join-Path $PSScriptRoot "resultado-instalacao.txt"
"Instalação iniciada em $(Get-Date -Format s)" | Set-Content -LiteralPath $log
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Este instalador precisa ser executado como administrador. Abra INSTALAR-COMO-ADMINISTRADOR.cmd e confirme o UAC."
}
$source = Join-Path $PSScriptRoot "NebulaPowerServer.exe"
$launcherSource = Join-Path $PSScriptRoot "iniciar_servicos_notebook.ps1"
$targetDir = Join-Path $env:LOCALAPPDATA "NebulaPower"
$target = Join-Path $targetDir "NebulaPowerServer.exe"
$launcherTarget = Join-Path $targetDir "iniciar_servicos_notebook.ps1"
$assistantSource = Join-Path $PSScriptRoot "NebulaNotebook.exe"
$assistantTarget = Join-Path $targetDir "NebulaNotebook.exe"
$lampConfigSource = Join-Path $PSScriptRoot "abajur_tuya.json"
$lampConfigDir = Join-Path $env:LOCALAPPDATA "Nebula"
$lampConfigTarget = Join-Path $lampConfigDir "abajur_tuya.json"
$airConfigSource = Join-Path $PSScriptRoot "ar_ir.json"
$airConfigTarget = Join-Path $lampConfigDir "ar_ir.json"

if (-not (Test-Path -LiteralPath $source) -or -not (Test-Path -LiteralPath $launcherSource)) {
    throw "Os arquivos do Nebula Power não foram encontrados ao lado deste instalador."
}

# Encerre a versão instalada antes de substituir o executável. No Windows, um
# processo em execução mantém o próprio arquivo bloqueado para gravação.
Get-Process NebulaPowerServer -ErrorAction SilentlyContinue | Stop-Process -Force
$deadline = (Get-Date).AddSeconds(5)
while ((Get-Process NebulaPowerServer -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 150
}
if (Get-Process NebulaPowerServer -ErrorAction SilentlyContinue) {
    throw "Não consegui encerrar a versão anterior do Nebula Power Server."
}

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Copy-Item -LiteralPath $source -Destination $target -Force
Copy-Item -LiteralPath $launcherSource -Destination $launcherTarget -Force
if (Test-Path -LiteralPath $assistantSource) {
    Get-Process NebulaNotebook -ErrorAction SilentlyContinue | Stop-Process -Force
    $assistantDeadline = (Get-Date).AddSeconds(8)
    while ((Get-Process NebulaNotebook -ErrorAction SilentlyContinue) -and
        (Get-Date) -lt $assistantDeadline) {
        Start-Sleep -Milliseconds 150
    }
    if (Get-Process NebulaNotebook -ErrorAction SilentlyContinue) {
        throw "Não consegui encerrar a versão anterior da Nebula do notebook."
    }
    Copy-Item -LiteralPath $assistantSource -Destination $assistantTarget -Force
}
if (Test-Path -LiteralPath $lampConfigSource) {
    New-Item -ItemType Directory -Path $lampConfigDir -Force | Out-Null
    Copy-Item -LiteralPath $lampConfigSource -Destination $lampConfigTarget -Force
}
if (Test-Path -LiteralPath $airConfigSource) {
    New-Item -ItemType Directory -Path $lampConfigDir -Force | Out-Null
    Copy-Item -LiteralPath $airConfigSource -Destination $airConfigTarget -Force
}

[Environment]::SetEnvironmentVariable("NEBULA_QWEN_ENABLED", "0", "User")
[Environment]::SetEnvironmentVariable("NEBULA_POWER_TOKEN", $PowerToken, "User")
$allowedNetworks = @("LocalSubnet", "100.64.0.0/10")

Get-NetFirewallRule -DisplayName "Nebula Power Server" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "Nebula Power Server" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 8766 `
    -RemoteAddress $allowedNetworks | Out-Null
Get-NetFirewallRule -DisplayName "Nebula Ollama Server" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Remove-ItemProperty -Path $run -Name "NebulaPowerServer" -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $run -Name "NebulaNotebookServices" -ErrorAction SilentlyContinue
$taskName = "Nebula Notebook Services"
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcherTarget + '"'
)
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser `
    -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $taskAction `
    -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings `
    -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
$startupDeadline = (Get-Date).AddSeconds(20)
$serverReady = $false
while ((Get-Date) -lt $startupDeadline) {
    if (Get-Process NebulaPowerServer -ErrorAction SilentlyContinue) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:8766/health" `
                -Headers @{"X-Nebula-Power-Token" = $PowerToken} `
                -UseBasicParsing -TimeoutSec 2 | Out-Null
            $serverReady = $true
            break
        } catch {
            # O executável one-file ainda pode estar extraindo os componentes.
        }
    }
    Start-Sleep -Milliseconds 400
}
if (-not $serverReady) {
    throw "O servidor foi copiado, mas não permaneceu em execução."
}
"SUCESSO: Nebula Power instalado e iniciado." | Add-Content -LiteralPath $log
Write-Host "Serviços Nebula instalados. O notebook iniciará o Wake-on-LAN; a Qwen ficará desativada."
