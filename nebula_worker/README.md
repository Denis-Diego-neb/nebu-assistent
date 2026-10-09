# Worker MCP do notebook

Primeiro marco do [MCP_GOAL](../docs/MCP_GOAL.md) (seções 24 e 32). O PC principal
monta um `JobEnvelope`, assina um ticket de capacidade e envia. O notebook valida,
entrega **só aquele prompt** ao Qwen Edge (Ollama local) e devolve um `JobResult`
tipado. O PC confere a correlação `job_id` + `trace_id`.

```
PC principal                                   Notebook
core/mcp/clients/notebook_worker.py  ──MCP──►  gateway/guard.py   (rede, taxa, token)
core/capabilities/ticket.py (assina)           gateway/tools.py   (6 tools, nada mais)
core/jobs/*  ─┐                                worker/dispatcher.py (fila, prazo, cancelamento)
              └── nebula_worker/protocol ◄──── capabilities/validator.py (ticket)
                  (contrato único dos dois)    models/ollama_client.py ──► Ollama 127.0.0.1
```

## O que o worker faz e o que ele não faz

| Faz | Não faz |
| --- | --- |
| `worker.health`, `worker.capabilities`, `worker.submit`, `worker.status`, `worker.result`, `worker.cancel` | shell, `python(code)`, leitura/escrita remota de arquivos |
| Operação única `model:qwen_edge:generate` | IoT, navegador, ferramentas da Nebula |
| Um job por vez, fila limitada, prazo, cancelamento | orquestrar, escolher o próximo passo, conhecer o objetivo global |
| Auditoria só de metadados | guardar prompt ou resposta em disco |

O catálogo é fixo em `gateway/tools.py`. Um teste falha se alguém acrescentar outra tool.

## Segurança, em camadas

1. **Rede.** `bind_host` precisa ser um IP explícito de loopback, LAN privada ou
   Tailscale (`100.64.0.0/10`); `0.0.0.0` e IP público são recusados. O instalador
   abre o firewall só para os IPs de `allowed_clients`, e o worker confere de novo.
2. **Transporte.** Exige `Authorization: Bearer <NEBULA_WORKER_TOKEN>`, um token
   separado do `NEBULA_POWER_TOKEN`, com no mínimo 32 caracteres. Há limite de taxa por cliente. Host e Origin são
   validados (bloqueia DNS rebinding e navegador), o Content-Type precisa ser JSON e o corpo tem tamanho limitado.
3. **Autorização por job.** Cada envelope traz um ticket Ed25519 assinado pelo PC.
   A chave privada fica só no PC, e o notebook guarda apenas a pública. O ticket:
   - vale para um único `job_id`;
   - carrega o hash do envelope, então o prompt não pode ser trocado no caminho;
   - expira em minutos e só pode ser usado uma vez; a lista de tickets usados sobrevive a reinícios;
   - tem escopo mínimo e nunca aceita curinga.
4. **Privacidade (INV-007).** A auditoria aceita uma lista fechada de campos, e
   prompt ou resposta não cabem nela. O prompt é apagado da memória ao fim do job. Os resultados
   ficam só em memória e expiram em 15 minutos. Cada job ganha uma pasta de rascunho,
   apagada depois.
5. **Execução.** O prazo conta desde o aceite. O cancelamento fecha o socket com o Ollama,
   que para de gerar. Uma saída JSON cortada pelo limite de tokens vira `OUTPUT_TRUNCATED`,
   nunca "quase sucesso". O `usage` traz tokens e `stop_reason`.

**Use o IP do Tailscale** em `bind_host`: o tráfego vai cifrado pelo WireGuard. Pela
LAN o HTTP é texto puro. Nesse caso, configure `tls_certfile`/`tls_keyfile`.

## Instalação

### No PC (uma vez)

```powershell
# 1. Chave de assinatura (fica em %LOCALAPPDATA%\Nebula\notebook_worker) e token novo
.\.venv\Scripts\python.exe -m scripts.notebook_worker_keys --token
setx NEBULA_WORKER_TOKEN "<token impresso acima>"
setx NEBULA_NOTEBOOK_WORKER_URL "http://100.78.67.81:8790/mcp"

# 2. Testes + executável (gera nebula_worker\NebulaWorker.exe)
powershell -ExecutionPolicy Bypass -File nebula_worker\build_worker.ps1
```

Copie `worker.example.json` para `worker.json` e ajuste:
- `trusted_keys`: o trecho impresso pelo passo 1;
- `bind_host`: o IP Tailscale do notebook;
- `allowed_clients`: os IPs do PC;
- `models.qwen_edge.model`: o modelo instalado no Ollama.

### No notebook

1. Coloque numa mesma pasta: `NebulaWorker.exe`, `worker.json`, `instalar_worker.ps1`,
   `iniciar_worker.ps1` e `INSTALAR-WORKER.cmd`.
2. Defina o **mesmo** token: `setx NEBULA_WORKER_TOKEN "<token>"` e abra um terminal novo.
3. Rode `INSTALAR-WORKER.cmd` e confirme o UAC. O instalador:
   - valida a configuração e o Ollama (`--check`);
   - abre o firewall só para o PC;
   - registra a tarefa **Nebula MCP Worker** no logon, com um lançador que reabre o worker se ele cair;
   - confirma que a porta está escutando.

### Validar, do PC

```powershell
.\.venv\Scripts\python.exe -m scripts.notebook_worker_demo
```

Executa os seis passos da seção 32. Depois, confira no notebook que
`%LOCALAPPDATA%\NebulaWorker\runtime\audit\worker.jsonl` não contém o prompt.

Diagnóstico no notebook: `NebulaWorker.exe --config worker.json --check`, e o log de
serviço em `%LOCALAPPDATA%\NebulaWorker\runtime\logs\worker.log` (sem payloads).

## Uso no código do PC

```python
from core.mcp.clients.notebook_worker import NotebookWorkerClient
from core.jobs.envelope import build_generate_envelope

client = NotebookWorkerClient.from_env()          # URL, token e chave do PC
result = client.run_sync(build_generate_envelope(
    "Classifique: ...", output_format="json", schema={...}, temperature=0,
))                                                # JobResult validado e correlacionado
```

`NotebookWorkerChat` oferece a mesma interface `chat()`/`is_alive()` do `OllamaClient`
das sprints. Falha de transporte vira `requests.ConnectionError`, então o circuit
breaker do autopilot continua funcionando igual.

## Desvios declarados em relação ao GOAL (seção 31, item 12)

1. **Contrato único.** Está em `nebula_worker/protocol/`, e os módulos `core/jobs/*` do PC apenas
   o reexportam. Não existe um `protocol/` separado na raiz, para evitar duas cópias divergentes.
2. **`gateway/` em vez de `mcp/`** dentro do worker: uma pasta local chamada `mcp` poderia
   esconder o SDK oficial ao executar o worker direto da pasta.
3. **JSON em vez de YAML**, para não acrescentar dependência ao executável.
4. **Ticket estendido** (seções 11 e 13): ganhou `key_id`, `job_id`, `issued_at`, `envelope_sha256` e `signature`.
   Sem esses campos, o notebook teria de confiar na rede.
5. **Envelope com campos opcionais** `input.system`, `output.schema` e `generation`
   (`temperature`, `seed`, `context_tokens`, `think`), necessários ao revisor das sprints.
   Hardware (`num_gpu`, `num_thread`) continua decisão da configuração do notebook.
6. **`usage.stop_reason`** a mais, para distinguir resposta completa de resposta cortada.
7. **Rejeições não entram no registro de jobs**: voltam como `status: rejected` + `error`.
   Existe também a transição `queued → failed` (`DEADLINE_EXCEEDED`).
8. **Resultados só em memória**: reiniciar o worker os perde (`JOB_NOT_FOUND`), de propósito (INV-007).
9. **Sem modo de log de prompt para depuração.** O GOAL permite esse modo atrás de uma flag, mas ele não foi implementado.

## Pendências fora deste marco

- **Autopilot fala direto com o Ollama.** O revisor das sprints ainda acessa
  `http://192.168.15.4:11434` (seção 19). A troca é só construir o `reviewer` em
  `ai_sprints/autopilot.py` com `NotebookWorkerChat(NotebookWorkerClient.from_env(), think=...)`.
  Não foi feita agora porque o watcher estava rodando e outro agente editava esse arquivo.
- **Ollama exposto na rede.** Depois da troca acima, o Ollama do notebook deve escutar só em `127.0.0.1`.
  Hoje `notebook_power_server/iniciar_servicos_notebook.ps1` usa `OLLAMA_HOST=0.0.0.0:11434`,
  e a API do Ollama não tem autenticação: qualquer aparelho da LAN pode usar, baixar ou apagar modelos.
- **Terminal do hub.** `/hub/terminal` é um shell remoto no notebook (INV-003) e deve continuar desligado
  (`terminal_policy.json` ausente).
- **Sentido invertido das zonas de confiança.** `scripts/mcp_ssh_console.py` e o botão do hub deixam o *notebook*
  com acesso SSH ao PC, invertendo as zonas de confiança. O certo é remover a chave do notebook ou
  restringi-la no `authorized_keys` com `restrict,command=...`.
- **Reparo silencioso de patches.** O `normalize_hunk_counts` e o `_codex_repair_patch` do autopilot reparam patches do modelo
  em silêncio, o que a seção 19.1 pede para não fazer.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_worker_protocol tests.test_worker_tickets `
    tests.test_worker_dispatcher tests.test_worker_ollama tests.test_worker_config tests.test_worker_gateway
```

São 65 testes, sem modelo real e sem rede além do loopback. Um deles sobe o worker
completo por HTTP e roda a demo da seção 32 contra um Ollama falso.
