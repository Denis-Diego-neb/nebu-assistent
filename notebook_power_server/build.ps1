$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
$dist = Join-Path $PSScriptRoot "dist_build"
$work = Join-Path $PSScriptRoot "work_build"

& $python -m unittest discover -s $projectRoot -p "test_tv_control.py"
if ($LASTEXITCODE -ne 0) { throw "Os testes do hub doméstico falharam." }

& $pyinstaller --noconfirm --clean --onefile --noconsole `
    --name NebulaPowerServer `
    --runtime-tmpdir runtime `
    --noupx `
    --paths $PSScriptRoot `
    --paths $projectRoot `
    --hidden-import tv_control `
    --hidden-import abajur_tuya `
    --hidden-import abajur_wifi `
    --hidden-import tinytuya `
    --hidden-import ar_ir_direto `
    --hidden-import versao `
    --hidden-import front_assets `
    --add-data "$(Join-Path $projectRoot 'nebula_front');nebula_front" `
    --hidden-import youtube_player `
    --hidden-import tkinter.scrolledtext `
    --collect-all yt_dlp `
    --distpath $dist `
    --workpath $work `
    --specpath $work `
    (Join-Path $PSScriptRoot "power_server.py")
if ($LASTEXITCODE -ne 0) { throw "A compilação do hub doméstico falhou." }

$destination = Join-Path $PSScriptRoot "NebulaPowerServer.exe"
$runningDestination = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $destination
}
foreach ($process in $runningDestination) {
    Stop-Process -Id $process.ProcessId -Force
}
if ($runningDestination) { Start-Sleep -Milliseconds 500 }
Copy-Item -LiteralPath (Join-Path $dist "NebulaPowerServer.exe") `
    -Destination $destination -Force
$versionText = Get-Content -LiteralPath (Join-Path $projectRoot "versao.py") -Raw
$versionMatch = [regex]::Match($versionText, 'VERSAO_NEBULA\s*=\s*["'']([0-9]+\.[0-9]+\.[0-9]+)["'']')
if ($versionMatch.Success) {
    $assistantSource = Join-Path $projectRoot "Nebula-$($versionMatch.Groups[1].Value).exe"
    if (Test-Path -LiteralPath $assistantSource) {
        Copy-Item -LiteralPath $assistantSource `
            -Destination (Join-Path $PSScriptRoot "NebulaNotebook.exe") -Force
    }
}
Write-Host "Nebula Home Hub compilado com controle de TVs."
