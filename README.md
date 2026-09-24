# Nebula

Organização incremental e fluxo Qwen → tools, servidor de execução e acesso
LAN/remoto: [arquitetura atual](ARQUITETURA.md).

As integrações autenticadas entre PC, notebook e Android exigem a variável
`NEBULA_POWER_TOKEN` com o mesmo valor em cada build/serviço. Não armazene esse
valor no repositório; consulte a seção de rede em `ARQUITETURA.md`.

Assistente virtual em Python para Windows. Ela acorda ao ouvir exclusivamente **Nebu**,
responde por voz e executa pesquisas no YouTube ou Google.

O A71 também oferece um [manômetro de turbo do BeamNG](integracoes/beamng/README.md),
com pressão real em bar e tela cheia AMOLED. A integração pode ser instalada
com o jogo fechado; a leitura fica indisponível até receber dados de um veículo.

## Instalação

Use Python 3.10 ou mais recente. A configuração também contempla o Python 3.14
no Windows, usando uma versão compatível do PyAudio. No PowerShell, dentro desta pasta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Se o PowerShell bloquear a ativação, você pode executar sem ativar:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Uso

Para iniciar com microfone e resposta falada:

```powershell
python main.py
```

Para abrir a interface gráfica durante o desenvolvimento:

```powershell
python gui.py
```

Depois de gerado, o aplicativo final pode ser iniciado diretamente por
`dist\Nebula.exe`, sem abrir o PowerShell. A aba **Assistente** mantém o microfone
ativo e mostra a esfera animada; a aba **Conversa** exibe o histórico e aceita
comandos digitados. Alternar entre elas não interrompe a assistente.

Ao fechar a janela pelo `X`, a Nebula é recolhida para a bandeja do Windows e
continua funcionando. Clique no ícone azul da bandeja para abrir novamente ou
use **Sair** no menu do ícone para encerrar completamente.

## Aplicativo nativo no Android

Estado atual da central por Ethernet, controle USB do A71 e pendências de login/chat:
[Central do notebook e A71](integracoes/CENTRAL_NOTEBOOK_A71.md).

O código do aplicativo Android está em `android/`. A versão **1.23.0** abre uma
central nativa com **Casa**, **Dispositivos**, **Ferramentas** e **Painel**.
A tela inicial prioriza ligar o PC e controlar a casa; o Grupo permanece em
sua aba separada no desktop. Ligar o PC mantém a confirmação pelo PIN do Android.

Em **Dispositivos**, o catálogo do hub reúne PC, TVs, abajur e ar-condicionado
configurados. A integração opcional Home Assistant amplia as marcas suportadas.
Em **Ferramentas**, controle a overlay Rocket League no PC e consulte o laboratório
experimental de BPM por CSI Wi-Fi. Não há leitura de BPM sem hardware compatível.

Pacotes: `Nebula-1.23.0.apk` (Android), `Nebula-1.23.0.exe` (Windows) e
`Nebula-Notebook-1.23.0.zip` (hub). Atualize também o hub para usar o catálogo.
O APK usa a assinatura de desenvolvimento deste projeto.

Veja [controles e overlay](integracoes/CONTROLE_UNIVERSAL.md) e
[hardware, formato CSI e limites do BPM](integracoes/wifi_bpm/README.md).

## Vocabulário ensinável

A Nebula guarda termos novos em `%LOCALAPPDATA%\Nebula\lexicon.json`:

- `aprenda que quasar significa um núcleo galáctico extremamente luminoso`
- `o que significa quasar`
- `leia o dicionario em C:\caminho\glossario.txt`

O importador aceita UTF-8, uma entrada por linha, nos formatos `termo:
definição`, `termo — definição` ou colunas separadas por tabulação. Use apenas
uma fonte que você tenha direito de copiar/exportar. Aprender definições aumenta
o vocabulário consultável; criar novas ações ainda requer associá-las a uma
função do programa.

Para compilar, abra a pasta `android` no Android Studio (SDK 35), aguarde a
sincronização e use **Build > Build APK(s)**. O arquivo será gerado em
`android/app/build/outputs/apk/debug/app-debug.apk`.

### Projetos, Codex e terminal

A aba **Projetos** do aplicativo permite selecionar a pasta ativa do PC, enviar
uma tarefa ao Codex, acompanhar a resposta e executar um comando PowerShell no
diretório ativo. O terminal é autenticado pelo mesmo pareamento privado do app;
cada comando tem limite de 60 segundos.

### Proteção antirroubo

Em **Controles > Recursos do celular**, ative a proteção antirroubo e confirme
o pedido de administrador do Android. A aba **Remoto** no PC poderá bloquear a
tela e ativar o modo perdido Nebula. O aparelho continua exigindo o PIN, padrão
ou senha nativos; o comando de desbloqueio remove apenas o modo perdido Nebula.

Enquanto a notificação **Proteção Nebula ativa** estiver presente, o aplicativo
atualiza a localização conhecida e aguarda comandos em segundo plano. Se o
telefone ficar offline, o PC conserva as últimas coordenadas e seus horários.

### Ligar a Nebula pelo celular

O botão **Ligar Nebula** fala primeiro diretamente com o notebook em
`http://192.168.15.86:8766`. O notebook envia o Wake-on-LAN para o alvo
`00:E0:23:7C:7B:4D`, pela porta UDP 9, e também deixa uma ordem autenticada para
abrir a Nebula. O agente leve `pc_start_agent.py`, iniciado no login do PC,
consulta essa ordem e abre a versão mais recente da Nebula. Assim o botão também
funciona quando o PC já está ligado e somente a Nebula foi fechada. O broadcast
feito pelo próprio celular fica apenas como reserva.

O app migra automaticamente o endereço antigo `.10` para `.86` e também tenta
o endereço Tailscale `100.78.67.81` quando necessário. Para usar fora de casa,
o Tailscale precisa estar conectado no notebook e no celular.

No notebook, execute `notebook_power_server\INSTALAR-COMO-ADMINISTRADOR.cmd` uma
vez. O instalador deixa a central Nebula iniciando automaticamente no login e
libera sua porta somente para a rede local e para a faixa privada do Tailscale.
O Ollama e a Qwen não são iniciados.

### Controle universal das TVs

A aba **TVs** do Android fala diretamente com a central do notebook, portanto o
PC principal pode permanecer desligado. Use **Buscar TVs**, selecione o aparelho
e toque em **Parear**; na primeira vez, aceite o pedido mostrado na tela da TV.
Depois disso ficam disponíveis energia, volume, canais, navegação, entrada e
mídia. A central detecta Samsung Tizen e LG webOS na rede local e guarda as
credenciais de pareamento apenas no notebook.

Foram identificadas na rede uma LG webOS e duas Samsung. Para ligar uma TV por
Wake-on-LAN, ela precisa continuar conectada à rede durante o modo de espera e a
opção de inicialização pela rede deve estar habilitada no televisor.

## Interface web no celular (legada)

Com a Nebula aberta no PC e o Tailscale conectado nos dois aparelhos, abra no
Android o endereço HTTPS exibido na aba **Remoto**. Toque em **Instalar
aplicativo** na página ou use o menu do navegador e escolha **Adicionar à tela
inicial**. O aplicativo continua privado na sua rede Tailscale e o PC precisa
permanecer ligado para executar comandos.

O pareamento é persistente: normalmente o PIN só precisa ser informado uma vez.
O painel também possui **Pausar Nebula** e **Retomar** para bloquear rapidamente
novos comandos pelo celular. A pausa não desfaz uma ação que o Windows já tenha
concluído, como um programa que acabou de ser aberto.

Em **Projeto ativo**, escolha uma pasta recente do VS Code ou informe o caminho
completo de outra pasta. A escolha permanece salva e passa a ser usada tanto por
**Abrir VS Code** quanto pelas solicitações enviadas ao Codex.

A seção **Conversar com a Nebula** envia comandos diretamente para a assistente
do PC. Ela aceita voz ou texto no celular e pode usar as funções já disponíveis,
como controlar mídia, abrir aplicativos e jogos, pesquisar e tirar prints.

O `qwen3:8b` permanece instalado, mas está desativado por padrão e descarregado
da GTX 1050. Com isso, pedidos não reconhecidos pelas regras locais não acordam o
Ollama nem reservam VRAM. Se um dia quiser reativá-lo, defina
`NEBULA_QWEN_ENABLED=1`, inicie o Ollama e configure `NEBULA_OLLAMA_URL` e
`NEBULA_OLLAMA_MODEL` quando necessário.

## Grupo geral: Você e Codex

A aba **Grupo** cria uma conversa persistente entre Você e Codex. O histórico
continua compatível com mensagens antigas da Qwen, mas novas rodadas não a
carregam nem enviam requisições ao notebook.

O histórico é salvo em `%LOCALAPPDATA%\Nebula\grupo_chat.json`. Dentro do grupo,
o Codex roda de forma efêmera, em uma pasta isolada e com sandbox somente leitura;
as mensagens do grupo não autorizam alterações no computador. Cada resposta do
Codex utiliza a cota normal da conta conectada ao Codex.

### Memória compartilhada e correções

O botão **Contexto e correções** abre a memória comum usada pela Nebu e pelo
Codex. O contexto base fica em `contexto_nebula.md`; preferências adicionadas no
editor ficam em `%LOCALAPPDATA%\Nebula\contexto_usuario.md`, e correções de fala
ficam em `%LOCALAPPDATA%\Nebula\correcoes_entendimento.json`.

Também é possível ensinar por voz ou texto:

- “Nebu, quando eu disser nevo, entenda como nebu”
- “Nebu, corrija quibe isso para clipe isso”
- “Nebu, guarde na sua memória que eu prefiro respostas diretas”

As correções são aplicadas antes da palavra de ativação e antes dos comandos. A
memória enriquece a interpretação e a personalidade, mas nunca concede ao Codex
permissão para executar ações no computador.

### Feedback contínuo

Nas abas **Conversa** e **Grupo**, cada última resposta pode receber 👍 ou 👎 e
um comentário opcional. No grupo, o feedback é associado ao Codex. O painel do
celular oferece a mesma avaliação para a última resposta
da Nebula.

Também funciona por voz:

- “Nebu, gostei dessa resposta porque foi direta”
- “Nebu, não gostei dessa resposta porque ficou robótica”

Os registros ficam somente no PC, em
`%LOCALAPPDATA%\Nebula\feedback_conversas.json`, e entram como sinais de qualidade
e preferência nas próximas conversas. Eles não autorizam ações e não são enviados
automaticamente a terceiros. O botão **Feedbacks** permite
revisar ou apagar todos os registros. Ao incluir o Codex numa rodada do grupo,
os feedbacks recentes fazem parte do contexto enviado ao Codex naquela rodada.

### Convivência com o app Tuya

Comandos comuns da Nebula fecham a conexão local assim que terminam, deixando a
lâmpada livre para o app Tuya. Durante música, tocha ou RPM, a conexão permanece
aberta somente enquanto a animação estiver ativa. O modo música congela o perfil
encontrado ao iniciar: uma lâmpada em `white` pulsa mantendo a mesma temperatura,
e uma lâmpada em `colour` mantém a mesma matiz, sem alternar entre os dois modos.

Exemplos de comandos:

- “Nebu, toca After Dark”
- Ao pedir para tocar uma música, a Nebula abre diretamente o primeiro vídeo do YouTube;
  pedidos para pesquisar continuam abrindo a página de resultados.
- “Nebu, procure synthwave no YouTube”
- “Nebu, pesquise como funciona um buraco negro”
- “Nebu, que horas são?”
- “Nebu, pode dormir”
- “Nebu, abra o Discord”
- “Nebu, abra o Brave”
- “Nebu, feche o Rocket League, o Brave e a Steam” (pede uma confirmação)
- “Nebu, que música está tocando?” (captura 10 segundos do áudio do PC)
- “Nebu, inicie o VS Code”
- “Nebu, conte uma piada”
- “Nebu, conte uma piada de humor negro”
- “Nebu, tire um print da tela”
- “Nebu, escreva no Bloco de Notas comprar pão e café”
- “Nebu, clipe” / “Nebu, clipa isso” (aceita pequenas variações do microfone e requer Repetição instantânea do NVIDIA App ativa)

### Abajur Wi-Fi Elgin Smart

A integração usa uma conexão Tuya direta entre o PC e a lâmpada pela rede local.
Depois da configuração inicial, o celular pode ficar desligado ou longe do
computador e os comandos não dependem da nuvem. A Nebula não recorre mais ao
aplicativo Elgin por ADB: quando faltar a configuração, ela orienta a abrir a aba
**Configuração** em vez de pedir um telefone conectado por USB.

Comandos disponíveis:

- “Nebu, ligue o abajur” / “Nebu, desligue o abajur”
- “Nebu, deixe o abajur azul” (também vermelho, verde, amarelo, roxo, rosa e ciano)
- “Nebu, deixe a luz branca”, “luz quente” ou “luz fria”
- “Nebu, coloque o brilho do abajur em 40 por cento”
- “Nebu, mude a temperatura da luz para mais baixa e diminua o brilho 20%”
  (luz mais quente e redução de 20 pontos no brilho atual)
- “Nebu, ative a animação musical” (mantém a cor atual e pulsa somente o brilho)
- “Nebu, faça o abajur piscar azul com a música” (mantém a cor e pulsa o brilho suavemente)
- “Nebu, modo música do abajur RGB 255 20 147”
- “Nebu, aumente a intensidade do pulso” (sobe 20 pontos sem mudar a cor)
- “Nebu, coloque a intensidade da animação em 90%”
- “Nebu, pare o modo música do abajur”
- “Nebu, ative o modo tocha” (laranja com pequenas brasas vermelhas e brilho de chama)
- “Nebu, pare o modo tocha”
- “Nebu, salve a cor RGB 255 20 147 como neon”
- “Nebu, salve a cor hexadecimal FF1493 como rosa neon”
- “Nebu, salve a cor atual como pôr do sol” (lê a seleção visível no Elgin Smart)
- “Nebu, use a cor salva neon no abajur”

As cores personalizadas ficam em `%LOCALAPPDATA%\Nebula\cores_abajur.json`.

#### Configuração direta, sem celular durante o uso

A comunicação Tuya local exige `device_id`, IP, protocolo e uma `local_key` de
16 caracteres. O scanner já consegue descobrir os três primeiros; a chave não
pode ser deduzida da rede e deve ser obtida uma única vez pela conta Tuya:

1. Crie/vincule um projeto em [Tuya IoT](https://iot.tuya.com/) à conta do app.
   Se a conta OEM do Elgin Smart não puder ser vinculada, use Smart Life/Tuya
   Smart. Migrar o dispositivo exige reset e novo pareamento e troca a chave.
2. Em uma pasta vazia fora deste projeto, execute o assistente oficial e copie a
   `local_key` da lâmpada:

   ```powershell
   python -m tinytuya wizard
   ```

3. Abra a aba **Configuração** da Nebula, clique em **Detectar na rede**, cole a
   chave no campo mascarado e use **Salvar e testar**. O teste faz somente uma
   consulta de estado; não muda a cor nem liga/desliga a lâmpada. O script
   `configurar_abajur.py` continua disponível apenas como alternativa de terminal.

O configurador salva o segredo apenas em
`%LOCALAPPDATA%\Nebula\abajur_tuya.json` e faz uma consulta de estado sem alterar
a lâmpada. Não publique `abajur_tuya.json`, `devices.json`, `snapshot.json`,
`tinytuya.json` ou `tuya-raw.json`. Se a lâmpada for resetada ou pareada de novo,
obtenha a nova chave e repita o passo 3.

No modo música, a Nebu confirma a atividade de Brave, Chrome, Edge, Firefox ou
Opera pelo mixer do Windows. Discord e outros aplicativos não ativam o efeito.
O pulso é dirigido pela faixa de graves da saída de áudio (aproximadamente
45–160 Hz), reduzindo a reação a fala e priorizando bumbo e baixo. Serviços
claramente musicais e áudio com pulso regular animam somente o brilho,
preservando a cor ou temperatura selecionada. Títulos com sinais de aula,
tutorial, explicação, podcast ou análise não são usados como atalho de detecção.
Por padrão a intensidade do pulso é 75% e a animação roda a 10 quadros por
segundo; o valor continua ajustável sem alterar a cor escolhida.
O modo tocha é independente: ele fica predominantemente laranja, acrescenta
pequenas brasas vermelhas e varia o brilho dentro de limites fixos, sem amarelar
demais nem piscar de forma agressiva.
Todas as animações do abajur usadas pela Nebula agora vão direto pela LAN, sem
ADB e sem telefone conectado durante o uso.

Comece a reprodução no navegador antes de ativar o modo. Quando o título não
indica claramente que é música, o detector precisa de até seis segundos para
reconhecer o ritmo. Títulos de outras abas não bloqueiam mais uma batida detectada,
e falhas no medidor de áudio agora são informadas em vez de confirmar uma animação
que não iniciou. Confira `Nebula 1.14.4` no título da janela para não usar por
engano uma compilação antiga.

Para publicar uma atualização, altere somente `VERSAO_NEBULA` em `versao.py` e
execute `build_release.ps1`. O mesmo número alimenta o desktop e o Gradle, e o
comando sempre testa e gera juntos `Nebula-<versão>.exe` e
`Nebula-<versão>.apk`. Use `-InstallAndroid` para também atualizar o aparelho
conectado por ADB.

### Modo RPM genérico para jogos de corrida

Não há uma API de RPM compartilhada literalmente por todos os jogos. A Nebula
agora recebe um protocolo UDP local genérico (`127.0.0.1:29876`), e a ponte do
SimHub incluída em `integracoes\simhub` cobre os jogos que o SimHub suporta e
que expõem RPM, limite de giro e acelerador. A Nebula normaliza o giro pelo
limite do carro e usa o acelerador para comandar as duas luzes:

- amarelo-claro em giro baixo;
- laranja na faixa média;
- vermelho em giro alto;
- vermelho piscando ao permanecer no limitador com o acelerador pressionado.

Há histerese entre as faixas para a cor não oscilar perto dos limites. A
lightbar do DualShock 4 responde imediatamente por HID USB; o abajur usa a mesma
faixa lógica pela LAN, limitado a quatro atualizações por segundo para proteger
o firmware. O perfil é destinado principalmente a BeamNG.drive e Assetto Corsa:
amarelo-claro em RPM baixo, laranja no médio, vermelho no alto e pisca vermelho
sincronizado no limitador. Comandos: “Nebu, ative o modo RPM”, “Nebu, status do modo RPM” e
“Nebu, pare o modo RPM”. Consulte `integracoes\simhub\README.md` para instalar a
ponte. Jogos fora do catálogo do SimHub ainda precisam de um adaptador próprio
para o protocolo documentado em `integracoes\PROTOCOL.md`.

Para evitar disputa pela lightbar, feche completamente a Steam/DS4Windows
durante o primeiro teste ou desative o controle de LED deles.

### Modo boost — Rocket League

A Nebula lê visualmente o aro de boost no canto do HUD, sem injetar DLL, abrir o
processo do jogo ou depender do BakkesMod. A leitura usa a intensidade do aro em
vez da matiz, portanto funciona tanto com a cor azul quanto com a laranja. A
Nebula preserva a cor ou temperatura atual do abajur e faz o DualShock 4 e os
teclados compatíveis acompanharem a mesma proporção. A lightbar aproxima a cor
atual do abajur, inclusive em branco quente/frio. No Redragon Kumara Lunar, as
teclas formam uma barra horizontal: 100% acende todo o teclado e a barra apaga
da direita para a esquerda conforme o boost diminui.

A cor dessa barra pode ser escolhida em **Controle > Cor do teclado no Boost**.
A preferência fica salva para as próximas ativações e, se o Boost já estiver
ligado, a nova cor é aplicada automaticamente. Ela afeta somente o teclado, sem
alterar a cor preservada do abajur ou da lightbar.

- zero boost: 1% de brilho;
- boost intermediário: brilho proporcional;
- boost cheio: 100% de brilho.

No X98HE, zero boost usa o menor RGB que o firmware ainda consegue exibir. As
mudanças são agrupadas em passos de 5% e usam o efeito estático, evitando o modo
de feed proprietário que ficava apagado sem o Attack Shark IOT. O controle e o
teclado são opcionais: se algum estiver desconectado, o abajur
continua funcionando. O X98HE precisa estar conectado por cabo USB para expor o
canal RGB. Ao parar o modo, minimizar o jogo ou perder o HUD, o brilho/efeito
anterior é restaurado. Comandos: “Nebu, ative o modo boost”, “Nebu, status do
modo boost” e “Nebu, pare o modo boost”.

O plugin x64 `NebulaBoost.dll`, em `native\nebula_boost`, continua disponível
como alternativa para treino/offline com o BakkesMod. Com o Easy Anti-Cheat
ativo, a integração visual é a opção padrão. Para escolher deliberadamente o
plugin em uma sessão offline, inicie a Nebula no mesmo terminal após executar:

```powershell
$env:NEBULA_BOOST_SOURCE = "rocket_league"
```

### Modo Ambilight — Netflix

A Nebula pode fazer a lâmpada Tuya acompanhar a cor média das cenas visíveis da
Netflix no navegador. A janela é capturada localmente em 30 FPS; barras pretas
são descartadas, as mudanças recebem suavização curta e somente diferenças
perceptíveis são enviadas à lâmpada, em até 10 atualizações por segundo. Nenhuma
imagem é salva ou enviada pela rede.

O modo reserva a lâmpada enquanto está ativo e restaura o perfil branco/colorido
e o brilho anterior ao terminar. Ele é exclusivo em relação aos modos música,
tocha, RPM e boost. Comandos: “Nebu, ative o modo Ambilight”, “Nebu, status do
Ambilight” e “Nebu, pare o Ambilight”. A janela da Netflix precisa permanecer
visível; capturas bloqueadas por DRM não podem ser contornadas pela Nebula.

Para testar usando o teclado, sem instalar bibliotecas de áudio:

```powershell
python main.py --texto
```

Para testar sem abrir abas no navegador:

```powershell
python main.py --texto --sem-navegador
```

O reconhecimento de voz usa o serviço de reconhecimento do Google e, portanto,
precisa de internet. As respostas usam a voz neural feminina Francisca do Edge;
se o serviço estiver indisponível, a Nebula volta automaticamente ao SAPI do Windows.

## Instalar voz em português brasileiro

Pressione `Windows + Ctrl + N` para abrir o Narrador. Em **Voz do Narrador**,
selecione **Adicionar vozes legadas**. Na página de Fala, entre em **Gerenciar
vozes > Adicionar vozes**, escolha **Português (Brasil)** e instale.

Feche e abra novamente a Nebula após a instalação. Ela prioriza automaticamente
as vozes brasileiras Maria ou Henrique quando uma delas está disponível.

## Espaço 1.28

O **Espaço** é a nova cara da Nebula: uma nebulosa volumétrica em WebGL por trás
de sete seções — Conversa, Casa, Projetos, Memória, Áudio, Telefone e Terminal.
Não é uma tela de demonstração: cada seção usa as mesmas APIs que a janela do PC
e o painel do celular já usavam, então o que funciona no painel funciona nele.

O front fica em `nebula_front/`, em uma cópia só, servida em três lugares:

- **No PC**, pelo botão **✧ Espaço** na barra lateral da janela da Nebula (ou
  pelo ícone na bandeja). Abre em janela própria do Chrome, Edge ou Brave,
  apontando para `http://127.0.0.1:8765/espaco/`. A Nebula emite um bilhete de
  uso único, válido por 90 segundos e aceito só no loopback, para a janela já
  nascer autenticada. Sem nenhum Chromium instalado, abre no navegador padrão.
- **No celular**, pelo cartão **Espaço** da tela inicial do aplicativo. O APK
  troca a credencial do aparelho por uma sessão curta e carrega `/espaco/` no
  WebView. Se o PC ainda estiver em uma versão anterior, o painel clássico
  responde no lugar.
- **No notebook**, o Home Hub ganhou o mesmo tratamento (veja abaixo).

**F11 alterna a tela cheia** no Espaço, na janela principal da Nebula, no
console do hub e na janela nativa do hub. No celular, o F11 de um teclado
Bluetooth também funciona, e o botão ⤢ no cabeçalho faz o mesmo.

Nada no Espaço depende de internet: as fontes são as do sistema e não há CDN.

## Nebula Home Hub 1.28

O monitor do hub no notebook passou a seguir a mesma temática. A janela nativa
desenha o conteúdo sobre um céu estrelado, colore cada linha do log conforme o
resultado da requisição (sucesso, bloqueada, falha ou aviso) e acompanha o mesmo
passeio de cor do acento do front. **F11** deixa a janela em tela cheia.

O botão **Abrir console no navegador** abre `http://127.0.0.1:8766/hub/`: a mesma
nebulosa em WebGL, com as métricas do servidor, o painel de sprints e o log ao
vivo. O console é liberado no loopback e, de fora da máquina, exige o
`X-Nebula-Power-Token`. As consultas do console não entram na contagem de
requisições do hub — do contrário encheriam justamente o log que ele mostra.

## Painel de controle 1.18

A Nebula agora abre em um painel minimalista escuro, tanto no Windows quanto no
Android. O painel permite ligar e desligar o PC, controlar cor, temperatura e
brilho do abajur, selecionar apenas um modo dinâmico por vez, silenciar a voz da
assistente e acompanhar o RPM em um mostrador inspirado em uma FuelTech.

O notebook funciona como central da casa: ele conserva o estado dos controles,
executa o Wake-on-LAN e controla diretamente o abajur. Modos que precisam da tela
ou da telemetria do PC gamer, como Ambilight, RPM e boost, são encaminhados para o
agente da Nebula no PC.

No Ambilight, o abajur e a lightbar PS4 acompanham a média da tela principal.
O Kumara acompanha os três blocos inferiores de uma grade 3 × 3. O modo
**Ambilight + RPM** mantém a iluminação da tela e o painel RPM do celular juntos.

O Kumara USB 320F:5000 usa envio direto com resposta de cada bloco de LEDs,
limitado a cinco quadros por segundo. O firmware testado não responde ao comando
de troca de modo, que travava a fila do driver genérico do OpenRGB. A Nebula
encerra sua instalação local do OpenRGB antes de assumir esse teclado; uma
instância externa deve ser fechada. Ao encerrar o efeito, volta ao modo reativo.
Outros modelos continuam usando OpenRGB. Não é necessário abrir o programa da
Redragon para usar a iluminação do Kumara.

No celular, o modo Boost também oferece um display imersivo: a área iluminada
sobe da base da tela conforme o boost, ocupando metade da tela em 50% e toda a
tela em 100%. O toque em sair fecha apenas o display e preserva o modo ativo.

## Casa conectada 1.21

A aba **Casa** do Windows e o painel **Controle** do Android controlam o
ar-condicionado Voltas diretamente pelo Smart IR na rede local. Estão disponíveis
liga/desliga, temperatura de 16 a 30 °C, modos Frio, Quente, Auto, Ventilar e
Desumidificar e ventilação Auto, Fraca, Média e Forte. A TV Philips cadastrada
no Smart IR não é usada. O controle do ar não depende do eKasa, do Samsung,
de USB nem de ADB e continua disponível pelo hub quando o PC gamer está desligado.

O controle de TVs ganhou ações simultâneas para todas as Samsung Tizen e LG
webOS descobertas no Wi-Fi. Em **YouTube multiroom**, digite uma música, artista
ou cole um link e escolha **Tocar em todas** para abrir o mesmo vídeo nas TVs
pareadas. Cada TV ainda pode ser selecionada e controlada individualmente.
O hub do notebook aceita atualizações autenticadas e verificadas por SHA-256.
Depois da instalação inicial da versão 1.21, os próximos builds enviam e
reiniciam o hub automaticamente.
No Kumara, o mesmo percentual acende progressivamente as teclas e mantém o
restante apagado, formando uma barra física de boost.
## Ligar e autorizar o Windows pelo telefone

Na tela offline do Android, **Ligar Nebula** exige a confirmação do bloqueio
seguro do próprio telefone antes de enviar o Wake-on-LAN. O envio direto usa o
endereço Wi-Fi local e não depende mais de `Network.bindSocket`, evitando a
falha `EPERM` observada em alguns aparelhos Samsung. O hub do notebook também é
notificado: se o PC não responder em 45 segundos, a interface completa da
Nebula abre no notebook.

O desbloqueio opcional do Windows fica em `native\nebula_credential_provider`.
Ele usa um Credential Provider V2, um agente de pré-login e uma autorização de
uso único que expira em 120 segundos. A senha real do Windows é cadastrada uma
vez no próprio PC, validada localmente e protegida com DPAPI; ela nunca é
incluída no APK, no Wake-on-LAN nem no hub. Os provedores normais de PIN e Senha
do Windows permanecem disponíveis para recuperação.
