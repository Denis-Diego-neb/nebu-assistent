# Claude (sessão na nuvem) — release 1.28.2

## Mensagem ao Terra — 09/10

O Denis pediu que eu ajude você a atualizar os apps e o APK. Estou numa sessão
na nuvem: não alcanço o PC, o A71 nem o notebook. Por isso **não compilei, não
instalei e não publiquei nada**. Deixei o código pronto no branch
`ccr-b43604ed-9vvu8j`, a partir do `main` de 25/09 (`e565406`):

| commit | o que muda |
| --- | --- |
| `daa56cf` | Ar pelo Smart IR por voz e texto (`modules/iot/air.py`). "Desligue o ar" não abre mais a confirmação de desligar o PC, e "não desligue" passou a cancelar essa confirmação (antes confirmava, porque contém "desligue"). A Coolix liga mesmo com 16 °C salvo pelo protocolo Voltas. O painel do desktop respeita `temperature_min`. |
| `6531426` | `VERSAO_NEBULA` 1.28.1 → 1.28.2, este arquivo e o README. |
| `6d8ed91` | Merge de `claude/wizardly-fermi-yi6i0u` (worker MCP do notebook, 25/09), a pedido do Denis. Só acrescenta arquivos; veja a seção própria abaixo. |
| `59e7192` | Ollama do notebook fechado para a rede, a pedido do Denis; veja a seção própria abaixo. |
| `27207d3` | Timer do ar a partir de 1 minuto (hub, APK e voz), a pedido do Denis; veja a seção própria abaixo. |
| `4af0716` | Modo chuva para dormir (hub, PC e APK), a pedido do Denis; veja a seção própria abaixo. |
| seguinte | Brave como navegador das telas e lanterna do celular no relâmpago com a tela apagada. |

Arquivos tocados: `main.py` (só `_executar_comando_ar`, a checagem em
`executar`, a chamada antes do abajur e a ordem da confirmação de desligar o
PC), `gui.py` (painel do ar), `ar_ir_direto.py` (`executar`), `versao.py`,
`README.md`, `modules/README.md` e testes (`tests/test_air.py`,
`test_main_ar.py`, `test_ar_ir_direto.py`). O merge do worker só cria
`nebula_worker/`, `core/mcp/`, `core/jobs/`, `core/capabilities/`,
`docs/MCP_GOAL.md`, `scripts/notebook_worker_*.py`, `tests/test_worker_*.py`
e uma seção no `ARQUITETURA.md`. Em `android/`: o passo do timer e a seção
Modo chuva em `MobileDashboard.java`, `ChuvaService.java`, `Trovao.java`, o
ícone em `Icone.java` e permissões novas no manifest. Em `nebula_front/`, só o
arquivo novo `chuva.html`. Nada em `services/collaboration/` ou `ai_sprints/`.

Validação aqui, no Linux com os módulos do Windows simulados: 730 testes
(65 do worker, todos passando), 4 falhas. São as mesmas de antes da mudança e dependem do comportamento do
Windows (`test_hub_terminal` ×2, `test_telemetry_udp`, `test_transfer_chat`).
No PC a suíte precisa passar inteira: o `build_release.ps1` para no primeiro
teste vermelho.

## Passo a passo sugerido

1. Confirme com o Denis que não há rodada ativa da Dupla nem do watcher: o
   `-StartDesktop` reinicia a Nebula.
2. Traga o branch sem perder trabalho local:

   ```powershell
   git status
   git fetch origin ccr-b43604ed-9vvu8j
   git merge --no-ff origin/ccr-b43604ed-9vvu8j
   ```

   Se houver alterações locais não commitadas em `main.py`, `gui.py`,
   `ar_ir_direto.py`, `versao.py` ou `README.md`, combine com o Denis antes do
   merge. Se o `versao.py` local já estiver em 1.28.2 ou acima, use um número
   maior que o instalado: o deploy do hub espera o `/health` responder a versão
   nova.
3. Exporte o token do escopo do usuário neste shell. O Gradle embute o token no
   APK, e o `deploy_notebook.ps1` aborta sem ele — e o deploy só roda depois de
   o EXE e o APK já estarem compilados:

   ```powershell
   $env:NEBULA_POWER_TOKEN = [Environment]::GetEnvironmentVariable('NEBULA_POWER_TOKEN', 'User')
   ```

4. Deixe o A71 em `adb devices` como `device` (não `unauthorized`) e rode:

   ```powershell
   .\build_release.ps1 -InstallAndroid -StartDesktop
   ```

   O deploy do hub usa `http://100.78.67.81:8766` (Tailscale). Se o Tailscale
   do PC estiver fora, o script só avisa (saída 3) e segue. Publique o hub
   depois pela LAN, no endereço em que ele responder:

   ```powershell
   .\deploy_notebook.ps1 -Server http://<ip-do-notebook>:8766 -Required
   ```

   Se a cópia do `NebulaPowerServer.exe` falhar por arquivo em uso, procure o
   processo antigo parado (em 23/09 havia um vivo sem escutar porta).

## Conferência

- Título da janela do PC: `Nebula 1.28.2`.
- APK: `adb shell dumpsys package com.nebula.assistant | Select-String versionName`
  mostra `versionName=1.28.2`.
- Hub: `Invoke-RestMethod http://<hub>:8766/health -Headers @{'X-Nebula-Power-Token' = $env:NEBULA_POWER_TOKEN}`
  responde `version` 1.28.2.
- Ar, no PC: "liga o ar", "coloca o ar em 22", "como está o ar?". "Desliga o ar"
  não pode perguntar se é para desligar o computador. Se o Smart IR não
  responder, o motivo aparece na fala e no status do painel do ar.

## Ollama do notebook fechado para a rede

A API do Ollama não tem senha, e o notebook a deixava em `0.0.0.0:11434` sem
regra de firewall: qualquer aparelho da LAN ou do tailnet podia usar, baixar ou
apagar modelos. Agora:

- `notebook_power_server/proteger_ollama.ps1` (+ `PROTEGER-OLLAMA.cmd`) bloqueia
  a porta 11434 para todos, menos os IPs do PC (`192.168.15.12` e
  `100.92.82.41`, ou `NEBULA_OLLAMA_CLIENTS`). O bloqueio vence a permissão que
  o Windows cria para o `ollama.exe`. O instalador chama esse script, e o
  `build_release.ps1` põe os dois arquivos no zip do notebook.
- `iniciar_servicos_notebook.ps1` só usa `OLLAMA_HOST=0.0.0.0` com essa regra
  ativa; sem ela, `127.0.0.1`.
- O revisor das sprints continua chegando ao notebook pelo PC. A troca dele
  para o worker MCP fica com o dono de `ai_sprints/autopilot.py`; depois dela,
  `proteger_ollama.ps1 -Clientes ""` fecha a porta de vez.

**Precisa de uma ação no notebook:** a atualização automática do hub troca só
o executável e não roda o instalador. Abra `PROTEGER-OLLAMA.cmd` no notebook
uma vez e confirme o UAC; pela sessão SSH de administrador também funciona:
`powershell -ExecutionPolicy Bypass -File proteger_ollama.ps1`. Confira se o PC
ainda está em `192.168.15.12`: com outro IP, o revisor para de alcançar o
Ollama até a regra ser refeita.

## Timer do ar a partir de 1 minuto

O Denis pediu para desligar o ar em 10 minutos, e o hub só aceitava múltiplos
de 30. Agora:

- `notebook_power_server/air_timer.py` aceita qualquer minuto de 1 a 1440.
- No APK, + e − do timer andam de 10 em 10 minutos até 1 hora e de 30 em 30
  depois (mínimo 10). Compilei os fontes Java aqui com `javac` contra o
  `android.jar` da API 35 e um `BuildConfig` simulado; o Gradle de verdade
  continua com você.
- Pela Nebula: "desliga o ar em 10 minutos", "em meia hora", "daqui a 1h30" e
  "cancela o timer do ar" vão ao `POST /control` do hub (`air.timer`), com
  `NEBULA_POWER_TOKEN` e os endereços de `pc_start_agent.NOTEBOOK_ENDPOINTS`.

O timer de 10 minutos só funciona depois que o hub novo estiver no notebook
(`deploy_notebook.ps1`) e o APK novo no A71. Na conferência, programe 10
minutos pelo app e veja o cartão do ar mostrar "Desligamento agendado".

## Modo chuva para dormir

O Denis pediu um modo para dormir com chuva. O hub coordena tudo:

- **Hub** (`notebook_power_server/coordenador_chuva.py`, rotas em `power_server.py`):
  `chuva.iniciar` / `chuva.parar` em `POST /control`, estado em `GET /chuva`
  (rota direta: `/control` consulta o PC antes de responder e estragaria a medida
  de relógio do celular). A sessão tem instante zero, semente dos trovões e uma
  chave que abre só `/hub/chuva.html` e `/hub/chuva/estado` enquanto o modo dura.
  O hub abre a página em tela cheia no notebook, toca o trovão (`winsound`),
  pisca o abajur (`ControleAbajurTuya.relampago`), alterna o ar a cada hora e
  retoma a sessão se reiniciar na mesma noite.
- **Telas** (`nebula_front/chuva.html`): YouTube em loop, posição calculada pelo
  relógio do hub, realinha acima de 1,2 s. Abre com `front_window.abrir_midia`
  (Brave primeiro, perfil próprio com reprodução automática liberada, `--kiosk`)
  e `TelaChuva` segura a máquina acordada. O Denis pediu o Brave: o
  `encontrar_navegador` agora o prefere em tudo, inclusive no console do hub.
- **PC** (`main.py`): recebe `chuva.iniciar` do hub com a URL (só aceita a página
  do hub em IP não público), passa para o modo manual, abre o vídeo e põe o
  Attack Shark em Ambilight (`AttackSharkX98HE.enviar_rgb`). Voz: "ative/pare o
  modo chuva".
- **Celular**: seção ☰ Modo chuva e `ChuvaService` em primeiro plano
  (`mediaPlayback`), que toca o trovão sintetizado (`Trovao.java`, mesma receita
  do Python) no instante do hub, pisca a lanterna no relâmpago só com a tela
  apagada (`setTorchMode`, sem permissão de câmera) e manda `chuva.parar` quando
  o celular é desbloqueado (`USER_PRESENT`).

Validado aqui: testes do coordenador, das rotas e do PC; a página rodou no
Chromium headless com hub e YouTube simulados (`node --test
tests/test_chuva_pagina.cjs`, precisa do Playwright): duas telas a 0,01 s, com
o relógio do hub 5 s adiantado. O Java compila com `javac` contra o
`android.jar` 35. **Não testado em hardware**: som, abajur, teclado, YouTube de
verdade e o serviço no A71. Na conferência, comece o modo pelo celular e
confira: as duas telas com o mesmo vídeo, o abajur apagando, um trovão em até
2,5 minutos (relâmpago no abajur e som no notebook e no celular) e o fim do modo
ao desbloquear o celular.

## Worker MCP do notebook

- Entrou no branch, mas **não muda o EXE, o APK nem o hub**: nenhum código dos
  apps o importa, e o `build_release.ps1` não o compila nem instala. O que muda
  no build é a suíte: os 65 testes `tests/test_worker_*` rodam junto e dependem
  de `mcp` e `cryptography`, que já estão no `requirements.txt` principal.
- Instalar no notebook é um passo separado, com chave de assinatura, um
  `NEBULA_WORKER_TOKEN` próprio, `worker.json` e UAC
  (`nebula_worker/README.md`). Faça só se o Denis pedir.
- Foi escrito por outra sessão Claude; aqui só rodei os testes, sem revisão
  linha a linha.

## Fora deste release

- Não abri PR nem mexi em `main`. Não faça push para `main` sem o ok do Denis.
