$ErrorActionPreference = "SilentlyContinue"
$PSScriptRoot | Set-Location

$powerServer = Join-Path $PSScriptRoot "NebulaPowerServer.exe"
if ((Test-Path -LiteralPath $powerServer) -and -not (Get-Process NebulaPowerServer -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $powerServer -WorkingDirectory $PSScriptRoot -WindowStyle Normal
}

$qwenEnabled = $env:NEBULA_QWEN_ENABLED -in @("1", "true", "sim", "yes", "on")
if (-not $qwenEnabled) {
    exit 0
}

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" `
        -UseBasicParsing -TimeoutSec 2 | Out-Null
    exit 0
} catch {
    # O Ollama ainda não está servindo; tente iniciá-lo sem abrir uma janela.
}

$ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ollama) {
    $ollamaPath = $ollama.Source
} else {
    $ollamaPath = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
}

if (Test-Path -LiteralPath $ollamaPath) {
    # A API do Ollama nao tem senha. Ele so escuta a rede quando o firewall
    # restringe a porta ao PC (proteger_ollama.ps1); sem isso, fica no notebook.
    $protegido = Get-NetFirewallRule -DisplayName "Nebula Ollama - bloquear outros aparelhos" `
        -ErrorAction SilentlyContinue | Where-Object { $_.Enabled -eq "True" }
    $env:OLLAMA_HOST = if ($protegido) { "0.0.0.0:11434" } else { "127.0.0.1:11434" }
    Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden
}
