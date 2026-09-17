param(
    [switch]$InstallAndroid,
    [switch]$StartDesktop
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$versionText = Get-Content -LiteralPath (Join-Path $projectRoot 'versao.py') -Raw
$versionMatch = [regex]::Match($versionText, 'VERSAO_NEBULA\s*=\s*["'']([0-9]+\.[0-9]+\.[0-9]+)["'']')
if (-not $versionMatch.Success) {
    throw 'VERSAO_NEBULA não foi encontrada em versao.py.'
}
$releaseVersion = $versionMatch.Groups[1].Value
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pyinstallerExe = Join-Path $projectRoot '.venv\Scripts\pyinstaller.exe'
$desktopDist = Join-Path $projectRoot "dist_nebu_$($releaseVersion.Replace('.', '_'))"
$desktopWork = Join-Path $projectRoot "build_nebu_$($releaseVersion.Replace('.', '_'))"
$desktopOutput = Join-Path $projectRoot "Nebula-$releaseVersion.exe"
$androidOutput = Join-Path $projectRoot "Nebula-$releaseVersion.apk"

& $pythonExe -m unittest discover -p 'test*.py'
if ($LASTEXITCODE -ne 0) { throw 'Os testes da Nebula falharam.' }

& $pyinstallerExe --noconfirm --clean --distpath $desktopDist --workpath $desktopWork (Join-Path $projectRoot 'Nebula.spec')
if ($LASTEXITCODE -ne 0) { throw 'A compilação do desktop falhou.' }
$desktopWasRunning = $false
$runningDesktop = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $desktopOutput
}
if ($runningDesktop) {
    $desktopWasRunning = $true
    foreach ($desktopProcess in $runningDesktop) {
        Stop-Process -Id $desktopProcess.ProcessId -Force
    }
    Start-Sleep -Milliseconds 500
}
Copy-Item -LiteralPath (Join-Path $desktopDist 'Nebula.exe') -Destination $desktopOutput -Force
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if (-not (Test-Path -LiteralPath $runKey)) {
    New-Item -Path $runKey -Force | Out-Null
}
$pcAgent = Join-Path $projectRoot 'pc_start_agent.py'
$pythonwExe = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
Set-ItemProperty -LiteralPath $runKey -Name 'Nebula' -Value (
    '"{0}" "{1}"' -f $pythonwExe, $pcAgent
)

Push-Location (Join-Path $projectRoot 'android')
try {
    & .\gradlew.bat assembleDebug
    if ($LASTEXITCODE -ne 0) { throw 'A compilação do Android falhou.' }
} finally {
    Pop-Location
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'android\app\build\outputs\apk\debug\app-debug.apk') -Destination $androidOutput -Force

& (Join-Path $projectRoot 'native\nebula_credential_provider\build.ps1')
if ($LASTEXITCODE -ne 0) { throw 'A compilacao do Credential Provider falhou.' }

& (Join-Path $projectRoot 'notebook_power_server\build.ps1')
if ($LASTEXITCODE -ne 0) { throw 'A compilacao do hub do notebook falhou.' }
& (Join-Path $projectRoot 'deploy_notebook.ps1')
if ($LASTEXITCODE -eq 3) {
    Write-Warning 'O hub novo foi gerado, mas ainda precisa do bootstrap 1.21.0 no notebook.'
} elseif ($LASTEXITCODE -ne 0) {
    throw 'A atualizacao automatica do notebook falhou.'
}

$notebookPackageDir = Join-Path $projectRoot ".package-notebook-$releaseVersion"
New-Item -ItemType Directory -Path $notebookPackageDir -Force | Out-Null
foreach ($packageFile in @(
    'NebulaPowerServer.exe', 'NebulaNotebook.exe',
    'iniciar_servicos_notebook.ps1', 'instalar_no_notebook.ps1',
    'INSTALAR-COMO-ADMINISTRADOR.cmd', 'LEIA-ME-INSTALACAO.txt'
)) {
    $source = Join-Path $projectRoot "notebook_power_server\$packageFile"
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $notebookPackageDir -Force
    }
}
$airConfig = Join-Path $projectRoot 'ar_ir.json'
if (Test-Path -LiteralPath $airConfig) {
    Copy-Item -LiteralPath $airConfig -Destination $notebookPackageDir -Force
}
Compress-Archive -Path (Join-Path $notebookPackageDir '*') `
    -DestinationPath (Join-Path $projectRoot "Nebula-Notebook-$releaseVersion.zip") -Force

$credentialSource = Join-Path $projectRoot 'native\nebula_credential_provider'
$credentialPackageDir = Join-Path $projectRoot ".package-credential-$releaseVersion"
New-Item -ItemType Directory -Path $credentialPackageDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $credentialSource 'dist\NebulaCredentialProvider.dll'),(
    Join-Path $credentialSource 'dist\NebulaUnlockAgent.exe'
) -Destination $credentialPackageDir -Force
Copy-Item -LiteralPath (Join-Path $credentialSource 'instalar.ps1'),(
    Join-Path $credentialSource 'desinstalar.ps1'
),(Join-Path $credentialSource 'README.md'),(
    Join-Path $credentialSource 'MICROSOFT-SAMPLE-LICENSE.txt'
),(Join-Path $credentialSource 'INSTALAR-COMO-ADMINISTRADOR.cmd'
) -Destination $credentialPackageDir -Force
Compress-Archive -Path (Join-Path $credentialPackageDir '*') `
    -DestinationPath (Join-Path $projectRoot "Nebula-CredentialProvider-$releaseVersion.zip") -Force

if ($InstallAndroid) {
    $adbExe = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
    & $adbExe install -r $androidOutput
    if ($LASTEXITCODE -ne 0) { throw 'A instalação do APK falhou.' }
}

if ($StartDesktop) {
    $previousDesktop = Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and
        (Split-Path -Parent $_.ExecutablePath) -eq $projectRoot -and
        (Split-Path -Leaf $_.ExecutablePath) -match '^Nebula-\d+\.\d+\.\d+\.exe$' -and
        $_.ExecutablePath -ne $desktopOutput
    }
    foreach ($desktopProcess in $previousDesktop) {
        Stop-Process -Id $desktopProcess.ProcessId -Force
    }
}

if ($StartDesktop -or $desktopWasRunning) {
    Start-Process -FilePath $desktopOutput -WorkingDirectory $projectRoot -WindowStyle Hidden
}

Write-Host "Nebula $releaseVersion gerada para desktop e Android."
