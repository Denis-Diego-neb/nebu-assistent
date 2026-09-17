[CmdletBinding()]
param(
    [switch] $Deploy
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$sdkRoot = Join-Path $env:APPDATA 'bakkesmod\bakkesmod\bakkesmodsdk'
$sourceFile = Join-Path $projectDirectory 'NebulaBoost.cpp'
$buildDirectory = Join-Path $projectDirectory 'build'
$outputFile = Join-Path $buildDirectory 'NebulaBoost.dll'
$objectFile = Join-Path $buildDirectory 'NebulaBoost.obj'
$sdkLibrary = Join-Path $sdkRoot 'lib\pluginsdk.lib'

if (-not (Test-Path -LiteralPath (Join-Path $sdkRoot 'include\bakkesmod\plugin\bakkesmodplugin.h'))) {
    throw "BakkesMod SDK não encontrado em: $sdkRoot"
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw 'Instale o Visual Studio Build Tools com a carga de trabalho C++ para compilar o plugin.'
}
$visualStudioPath = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -Last 1)
if ([string]::IsNullOrWhiteSpace($visualStudioPath)) {
    throw 'Nenhuma instalação do Visual Studio com compilador C++ foi encontrada.'
}
$visualStudioPath = $visualStudioPath.Trim()
$developerShellModule = Join-Path $visualStudioPath 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll'
Import-Module $developerShellModule
Enter-VsDevShell -VsInstallPath $visualStudioPath -SkipAutomaticLocation -Arch amd64 -HostArch amd64 | Out-Null

New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
& cl.exe /nologo /c /std:c++20 /O2 /EHsc /MD /W4 "/I$(Join-Path $sdkRoot 'include')" "/Fo$objectFile" $sourceFile
if ($LASTEXITCODE -ne 0) {
    throw "A compilação do NebulaBoost falhou com o código $LASTEXITCODE."
}
& link.exe /NOLOGO /DLL /MACHINE:X64 /INCREMENTAL:NO /OPT:REF /OPT:ICF "/OUT:$outputFile" $objectFile $sdkLibrary Ws2_32.lib
if ($LASTEXITCODE -ne 0) {
    throw "A linkedição do NebulaBoost falhou com o código $LASTEXITCODE."
}

$image = [System.IO.File]::ReadAllBytes($outputFile)
$peOffset = [BitConverter]::ToInt32($image, 0x3C)
$machine = [BitConverter]::ToUInt16($image, $peOffset + 4)
if ($machine -ne 0x8664) {
    throw ('O plugin compilado não é PE64 x64 (machine=0x{0:X4}).' -f $machine)
}
Write-Host "Plugin compilado: $outputFile"
Write-Host "SHA256: $((Get-FileHash -LiteralPath $outputFile -Algorithm SHA256).Hash)"

if ($Deploy) {
    $bakkesRoot = Join-Path $env:APPDATA 'bakkesmod\bakkesmod'
    $pluginDirectory = Join-Path $bakkesRoot 'plugins'
    $pluginConfig = Join-Path $bakkesRoot 'cfg\plugins.cfg'
    if (-not (Test-Path -LiteralPath $pluginDirectory -PathType Container)) {
        throw "Pasta de plugins do BakkesMod não encontrada: $pluginDirectory"
    }
    if (Get-Process RocketLeague -ErrorAction SilentlyContinue) {
        throw 'Feche o Rocket League antes de atualizar o NebulaBoost.dll.'
    }
    $deployFile = Join-Path $pluginDirectory 'NebulaBoost.dll'
    Copy-Item -LiteralPath $outputFile -Destination $deployFile -Force
    $loadCommand = 'plugin load nebulaboost'
    $existingConfig = if (Test-Path -LiteralPath $pluginConfig) {
        Get-Content -LiteralPath $pluginConfig -Raw
    } else {
        ''
    }
    if ($existingConfig -notmatch '(?im)^\s*plugin\s+load\s+nebulaboost\s*$') {
        Add-Content -LiteralPath $pluginConfig -Value $loadCommand -Encoding utf8
    }
    Write-Host "Plugin instalado: $deployFile"
}
