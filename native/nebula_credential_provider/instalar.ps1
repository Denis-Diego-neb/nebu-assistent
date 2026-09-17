# Requer PowerShell elevado. Mantém os provedores normais do Windows habilitados.
$ErrorActionPreference = "Stop"
$installationLog = Join-Path $PSScriptRoot "resultado-instalacao.txt"
trap {
    $message = "ERRO: $($_.Exception.Message)"
    $message | Set-Content -LiteralPath $installationLog -Encoding UTF8
    Write-Host ""
    Write-Host $message -ForegroundColor Red
    Read-Host "Pressione Enter para fechar"
    exit 1
}

$providerId = "{B5C61DE8-44CD-4BF6-90D9-283726850FF2}"
$sourceDir = Join-Path $PSScriptRoot "dist"
$providerSource = Join-Path $sourceDir "NebulaCredentialProvider.dll"
$agentSource = Join-Path $sourceDir "NebulaUnlockAgent.exe"
# No pacote distribuído, os binários ficam ao lado do instalador. Durante o
# desenvolvimento, eles continuam na pasta dist.
if (-not (Test-Path -LiteralPath $providerSource) -or
    -not (Test-Path -LiteralPath $agentSource)) {
    $sourceDir = $PSScriptRoot
    $providerSource = Join-Path $sourceDir "NebulaCredentialProvider.dll"
    $agentSource = Join-Path $sourceDir "NebulaUnlockAgent.exe"
}
$installDir = Join-Path $env:ProgramFiles "Nebula"
$providerTarget = Join-Path $installDir "NebulaCredentialProvider.dll"
$agentTarget = Join-Path $installDir "NebulaUnlockAgent.exe"
$dataDir = Join-Path $env:ProgramData "Nebula"
$phonePublicKey = Join-Path $PSScriptRoot "phone_public.der"
if (-not (Test-Path -LiteralPath $phonePublicKey)) {
    throw "Pareie o A71 por USB antes de instalar: chave pública do telefone ausente."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Abra este instalador com Executar como administrador."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "O Credential Provider da Nebula requer Windows de 64 bits."
}
if (-not (Test-Path -LiteralPath $providerSource) -or
    -not (Test-Path -LiteralPath $agentSource)) {
    throw "Os binários NebulaCredentialProvider.dll e NebulaUnlockAgent.exe não foram encontrados ao lado do instalador."
}

$localAccount = Get-LocalUser -SID $identity.User -ErrorAction SilentlyContinue
function Normalize-NebulaMicrosoftEmail([string]$value) {
    $normalized = $value.Trim().Replace('\@', '@')
    if ($normalized -notmatch '^[^@\s\\]+@[^@\s\\]+\.[^@\s\\]+$') { return $null }
    return $normalized
}
$credentialUser = $identity.Name
if ($localAccount -and [string]$localAccount.PrincipalSource -eq "MicrosoftAccount") {
    Write-Host "Conta Microsoft detectada para o usuário $($localAccount.Name)."
    # Esta lista sugere o e-mail; a validação posterior pelo SID confirma o usuário.
    $emailCandidates = @(Get-ChildItem 'HKCU:\Software\Microsoft\IdentityCRL\UserExtendedProperties' -ErrorAction SilentlyContinue |
        ForEach-Object { Normalize-NebulaMicrosoftEmail $_.PSChildName } | Where-Object { $_ })
    $suggestedEmail = if ($emailCandidates.Count -eq 1) { $emailCandidates[0] } else { '' }
    do {
        $emailPrompt = if ($suggestedEmail) { "E-mail da conta [$suggestedEmail] - Enter para usar" } else { 'Digite o e-mail usado para entrar no Windows' }
        $enteredEmail = (Read-Host $emailPrompt).Trim()
        if (-not $enteredEmail) { $enteredEmail = $suggestedEmail }
        $microsoftEmail = Normalize-NebulaMicrosoftEmail $enteredEmail
        if (-not $microsoftEmail) { Write-Host 'E-mail inválido. Use nome@dominio.com, sem barras.' }
    } while (-not $microsoftEmail)
    Write-Host "Conta para validação: $microsoftEmail"
    $credentialUser = "MicrosoftAccount\$microsoftEmail"
}

Write-Host "Informe a SENHA da conta do Windows (não o PIN do Windows)."
$credential = Get-Credential -UserName $credentialUser `
    -Message "A senha ficará criptografada por este PC e nunca será enviada ao telefone."
if (-not $credential) { throw "Instalação cancelada." }

# O Windows PowerShell 5.1 não carrega System.Security automaticamente em
# todas as instalações do Windows 10. ProtectedData (DPAPI) fica nesse assembly.
Add-Type -AssemblyName System.Security
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class NebulaLogonCheck {
  [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  static extern bool LogonUser(string user, string domain, string password,
    int logonType, int provider, out IntPtr token);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
  public static int Verify(string qualified, string password, string expectedSid) {
    string domain = ".", user = qualified;
    int slash = qualified.IndexOf('\\');
    if (slash >= 0) { domain = qualified.Substring(0, slash); user = qualified.Substring(slash + 1); }
    IntPtr token;
    bool ok = LogonUser(user, domain, password, 2, 0, out token);
    if (!ok) return Marshal.GetLastWin32Error();
    try {
      using (var identity = new System.Security.Principal.WindowsIdentity(token)) {
        return identity.User.Value == expectedSid ? 0 : 1332;
      }
    } finally { CloseHandle(token); }
  }
}
'@

$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $logonError = [NebulaLogonCheck]::Verify($credential.UserName.Trim(), $plainPassword, $identity.User.Value)
    if ($logonError -ne 0) {
        $logonDescription = [ComponentModel.Win32Exception]::new($logonError).Message
        $hint = switch ($logonError) {
            1326 { 'O Windows não validou esta combinação de conta e senha localmente. Isso também pode ocorrer se a senha da conta Microsoft ainda não foi validada na entrada deste PC. Teste entrar no Windows por Senha, com internet, em vez do PIN, antes de repetir o instalador.' }
            1332 { 'A credencial validada pertence a outra conta, não à sessão atual. Use a conta deste usuário do Windows.' }
            1385 { 'Uma política do Windows impede o logon interativo desta conta.' }
            1909 { 'A conta está temporariamente bloqueada. Não repita tentativas agora.' }
            1314 { 'Falta um privilégio exigido pelo Windows para validar esta conta. A senha não foi classificada como incorreta.' }
            default { 'A instalação foi interrompida antes de salvar a credencial.' }
        }
        throw "Windows retornou erro $logonError : $logonDescription. $hint Nada foi instalado."
    }
    $passwordBytes = [Text.Encoding]::Unicode.GetBytes($plainPassword)
    $protectedBytes = [Security.Cryptography.ProtectedData]::Protect(
        $passwordBytes, $null,
        [Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    [Array]::Clear($passwordBytes, 0, $passwordBytes.Length)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $plainPassword = $null
}

New-Item -ItemType Directory -Path $installDir,$dataDir -Force | Out-Null
# Proteja o diretório ANTES de gravar a credencial DPAPI da máquina.
& icacls.exe $dataDir /inheritance:r /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Não foi possível proteger as credenciais da Nebula." }
Copy-Item -LiteralPath $phonePublicKey -Destination (Join-Path $dataDir "phone_public.der") -Force
$targetMachine = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid
[IO.File]::WriteAllText((Join-Path $dataDir "unlock_target.txt"), $targetMachine, [Text.Encoding]::ASCII)
# Nenhum ticket de instalação anterior deve conceder login.
Remove-Item -LiteralPath (Join-Path $dataDir "unlock.authorized") -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $providerSource -Destination $providerTarget -Force
Copy-Item -LiteralPath $agentSource -Destination $agentTarget -Force
[IO.File]::WriteAllBytes((Join-Path $dataDir "windows_password.bin"), $protectedBytes)
[IO.File]::WriteAllText(
    (Join-Path $dataDir "target_sid.txt"), $identity.User.Value,
    [Text.UTF8Encoding]::new($false)
)
[Array]::Clear($protectedBytes, 0, $protectedBytes.Length)

& icacls.exe $dataDir /inheritance:r /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null

$cpKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\$providerId"
$classKey = "Registry::HKEY_CLASSES_ROOT\CLSID\$providerId"
$serverKey = Join-Path $classKey "InprocServer32"
New-Item -Path $cpKey,$classKey,$serverKey -Force | Out-Null
Set-Item -LiteralPath $cpKey -Value "Nebula - confirmacao pelo telefone"
Set-Item -LiteralPath $classKey -Value "Nebula Credential Provider"
Set-Item -LiteralPath $serverKey -Value $providerTarget
New-ItemProperty -LiteralPath $serverKey -Name "ThreadingModel" `
    -PropertyType String -Value "Apartment" -Force | Out-Null

$action = New-ScheduledTaskAction -Execute $agentTarget
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Nebula Unlock Agent" -Action $action `
    -Trigger $trigger -Settings $settings -User "SYSTEM" `
    -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName "Nebula Unlock Agent"

Write-Host "Credential Provider instalado. Reinicie o PC para testar."
Write-Host "Os métodos PIN e Senha do Windows continuam disponíveis para recuperação."
"SUCESSO: Credential Provider instalado para $($identity.User.Value)." |
    Set-Content -LiteralPath $installationLog -Encoding UTF8
