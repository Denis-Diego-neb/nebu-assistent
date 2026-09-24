# Fila segura dos agentes locais

O `autopilot.py` processa somente arquivos `*.json` desta pasta. Cada job aponta
para um manifesto de evidencias, lista exatamente os arquivos que o worker pode
alterar e define comandos de teste fixos. Os modelos nunca fornecem comandos de
shell.

Exemplo de job (salve sem o prefixo `_` para enfileirar):

```json
{
  "id": "sprint_03_exemplo",
  "candidate": "ai_sprints/candidates/sprint_03_exemplo.json",
  "allowed_paths": [
    "modules/exemplo.py",
    "core/bootstrap.py",
    "tests/test_exemplo.py"
  ],
  "tests": [
    ["{python}", "-m", "unittest", "tests.test_exemplo"],
    ["{python}", "-m", "unittest", "discover"]
  ],
  "timeout_seconds": 300
}
```

O fluxo usa um Git worktree descartavel fora do repositorio. Antes e depois do
patch, executa os testes do manifesto. O reviewer 9B avalia o patch e os testes.
O reviewer 9B usa temperatura zero e uma resposta JSON validada. Ele faz a
triagem local rapida; o Gemini executa a revisao profunda. Para ativar thinking
local em uma maquina mais rapida, defina `NEBULA_SPRINT_REVIEWER_THINK=1`. Se o
patch terminar os testes (mesmo com parecer Qwen negativo), o autopilot cria um pedido em
`ai_sprints/gemini_queue/` e entra em `waiting_gemini`. O patch so fica pronto
para revisao humana depois que a resposta do Gemini Web tambem for aprovada.
O processo nao faz commit, merge nem push.

Comandos:

```powershell
python ai_sprints/autopilot.py --watch
python ai_sprints/autopilot.py --pause
python ai_sprints/autopilot.py --resume
python ai_sprints/autopilot.py --stop
python ai_sprints/autopilot.py --status
python ai_sprints/gemini_bridge.py --list
python ai_sprints/gemini_bridge.py --show sprint_03_exemplo
python ai_sprints/gemini_bridge.py --record sprint_03_exemplo --response-file resposta.json
python ai_sprints/scoreboard.py --status
```

O login e os cookies permanecem no navegador. A ponte exporta apenas objetivo,
diff, resultado dos testes e revisao do Qwen; conteudo com padrao de credencial
e bloqueado. Sem resposta valida do Gemini, a sprint permanece pausada no gate.

Enquanto a 1660 Super estiver instavel, o worker 4B usa CPU por padrao
(`num_gpu=0`). Depois da troca da placa, defina
`NEBULA_SPRINT_WORKER_NUM_GPU=auto` para devolver a selecao de GPU ao Ollama.

Se uma Qwen ficar offline, exceder o timeout ou devolver saida corrompida, o
autopilot abre um circuit breaker de 30 minutos e usa o Codex app-server local
com `gpt-5.6-terra` e reasoning `low`. O app-server e iniciado sob demanda no
loopback. Cada resposta reserva fica vinculada ao fingerprint e e reutilizada,
evitando outra chamada na repeticao do watcher. Quando o reviewer 9B cai, o
patch continua apenas no worktree descartavel, roda os testes fixos e recebe uma
revisao Terra antes de chegar ao gate Gemini. Configuracao:

```powershell
$env:NEBULA_CODEX_FALLBACK = "1"
$env:NEBULA_CODEX_FALLBACK_MODEL = "gpt-5.6-terra"
$env:NEBULA_CODEX_FALLBACK_EFFORT = "low"
$env:NEBULA_QWEN_CIRCUIT_SECONDS = "1800"
```

O placar registra os deltas `worker_4b` e `reviewer_9b` apenas depois de uma
resposta Gemini valida, vinculada ao hash da sprint. Ele e idempotente:
reprocessar o mesmo job nao soma pontos novamente. O ranking mede qualidade e
nunca altera a aprovacao de um patch.

### Retomada e acompanhamento (21/09/2026)

O parecer Qwen e consultivo. Patches rejeitados localmente e falhas de patch/teste
tambem chegam ao Gemini, com os motivos e evidencias. Falha de teste ou validacao
nao pode virar patch aprovado, mesmo que Gemini devolva approved. Todo resultado
Gemini valido recebe deltas e justificativas no placar, inclusive revise.
O placar mede os papeis worker/reviewer; o prompt informa a origem quando conhecida.

Para recuperar a rodada antiga: pare o watcher, execute `--requeue-saved` e
reinicie `--watch`. O historico fica em `before_gemini_recovery/`; os patches e
pareceres salvos sao reutilizados, sem novas geracoes. Nao reabre resultados ja
avaliados pelo Gemini. A ponte Web 0.3 oferece envio e registro automaticos em
aba exclusiva, apos ativacao no popup; o modo manual continua disponivel.
`waiting_gemini` significa espera, nao atividade de inferencia nem nota zero.

No Xeon de 14 nucleos, a inferencia local usa ate 14 threads em CPU. Children of
Morta usa ate 8 e intervalo de 60s; Rocket League usa ate 4 e intervalo de 300s.
BeamNG pausa novas tarefas: a chamada local em andamento termina com afinidade
de 2 threads logicas e prioridade reduzida. Ao fechar o jogo a afinidade original
e restaurada. A contagem de threads do Ollama muda na proxima chamada; a afinidade
dos runners locais e ajustada a cada 3s, inclusive nas chamadas em andamento.
Essa afinidade afeta runners Ollama locais compartilhados; o notebook nao e limitado.

O monitor do Home Hub recebe um resumo a cada 15s quando `NEBULA_SPRINT_HUB_URL`
e `NEBULA_POWER_TOKEN` estao configurados no processo do watcher. Mostra notas,
motivos, espera por Gemini e falta de heartbeat por mais de 60s. Os botoes de
pausa/retomada sao confirmados pelo PC no heartbeat seguinte; nao interrompem
uma chamada ja em andamento. Credenciais nunca entram no resumo.
