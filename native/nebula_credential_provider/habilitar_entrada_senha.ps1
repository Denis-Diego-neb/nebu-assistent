$ErrorActionPreference = 'Stop'
$resultFile = Join-Path $PSScriptRoot 'resultado-entrada-senha.txt'
try {
    $key = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device'
    $name = 'DevicePasswordLessBuildVersion'
    $previous = (Get-ItemProperty -LiteralPath $key -Name $name).$name
    $backupFile = Join-Path $PSScriptRoot 'entrada-senha-anterior.json'
    if (-not (Test-Path -LiteralPath $backupFile)) {
        @{Path=$key; Name=$name; Value=$previous} | ConvertTo-Json |
            Set-Content -LiteralPath $backupFile -Encoding UTF8
    }
    Set-ItemProperty -LiteralPath $key -Name $name -Value 0
    if ((Get-ItemProperty -LiteralPath $key -Name $name).$name -ne 0) {
        throw 'O Windows não confirmou a alteração.'
    }
    'OK: entrada por senha habilitada junto com o PIN existente. Nenhuma credencial foi alterada.' |
        Set-Content -LiteralPath $resultFile -Encoding UTF8
} catch {
    ('ERRO: ' + $_.Exception.Message) | Set-Content -LiteralPath $resultFile -Encoding UTF8
    exit 1
}
