$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$msbuild = "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
$output = Join-Path $PSScriptRoot "dist"
$agentWork = Join-Path $PSScriptRoot "agent_build"

if (-not (Test-Path -LiteralPath $msbuild)) {
    throw "MSBuild com as ferramentas C++ não foi encontrado."
}
New-Item -ItemType Directory -Path $output -Force | Out-Null

& $msbuild (Join-Path $PSScriptRoot "SampleV2CredentialProvider.vcxproj") `
    /t:Rebuild /p:Configuration=Release /p:Platform=x64 /m
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar o Credential Provider." }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "x64\Release\NebulaCredentialProvider.dll") `
    -Destination (Join-Path $output "NebulaCredentialProvider.dll") -Force

& $pyinstaller --noconfirm --clean --onefile --noconsole `
    --name NebulaUnlockAgent `
    --distpath $output --workpath $agentWork --specpath $agentWork `
    (Join-Path $projectRoot "windows_unlock_agent.py")
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar o agente de pré-login." }

& $python -m unittest (Join-Path $projectRoot "test_windows_unlock_agent.py")
if ($LASTEXITCODE -ne 0) { throw "Os testes do agente de desbloqueio falharam." }
Write-Host "Credential Provider e agente de pré-login compilados em $output."
