# Lancador do worker no notebook, chamado pela tarefa "Nebula MCP Worker" no logon.
# Fica em laco: se o worker cair, e reaberto em ate 30 segundos.
$ErrorActionPreference = "SilentlyContinue"
$exe = Join-Path $PSScriptRoot "NebulaWorker.exe"
$config = Join-Path $PSScriptRoot "worker.json"

while ($true) {
    if ((Test-Path -LiteralPath $exe) -and -not (Get-Process NebulaWorker -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $exe -ArgumentList @("--config", "`"$config`"") `
            -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    }
    Start-Sleep -Seconds 30
}
