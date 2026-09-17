# Central do notebook e A71

Verificação realizada em 14/09/2026.

## Estado verificado

- Notebook: Ethernet ativa a 1 Gbps, IP local `192.168.15.4`, Tailscale `100.78.67.81`.
- Home Hub 1.23.0 respondeu autenticado nas duas redes. O painel do notebook respondeu pelo Tailscale.
- O alias SSH `note` usa agora o Tailscale, preservando a verificação da chave já conhecida do notebook.
- Agente do PC iniciado; abriu Nebula 1.23.0. A entrada existente no registro inicia o agente no login.
- A API autenticada listou os projetos e abriu o VS Code em `assistente virtual`.
- Wake on Magic Packet e Shutdown Wake-On-Lan estão habilitados no adaptador do PC. A partida com o PC desligado ainda exige teste físico; BIOS e alimentação também influem.
- APK recompilado e instalado no A71 por USB. O app migra o endereço anterior do notebook para o Ethernet atual e mantém alternativa Tailscale.
- A71 SM-A715F, Android 13: autorização ADB válida. Instalação concluída com tela apagada e diagnóstico posterior `deviceLocked=1`.
- `adb_allowed_connection_time` passou de `604800000` (sete dias) para `0` (sem expiração automática). Para restaurar: `adb shell settings put global adb_allowed_connection_time 604800000`.
- 17 testes existentes passaram: agentes de inicialização e desbloqueio, fluxo de energia, sessão do dispositivo e API de ferramentas. Compilação Android concluída.

## Uso pelo cabo

A autorização ADB identifica o computador autorizado. Ela permite manutenção sem pedir o PIN a cada comando. A tela de bloqueio continua protegendo a interação visual e apps protegidos; a instalação testada não comprova acesso irrestrito aos aplicativos. Reinício, revogação de chaves ou restrições USB do sistema podem exigir intervenção local.

Com o A71 conectado ao PC principal, esse acesso USB depende do PC ligado. Para o notebook assumir também o controle USB, conecte o cabo nele e autorize a chave daquele computador uma vez. O notebook ainda não possui ADB no PATH nem no caminho padrão do SDK verificado.

## Chat e central sempre disponível

O hub da casa já funciona no notebook. O chat atual e os projetos deste PC ainda não foram transferidos para ele.

Para continuar chats do computador no telefone, a documentação oficial oferece ChatGPT Remoto: no app desktop, Configurações > Conexões > Controlar este PC > Configurar/Adicionar; parear o A71 pelo QR code, na mesma conta e workspace. A disponibilidade depende da versão e liberação para a conta. O host precisa estar ligado, online e com o aplicativo aberto.

Para independência do PC gamer, preparar o aplicativo, projetos e ferramentas no notebook e fazer o pareamento daquele host. O chat do Codex integrado ao painel Nebula não foi verificado como continuação desta conversa.

Fonte: https://learn.chatgpt.com/docs/remote-connections

## PIN do telefone para o Windows

O PIN pode confirmar uma autorização no Android; ele não se torna a senha do Windows. O projeto tem um Credential Provider próprio, mas ele não está registrado neste PC. Sua instalação solicita a senha real da conta em uma janela local; não enviar essa senha pelo chat.

Atualização de 14/09: o Android agora assina o pedido com chave P-256 do Keystore, utilizável após confirmação recente da credencial do dispositivo. A chave pública do A71 foi pareada por USB. O agente verifica assinatura, PC de destino, validade e repetição persistente. O token do hub continua sendo transporte autenticado, mas sozinho não autoriza login. O hub atualizado foi implantado no notebook e seu encaminhamento foi verificado. O agente e o Credential Provider foram recompilados. A instalação no PC está aguardando a senha na janela local; o login real ainda não foi validado.

A tela inicial do A71 foi restaurada: pede PIN antes de liberar os controles nesta sessão do app, assina o pedido e libera o painel mesmo enquanto o PC inicia. Isso não impede a manutenção por ADB autorizada anteriormente. Os testes dos agentes e fluxo de energia totalizam 20 casos aprovados, incluindo assinatura falsa, alvo incorreto, expiração e repetição após reinício.

Referências: https://developer.android.com/tools/adb e https://learn.microsoft.com/en-us/windows/win32/secauthn/credential-providers-in-windows
