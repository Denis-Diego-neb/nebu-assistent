$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "A finalização do OpenSSH exige uma sessão administrativa."
}

$config = Join-Path $env:ProgramData "ssh\sshd_config"
$backup = Join-Path $env:ProgramData "ssh\sshd_config.nebula-backup"
$temporary = Join-Path $env:ProgramData "ssh\sshd_config.nebula-new"
$sshd = Join-Path $env:WINDIR "System32\OpenSSH\sshd.exe"
if (-not (Test-Path -LiteralPath $config)) {
    throw "O arquivo sshd_config não foi encontrado."
}
if (-not (Test-Path -LiteralPath $backup)) {
    Copy-Item -LiteralPath $config -Destination $backup
}

$lines = @(Get-Content -LiteralPath $config)
$matchIndex = $lines.Count
for ($index = 0; $index -lt $lines.Count; $index++) {
    if ($lines[$index] -match '^\s*Match\s+') {
        $matchIndex = $index
        break
    }
}
$global = @($lines[0..([Math]::Max(0, $matchIndex - 1))]) |
    Where-Object { $_ -notmatch '^\s*#?\s*(PubkeyAuthentication|PasswordAuthentication|KbdInteractiveAuthentication)\s+' }
$tail = if ($matchIndex -lt $lines.Count) { @($lines[$matchIndex..($lines.Count - 1)]) } else { @() }
$newConfig = @(
    $global
    "PubkeyAuthentication yes"
    "PasswordAuthentication no"
    "KbdInteractiveAuthentication no"
    $tail
)
$newConfig | Set-Content -LiteralPath $temporary -Encoding ascii

& $sshd -t -f $temporary
if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    throw "A configuração sem senha foi recusada pelo OpenSSH; o arquivo atual foi preservado."
}
Move-Item -LiteralPath $temporary -Destination $config -Force
Restart-Service -Name sshd
Write-Output "SUCESSO: autenticação SSH restrita a chave pública."
