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

Arquivos tocados: `main.py` (só `_executar_comando_ar`, a checagem em
`executar`, a chamada antes do abajur e a ordem da confirmação de desligar o
PC), `gui.py` (painel do ar), `ar_ir_direto.py` (`executar`), `versao.py`,
`README.md`, `modules/README.md` e testes (`tests/test_air.py`,
`test_main_ar.py`, `test_ar_ir_direto.py`). O merge do worker só cria
`nebula_worker/`, `core/mcp/`, `core/jobs/`, `core/capabilities/`,
`docs/MCP_GOAL.md`, `scripts/notebook_worker_*.py`, `tests/test_worker_*.py`
e uma seção no `ARQUITETURA.md`. Nada em `android/`,
`services/collaboration/`, `nebula_front/` ou `ai_sprints/`.

Validação aqui, no Linux com os módulos do Windows simulados: 691 testes
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
