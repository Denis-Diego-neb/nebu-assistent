# Nebula Credential Provider

Este componente adiciona à tela de entrada do Windows uma opção **Nebula**. O
telefone confirma a digital ou o PIN do Android e assina uma autorização com
uma chave EC P-256 do Android Keystore. No A71/Android 13, a chave exige
autenticação biométrica forte ou credencial do dispositivo nos últimos 5
segundos. O PIN nunca sai do telefone.
O hub apenas encaminha a assinatura: o agente `SYSTEM` confere a chave pública
pareada por USB, a identidade do PC e a validade de 180 segundos. Pedidos
genéricos de Wake-on-LAN não autorizam login. O agente persiste os identificadores
consumidos antes de emitir o ticket; reenvios e reinícios não renovam uma assinatura.
O ticket local é consumido uma única vez e expira em até 120 segundos, limitado
também pela validade original da assinatura.

A senha da conta Windows é solicitada somente pelo instalador local, validada
com `LogonUser` e protegida por DPAPI no escopo da máquina. Ela não entra no APK,
no pacote Wake-on-LAN, no hub ou nos logs. PIN e Senha normais do Windows não são
desativados e continuam sendo a recuperação em caso de falha.

Para preparar os binários, execute `build.ps1`. Depois de instalar uma versão
do app que altere a chave do Android Keystore, pareie novamente a chave pública
`files/unlock-public.der` do app instalado por USB e salve-a como
`phone_public.der` ao lado do instalador. Nunca exporte a chave privada.
Execute `instalar.ps1`, informe a senha real da conta (não o PIN do Windows) e
reinicie. Para remover, execute `desinstalar.ps1` como administrador e reinicie.

Base V2 derivada do exemplo oficial `Windows-classic-samples`, sob a licença MIT
incluída em `MICROSOFT-SAMPLE-LICENSE.txt`.
