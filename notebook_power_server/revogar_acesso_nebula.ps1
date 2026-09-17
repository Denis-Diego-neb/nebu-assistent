$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "A revogacao do acesso exige uma sessao administrativa."
}

$publicKeyFile = Join-Path $PSScriptRoot "nebula_notebook_admin.pub"
$authorizedKeys = Join-Path $env:ProgramData "ssh\administrators_authorized_keys"
if ((Test-Path -LiteralPath $publicKeyFile) -and
    (Test-Path -LiteralPath $authorizedKeys)) {
    $publicKey = (Get-Content -LiteralPath $publicKeyFile -Raw).Trim()
    $remaining = @(Get-Content -LiteralPath $authorizedKeys) |
        Where-Object { $_.Trim() -ne $publicKey }
    $remaining | Set-Content -LiteralPath $authorizedKeys -Encoding ascii
    & icacls.exe $authorizedKeys /inheritance:r `
        /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
}
Restart-Service -Name sshd -ErrorAction SilentlyContinue
Write-Host "Acesso administrativo desta chave Nebula revogado."
