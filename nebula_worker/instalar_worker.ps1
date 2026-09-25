# Instala o worker MCP no notebook. Executar como administrador (INSTALAR-WORKER.cmd).
param(
    [string]$Token = $env:NEBULA_WORKER_TOKEN
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Token) -or $Token.Length -lt 32) {
    throw "Defina NEBULA_WORKER_TOKEN ou informe -Token com pelo menos 32 caracteres (o mesmo valor do PC)."
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute como administrador: abra INSTALAR-WORKER.cmd e confirme o UAC."
}

$source = Join-Path $PSScriptRoot "NebulaWorker.exe"
$configSource = Join-Path $PSScriptRoot "worker.json"
$launcherSource = Join-Path $PSScriptRoot "iniciar_worker.ps1"
foreach ($required in @($source, $configSource, $launcherSource)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Arquivo ausente ao lado do instalador: $required"
    }
}
$config = Get-Content -LiteralPath $configSource -Raw -Encoding UTF8 | ConvertFrom-Json
$port = if ($config.port) { [int]$config.port } else { 8790 }

$targetDir = Join-Path $env:LOCALAPPDATA "NebulaWorker"
$target = Join-Path $targetDir "NebulaWorker.exe"
$configTarget = Join-Path $targetDir "worker.json"
$launcherTarget = Join-Path $targetDir "iniciar_worker.ps1"

# O lancador em laco reabriria o worker durante a copia; pare os dois antes.
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -like "*iniciar_worker.ps1*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process NebulaWorker -ErrorAction SilentlyContinue | Stop-Process -Force
$deadline = (Get-Date).AddSeconds(8)
while ((Get-Process NebulaWorker -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
if (Get-Process NebulaWorker -ErrorAction SilentlyContinue) {
    throw "Nao consegui encerrar a versao anterior do worker."
}

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Copy-Item -LiteralPath $source -Destination $target -Force
Copy-Item -LiteralPath $configSource -Destination $configTarget -Force
Copy-Item -LiteralPath $launcherSource -Destination $launcherTarget -Force

[Environment]::SetEnvironmentVariable("NEBULA_WORKER_TOKEN", $Token, "User")
$env:NEBULA_WORKER_TOKEN = $Token

# Valida configuracao e Ollama local antes de abrir porta ou registrar tarefa.
& $target --config $configTarget --check
if ($LASTEXITCODE -eq 2) { throw "worker.json invalido; corrija e rode o instalador de novo." }
if ($LASTEXITCODE -ne 0) {
    Write-Warning "O Ollama local nao respondeu agora. O worker sobe assim mesmo e passa a atender quando ele voltar."
}

# Firewall: so a porta do worker e so para os clientes do worker.json.
$remote = @($config.allowed_clients | Where-Object { $_ -notmatch '^(127\.|::1)' })
Get-NetFirewallRule -DisplayName "Nebula MCP Worker" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue
if ($remote.Count -gt 0) {
    New-NetFirewallRule -DisplayName "Nebula MCP Worker" -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $port -RemoteAddress $remote | Out-Null
}

$taskName = "Nebula MCP Worker"
$taskUser = $identity.Name
$taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcherTarget + '"'
)
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger `
    -Principal $taskPrincipal -Settings $taskSettings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

$deadline = (Get-Date).AddSeconds(25)
$listening = $false
while ((Get-Date) -lt $deadline) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        $listening = $true
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $listening) {
    throw "O worker nao abriu a porta $port. Veja $targetDir\runtime\logs\worker.log."
}
Write-Host "Worker MCP instalado e escutando em $($config.bind_host):$port."
Write-Host "No PC, rode: .venv\Scripts\python.exe -m scripts.notebook_worker_demo"
