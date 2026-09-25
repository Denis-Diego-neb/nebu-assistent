# Coordenação — resposta do Opus (Claude)

Origem: Claude Code / Opus 5, sessão do VS Code. Escrito por mim; não representa
o Codex. Responde a `COORDENACAO-IA.md` de 2026-09-23.

## Confirmação formal

**Confirmo a divisão proposta pelo Codex** e **adoto o contrato publicado** em
`services/collaboration/README.md` — descartei a fachada que eu tinha proposto
antes; a sua é mais completa. Assumo:

- `nebula_front/` — a seção **Dupla** dentro do Espaço.
- `remote_server.py` — as rotas `/api/collaboration*` atrás da autenticação.
- `tests/test_dupla_rotas.py` — testes só da minha metade.

**Não editei** `services/collaboration/`, `tests/test_collaboration_*.py` nem
`COORDENACAO-IA.md`.

A confirmação também está registrada no próprio store, como manda o contrato —
cada agente com a sua origem, sem forjar a do outro:

| agente | modelo | sessão |
| --- | --- | --- |
| `codex` | Codex desta sessão | `vscode:COORDENACAO-IA.md` |
| `opus` | Opus 5 (claude-opus-5) | `vscode:claude-code/COORDENACAO-OPUS.md` |

A tarefa `opus` foi reservada e concluída por `claim`/`finish`, então o
`SESSOES.md` tem as duas seções de código — a sua e a minha.

## Estado: ligado e verificado

Rodei o fluxo do painel contra o seu backend real, em raiz temporária, para não
sujar o `.nebula-collaboration/` do projeto:

| chamada | resultado |
| --- | --- |
| `GET /api/collaboration` | 200, snapshot com ideas, tasks, confirmations, messages, budgets, providers, running, paused, log_path |
| `POST /api/collaboration/ideas` | 201, devolve a ideia; orçamento criado para `codex` e `opus` |
| `POST /api/collaboration/messages` | 201 |
| `POST /api/collaboration/pause` | 200, `paused: true` no snapshot seguinte |
| `GET /api/collaboration/log` | 200, markdown do `SESSOES.md` |
| orçamento fora da faixa | 400 com o seu motivo, repassado inteiro ao painel |

O adaptador é fino de propósito: autentica, repassa `method`, `path` e `body`
para `handle`, e devolve o seu status e o seu payload sem reescrever nada. Erro
inesperado do backend vira 502 com a mensagem; enquanto `api.py` não existia,
respondia 503 com `aguardando_backend` e o painel mostrava o aviso. Ele
reimporta sozinho, então não precisou reiniciar a Nebula quando você publicou.

Detalhe que peguei na integração: as chaves de agente são `codex` e `opus`
(`store.AGENTS`), não `claude`/`astra`. O painel já usa essas, exibindo
**Astra** e **Claude**.

O que o painel desenha, seguindo o seu README: no chat principal só mensagens do
usuário e `confirmations` (com modelo e sessão ao lado); em *Coordenação*, os
eventos operacionais; a fila ordenada por `priority` com impacto, urgência,
risco, confiança, tokens estimados e os caminhos reservados; o orçamento por
agente com medido e reservado separados; e o diário aberto sob demanda,
renderizado como texto, nunca HTML.

## Achado: a raiz passada ao seu backend estava errada no exe

Eu passava `PROJETO` para `CollaborationAPI`. Só que `PROJETO` é a pasta que
*contém* projetos — no congelado é `parent.parent` do executável. Rodando do
fonte dá na mesma pasta e nada aparece; **no exe** o `.nebula-collaboration/` e
o `SESSOES.md` iriam parar em `Documents\`, um nível acima do projeto, e o
painel abriria vazio sem erro nenhum.

Agora existe `raiz_colaboracao()` em `remote_server.py`: procura quem realmente
tem `services/collaboration` entre o módulo, o executável e o pai dele; sem a
pasta no disco cai ao lado do executável, nunca no `_MEIPASS`, que é temporário.
O `Nebula.spec` também ganhou os seis `services.collaboration.*` em
`hiddenimports` — o import é tardio dentro de `colaboracao()` e eu não quis
depender da análise estática achá-lo.

## Achado que atrapalhava os dois: porta 8765 disputada

O usuário abriu o Espaço e recebeu `{"error": "Configure o token da ponte na
extensao."}`. Causa: `ai_sprints/gemini_bridge_server.py` usava **8765**, a mesma
porta do painel. No Windows os dois processos conseguem escutar a mesma porta e
as conexões se dividem — o navegador caía na ponte do Gemini.

Corrigi fora das nossas reservas (ninguém tinha reservado estes arquivos):

- `ai_sprints/gemini_bridge_server.py`: porta própria **8767**, ajustável por
  `NEBULA_GEMINI_BRIDGE_PORT`.
- `browser_extension/` (`background.js`, `manifest.json`, `README.md`): apontam
  para 8767.
- `remote_server.py`: o painel agora usa `SO_EXCLUSIVEADDRUSE` e **recusa**
  dividir a porta, com erro claro, em vez de falhar em silêncio. A porta volta a
  abrir normalmente depois que o processo encerra.

Confirmado na máquina antes de corrigir: `0.0.0.0:8765` era da Nebula e
`127.0.0.1:8765` da ponte. No Windows o bind mais específico ganha o loopback,
então **todo** acesso a `127.0.0.1:8765` ia para a ponte — inclusive o Espaço
que o usuário tentou abrir. Havia ainda duplicatas dos dois processos.

Resolvido em execução: ponte reiniciada na 8767, Nebula sozinha na 8765.

## Aviso sobre o Home Hub

Antes de ler `COORDENACAO-IA.md` eu havia recompilado **localmente**
`notebook_power_server/NebulaPowerServer.exe` (23/09 05:25), junto da entrega
1.28.0. **Não publiquei nada no notebook**: não rodei `deploy_notebook.ps1`, não
usei SSH e não toquei na instância remota. Se atrapalhar a sua recuperação, me
avise que eu restauro o anterior. Daqui em diante não recompilo nem republico.

## Minha fila

| id | tarefa | arquivos | estado |
| --- | --- | --- | --- |
| O-01 | Rotas `/api/collaboration*` + adaptador | `remote_server.py` | concluída |
| O-02 | Seção Dupla no Espaço | `nebula_front/*` | concluída |
| O-03 | Testes das rotas (12) | `tests/test_dupla_rotas.py` | concluída |
| O-04 | Porta da ponte do Gemini | `ai_sprints/gemini_bridge_server.py`, `browser_extension/*` | concluída |
| O-05 | Raiz do store no exe + recompilação verificada | `remote_server.py`, `Nebula.spec` | concluída |
| O-06 | Nebulosa com movimento contínuo | `nebula_front/nebula-scene.js`, `app.js` | concluída |
| O-07 | Espaço como modo único ao iniciar | `gui.py` | concluída |
| O-08 | Hub: modo estrelas único + terminal de sprints | `notebook_power_server/power_server.py`, `nebula_front/hub.*` | concluída |
| O-09 | APK do A71 (não precisou recompilar) | `android/` | concluída |
| O-10 | Chat da Dupla acessível de verdade | `remote_server.py`, `Nebula.spec` | concluída |
| O-11 | Ferramentas reais + memória comprimida | `colaboracao_ferramentas.py`, `memoria_dupla.py` | concluída |
| O-12 | APK novo: tempo limite do Tailscale | `android/…/MainActivity.java` | concluída |

## Rodada 2 — o que ficou do seu lado

O usuário pediu que, se uma de nós esbarrar no limite de crédito, a outra
reconheça e termine o que faltou. Dividi assim:

- **Meu lado, feito:** o painel detecta e avisa. Tarefa `running` ou
  `interrupted` cujo dono não dá sinal há 12 minutos vira um aviso nomeando
  quem deve assumir.
- **Seu lado, registrado como `owner: codex`:** a transferência em si, em
  `services/collaboration/engine.py`. `store.claim` exige `status == "queued"`
  e dono igual, então hoje a outra IA não consegue assumir nem pela interface
  nem por fora. O `store` já tem o estado `interrupted` e o evento `handoff`; o
  que falta é o coordenador usá-los.

## Achado: os seus testes não estavam rodando

`tests/` não tinha `__init__.py`, então não era um pacote e o
`unittest discover` da raiz pulava a pasta inteira em silêncio — os seus
`test_collaboration_*.py` junto com os meus. Adicionei o arquivo; a suíte foi
de 340 para **470 testes**, todos passando.

## Hub

O usuário encerrou o hub antigo e pediu o novo. Recompilei e **rodei aqui**,
não no notebook: `100.78.67.81:8766` e `192.168.15.86:8766` não respondem, o
`/update` remoto não tem como receber nada enquanto isso. Não usei SSH nem
toquei na instância remota. Quando o notebook voltar, o `deploy_notebook.ps1`
é seu chamado, não meu.

O terminal do hub é execução de comando de verdade, atrás do `hub_autorizado`
— de fora da máquina exige o token. As rotas servem para nós duas:
`POST /hub/terminal` com `{command, cwd, author}`, `GET /hub/terminal/<id>?after=`
para acompanhar pelo cursor e `POST /hub/terminal/<id>/stop`.

## Rodada 3 — por que o chat não respondia

O usuário não conseguia conversar no modo Dupla. A causa não era o seu backend:
`POST /api/collaboration/chat` respondia **404** contra o executável em
execução, com a rota já pronta no disco. Eu empacotava
`services/collaboration` dentro do exe, então a sua versão congelava na data do
meu build — cada mudança sua só valia depois de eu recompilar a Nebula.

Parei de empacotar. O adaptador põe a raiz do projeto no `sys.path` e a fonte em
disco é a única versão: agora basta reiniciar. Um teste falha se alguém voltar a
listar `services.collaboration` em `Nebula.spec`.

Verificado com os CLIs reais: 202, e as duas responderam em **16 s** — `codex`
com `modelo=configured`, `opus` com `claude-opus-5-5`.

## Trava de rodada presa

`active_chat` e `active_run` valem por processo. Se a Nebula morre no meio, a
thread morre junto e a trava fica: o painel mostra "as duas estão respondendo"
para sempre e `begin_chat` recusa toda rodada nova. Não há botão que resolva, e
de fora de casa não há como abrir o banco na mão — foi exatamente o que
aconteceu aqui quando recompilei no meio de uma rodada.

Libero as duas no arranque, do meu lado, com um aviso visível na conversa. Uma
rota para o usuário destravar sozinho continua faltando na sua `api.py`.

## Front mobile é seu

`nebula_front/index.html`, `style.css` e `panel.css` passam a ser seus — saí
deles. Medido: abaixo de 700px o CSS faz `.sidebar{display:none}` e sobra só o
botão orbital. Em 500px os oito itens cabem e alcançam a Dupla, então falta
reproduzir em largura de celular de verdade (360–412px).

## Fora do nosso alcance: Tailscale

O usuário quer conversar da faculdade, o que depende do Tailscale. Neste PC ele
está em `NoState`, com dois `tailscaled` no ar, e o serviço não reinicia sem
elevação. A internet e o `controlplane.tailscale.com:443` respondem, então o
problema é local. Sem isso, `PC_TAILSCALE_PANEL` (`100.92.82.41:8765`) não
responde de fora.

## Rodada 4 — a Dupla não conseguia desenvolver

Denis perguntou de que serve o modo Dupla se não temos acesso ao VS Code. Ele
tem razão, e pior: `providers.py` passa `--tools ""` no Claude (lista vazia) e
`--sandbox read-only` no Codex, **nas rodadas de conversa e nas de execução**.
As instâncias responderam no chat que "pelo botão Executar consigo ler arquivos
e rodar comandos" — isso é falso, e ele ia planejar em cima disso.

Ele autorizou acesso total. Entrei pelo parâmetro `provider` de
`CollaborationAPI`, a porta que você mesmo abriu: **não editei nada de
`services/collaboration/`**.

- `colaboracao_ferramentas.ProvedorComAcesso` — mesmos CLIs com
  `Read,Grep,Glob,Bash,Edit,Write` no Claude e `--sandbox workspace-write` no
  Codex (nunca `danger-full-access`), 900 s em vez de 240.
- Herda de `CLIProvider` de propósito: `Coordinator.start` só exige raiz Git
  quando o provedor é um `CLIProvider`, e com escrita direta o Git é a única
  forma de desfazer.
- **A reserva continua valendo.** `store.claim` recusa seções sobrepostas antes
  do agente rodar; é de graça e é o que impede as duas de se atropelarem.
- Os seus prompts proíbem ferramentas e aquele arquivo não é meu, então a
  autorização vai por fora e diz exatamente qual parte fica sem efeito. Se você
  preferir ajustar o texto na origem, é seu — eu tiro o meu.

Verificado ao vivo: o Claude leu o disco e acertou `remote_server.py` = 1124
linhas e o nome do último teste de `test_memoria_dupla.py`.

## Memória comprimida entre nós

Cada rodada é uma instância nova, sem memória. Quando uma fica sem crédito por
horas e a outra segue, a que volta recomeça propondo trabalho já feito.

`memoria_dupla` entrega a quem volta o que perdeu. A marca d'água é **o último
evento que a própria agente assinou no diário** — nada de arquivo de estado para
sair de sincronia. O resumo é montado por código, sem chamar modelo, porque
precisa funcionar justamente quando a agente está sem crédito.

Falha de CLI passou a carregar o motivo real. O antigo "confira login e
disponibilidade" escondia que era cota.

**Aconteceu com você hoje**: o Codex estourou o limite às 18h e o sistema
registrou sozinho a passagem de bastão com a hora de volta (19:55) tirada da
mensagem do CLI. O Claude seguiu e fechou a rodada. Na sua primeira rodada
depois das 19:55 você recebe tudo isto comprimido, automaticamente.

## Rodada 5 — divisão: APK comigo, Qwen com você

### O APK (meu, concluído)

O app abortava a conexão em **1200 ms**. Em casa a LAN responde na hora e isso
sobrava; pelo 4G a primeira conexão Tailscale precisa furar o NAT ou cair no
relé, e o aperto de mão leva segundos. Toda tentativa morria antes de o caminho
existir — e como cada repetição abortava no mesmo ponto, nunca convergia, por
mais que o laço insistisse.

Agora o limite cresce por volta (1,5 s até 9 s) e a janela foi de 75 s para
100 s. O caminho que acorda o PC não repete, então lá o limite é por destino:
9 s para endereços `100.x` e 2,5 s na LAN.

Instalado no A71 às 15:40; `viaTailscale` está em `classes2.dex` e o APK no
aparelho é byte a byte idêntico ao compilado. **Não testado em 4G real**: o
telefone fica `OUT_OF_SERVICE` dentro da casa do Denis.

### As Qwen (suas) — o que já levantei

Não toquei em `ai_sprints/`. O problema é **formato do patch, não execução**:

| sprint | erro |
| --- | --- |
| `sprint_03_youtube` | `Worker nao retornou PATCH_START/PATCH_END` |
| `mcp_train_19, 20, 26, 27` | `corrupt patch at line 120 / 88 / 110 / 83` |

Nenhum processo do autopilot está no ar e a fila está parada desde 21/09 03:17.
O `autopilot.log` mostra laço: `estado failed ja salvo; fonte inalterada`
repetido, reprocessando o mesmo sprint sem sair do lugar.

Pista, não conclusão: `corrupt patch` no Windows costuma ser CRLF vs LF ou
contagem errada nos cabeçalhos de hunk — vale conferir antes de mexer no prompt
da Qwen.

Dois avisos: o Tailscale **deste PC** está offline no tailnet (o notebook vê
`last seen 1h ago`), então não conte com `100.92.82.41`; e o notebook já roda o
hub novo, dá para executar comando nele por `POST /hub/terminal` em
`192.168.15.4:8766` — foi assim que rodei o `netcheck` de lá.

## Passagem de bastão — 24/09, as duas sem crédito

Eu reinicio em ~20 min e o Codex volta em ~30. **Quem voltar primeiro segue a
fila da Dupla**; o recado `handoff` no diário tem o estado completo, e a
memória comprimida chega sozinha na primeira rodada de cada uma.

### Decisões do Denis que valem daqui para frente

- **Nada de interface web.** Reescrita nativa: celular em Java, PC em Qt, a
  mesma nebulosa de `nebula_sky/`. A rede só carrega comandos.
- O dourado virou **a cor da nebulosa**; botões acompanham o céu.
- Cartões cinza viraram **vidro fosco** legível.
- O **"Painel completo"** some quando o nativo tiver tudo.
- Dispositivos e Modos numa tela só.

### O que está no ar

| | |
| --- | --- |
| Nebula 1.28.0 | rota `/api/dupla/conversa` (só o que é novo; o snapshot inteiro dava 316 MB/h no 4G), chat sem avisos repetidos |
| APK no A71 | céu nativo com giroscópio, vidro, cor dinâmica, chat da Dupla nativo com símbolo por modelo, menu sanduíche, painel web sem abertura automática |
| Ponte do Gemini | 8767, token fixo no usuário; falta o Denis recarregar a extensão e colar o token |

### Pontos abertos que merecem atenção

- O menu sanduíche não abriu no único toque de teste, que coincidiu com o
  Denis usando outro app. Há logs `NebulaMenu`: `adb logcat -s NebulaMenu`.
- fps caiu de 25 para ~22 com o vidro.
- Compile o APK com `NEBULA_POWER_TOKEN` exportado do escopo de usuário: o
  Gradle lê do ambiente e os shells daqui não têm a variável.
- Nada commitado desde `313681b`; o ok de commit do Denis valia só para aquele.

Livre para o próximo item. Se quiser que eu assuma algo pelo próprio painel,
planeje a tarefa com `owner: "opus"` que eu reservo por lá.

## Rodada 6 — migração MCP: mídia (24/09)

Pedido do Denis: continuar a migração para MCP. Reserva desta seção:
`modules/desktop/media.py`, `modules/desktop/__init__.py`, `core/bootstrap.py`,
`core/legacy_actions.py`, `main.py` (só os métodos de mídia),
`tests/test_modular_tools.py`, `tests/test_tool_flow.py`, `modules/README.md`.
Não toquei em `services/collaboration/`, `colaboracao_ferramentas.py`,
`nebula_front/` nem nos testes da Dupla (reserva de rolagem do Codex).

As quatro tools de mídia agora são chamadas direto, sem frase legada, e
aparecem no servidor MCP pelo mesmo `Registry`. Suíte completa: 524 OK.
Restam no adaptador legado: abajur (tools simples), `capturar_tela`,
`salvar_clipe`, `identificar_musica`, `ver_horas`, `abrir_emails`, `desligar_pc`.

## Rodada 7 — o falso "a Nebula reiniciou" (25/09 00:40 UTC)

Reserva: `tests/test_dupla_ferramentas.py` e `tests/test_dupla_rotas.py` (meus,
O-03 e O-11). Não toquei em `services/collaboration/`.

O aviso das 00:34:40 ("Conversa anterior foi encerrada porque a Nebula reiniciou
no meio da rodada") **não veio de reinício**: a resposta do Codex chegou 24 s
depois. Veio da suíte de testes. Dois testes meus chamavam
`remote_server.colaboracao()` sem trocar o projeto; `STATE` lê o projeto ativo de
`%LOCALAPPDATA%\Nebula\remote.json`, então abriam o store **real** e rodavam
`liberar_rodadas_orfas`, que encerra a conversa em andamento — e, no modo
Desenvolver, derruba a árvore do CLI. O autopilot do `ai_sprints` (no ar desde
21/09 23:47) roda `unittest discover -s tests` sozinho; com a suíte dele em
curso (iniciada 21:38:42 locais), o `.gitignore` do store real foi reescrito às
21:38:51, no meio desta rodada. A minha primeira execução dos testes, antes da
correção, também abriu o store real uma vez.

Provado pelo `mtime` de `.nebula-collaboration/.gitignore`: mudava a cada
execução dos dois testes. Corrigido com projeto temporário; suíte da raiz com
564 OK e o store real intacto antes e depois.

Revisão da correção do Codex no `store.py` (repetir o `os.replace`): aprovada,
10/10 testes. A causa do `WinError 5` não foi provada — os exportadores já se
serializam pela trava do SQLite, então sobra leitor externo (antivírus,
editor). Sugestões do lado dele: `/api/collaboration/log` ainda propaga o erro
depois de 5 tentativas, e o diário inteiro (456 KB) é reescrito a cada evento,
inclusive `tool_activity`.

Pendente, fora do meu alcance nesta rodada: publicar o hub no notebook
(publicação é proibida para a Dupla); até lá o notebook roda o terminal antigo,
sem política. O `NebulaPowerServer.exe` local (PID 56372, 23/09 06:18) está vivo
mas não escuta porta nenhuma — é ele que trava a cópia do exe.

## Regras do Denis para o celular (valem para as duas)

- **Toda aba ou seção nova entra no menu sanduíche (☰)** do `MobileDashboard`:
  item em `montarMenu()` (`itens`, `secaoMenu`, `titulosMenu`), ícone vetorial
  novo em `Icone.java` e o caso em `select()`. Nada de barra inferior. Ele
  testou o ☰ em 24/09 e aprovou.
- Interface **nativa**, nunca web; cor de destaque vem da nebulosa (`Tema`);
  cartões são vidro (`Tema.vidro`).
