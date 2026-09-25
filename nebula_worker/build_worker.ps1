# Executar no PC principal, na raiz do projeto ou de qualquer pasta.
# Roda os testes do worker e gera nebula_worker\NebulaWorker.exe (one-file).
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
$dist = Join-Path $PSScriptRoot "dist_build"
$work = Join-Path $PSScriptRoot "work_build"

Push-Location $projectRoot
try {
    & $python -m unittest tests.test_worker_protocol tests.test_worker_tickets `
        tests.test_worker_dispatcher tests.test_worker_ollama tests.test_worker_config `
        tests.test_worker_gateway
    if ($LASTEXITCODE -ne 0) { throw "Os testes do worker falharam; nada foi compilado." }

    # Executavel de console de proposito: --check e --version escrevem no
    # terminal. No notebook ele roda oculto pelo iniciar_worker.ps1.
    # Nada de --collect-all mcp: ele importa mcp.cli, que encerra o processo
    # quando o typer nao esta instalado e derruba a compilacao.
    & $pyinstaller --noconfirm --clean --onefile --console `
        --name NebulaWorker `
        --noupx `
        --paths $projectRoot `
        --collect-submodules nebula_worker `
        --collect-submodules uvicorn `
        --collect-submodules mcp.server `
        --collect-submodules mcp.shared `
        --collect-submodules mcp_types `
        --collect-submodules sse_starlette `
        --copy-metadata mcp `
        --distpath $dist `
        --workpath $work `
        --specpath $work `
        (Join-Path $PSScriptRoot "__main__.py")
    if ($LASTEXITCODE -ne 0) { throw "A compilacao do worker falhou." }
} finally {
    Pop-Location
}

$destination = Join-Path $PSScriptRoot "NebulaWorker.exe"
Copy-Item -LiteralPath (Join-Path $dist "NebulaWorker.exe") -Destination $destination -Force
& $destination --version
if ($LASTEXITCODE -ne 0) { throw "O executavel gerado nao iniciou." }
Write-Host ""
Write-Host "Pronto: $destination"
Write-Host "Leve para o notebook, numa mesma pasta: NebulaWorker.exe, worker.json,"
Write-Host "instalar_worker.ps1, iniciar_worker.ps1 e INSTALAR-WORKER.cmd."
