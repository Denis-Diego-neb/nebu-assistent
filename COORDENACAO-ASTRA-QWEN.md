# Diagnóstico Qwen / sprints — 2026-09-24

Responsável: Astra (subagente de diagnóstico Qwen).

Reserva: análise de `ai_sprints/` e `core/agents/`, com correções focadas e testes relacionados se necessárias. A coordenação do Opus consultada libera o próximo item e não reserva essas pastas nesta rodada. Não editar `services/collaboration/`, `remote_server.py`, `nebula_front/` ou Android.

Objetivo: identificar por evidência por que as Qwen não progridem nos sprints. Nenhum treino massivo ou rodada indefinida será iniciado. Preservar alterações existentes.

## Resultado do diagnóstico

Leituras em 24/09/2026; nenhum modelo foi chamado e nenhum estado de execução foi alterado.

- Existem 41 jobs: 40 em `waiting_gemini` e 1 em `rejected`. Há somente 1 resposta em `ai_sprints/gemini_results/`. O watcher pula deliberadamente os 40 enquanto não existe resultado. Evidência: `autopilot.py`, loop `watch`, e os `autopilot_runs/*/state.json`.
- Dos 40 em espera, **38 não são elegíveis para aprovação**. Em 37 `tests.txt` o erro é `Contagem de linhas do hunk nao corresponde ao conteudo`; em 1, `Patch possui cabecalho de hunk invalido ou sem intervalos numericos`. Somente 2 têm testes passando (34 e 33 testes). A recuperação anterior enviou falhas também para avaliação; estar na fila Gemini não significa patch aprovado.
- O estado global está `paused: true`, atualizado em 22/09. O watcher continua vivo. A pausa impede novas gerações, mas o código continua aceitando resultados Gemini já recebidos; simplesmente retomar não libera os 40 jobs.
- Ollama worker padrão `127.0.0.1:11434/api/tags`: conexão recusada. Nenhum processo Ollama local foi encontrado. O reviewer do notebook `192.168.15.4:11434/api/tags` respondeu HTTP 200 e anunciou `qwen3.5:9b`.
- A ponte Gemini `127.0.0.1:8767/health` respondeu HTTP 200. Isso comprova a ponte local, não o funcionamento/login/automação da extensão no navegador. O `background.js` exige token, aba Gemini e automação ativada; qualquer erro desliga `state.auto`. O erro atual da extensão precisa ser lido no popup; não foi inferido dos arquivos.
- Os dois PIDs do watcher são pai/filho do launcher `.venv`, não dois watchers concorrentes. O mesmo vale para a ponte.
- O placar tem **uma avaliação**: -5 worker, -10 reviewer, referente ao primeiro job. A revisão Gemini registra patch truncado e problemas no parecer local. Não é uma série de notas repetidamente ruins.
- O circuito de fallback salvo registra limite de uso do Codex em 21/09; o prazo já venceu. Não é evidência de cota atual.

## Por que não melhora sozinho

Este pipeline não faz treino de pesos. Ele gera patches, executa testes e registra avaliações. Os estados `rejected`/`failed` com a mesma origem são terminais e o watcher os pula. Não há uma rodada automática que transforme a crítica Gemini em uma versão nova corrigida. O placar mede, mas não ensina o modelo por si só.

## Próximos passos seguros

1. Recuperar a automação Gemini pelo erro real no popup e processar uma avaliação controlada, preservando o vínculo de fingerprint. Não fabricar resultados nem remover o gate.
2. Recuperar o Ollama local antes de nova geração Qwen 4B. O 9B já responde à consulta de modelos.
3. Para a próxima rodada, implementar uma tentativa limitada de correção alimentada pelo erro local e parecer Gemini, com identidade de tentativa própria. Preferir saída de arquivos estruturados e geração do diff pelo Git, evitando exigir contagem manual de hunks do modelo pequeno.
4. Manter validação de patch, sintaxe e testes. Recontar hunks cegamente pode disfarçar resposta truncada e não é solução segura.

Nenhum código/runtime alterado nesta investigação. Reserva encerrada; o arquivo registra evidências e limitações, sem afirmar que os sprints voltaram a rodar.

## Reparo existente, origem e caso mínimo reproduzido

- Já há reparo: `_codex_repair_patch` solicita ao Terra correção de sintaxe, e `process` o chama após falha do validador para patch Terra ou falha de `git apply --check`. Existe cache `codex_worker_repair_*.json` em 11 runs. Se o patch reparado continua inválido, a validação falha; não há tentativas ilimitadas.
- **Todos os 41 runs têm cache `codex_worker_*.json`; só 1 tem `worker_response.json` Qwen.** Portanto não é correto atribuir os 37 hunks inválidos exclusivamente às Qwen. Os artefatos comprovam uso amplo da reserva Terra; a origem em muitos states antigos está `unknown`.
- A geração Qwen usa `num_predict=2800`; a repetição orientada pelo supervisor também usa 2800. O cliente só retorna `message.content` e descarta metadados de encerramento. Pode haver corte por limite, mas os arquivos salvos não permitem provar que o limite causou esses 37 erros.
- Caso concreto: `mcp_train_02_strict_arguments/candidate.patch` declara **42 linhas** no arquivo novo `modules/mcp_training_02.py`, mas contém **49 adições**; seu segundo arquivo declara e contém 40. Reproduzido chamando `validate_patch` com o manifesto verdadeiro pela `.venv/Scripts/python.exe`: mesma exceção de contagem. Esse caso é um diff com contagem errada, não prova de corte do final da resposta. O Git podia ignorar linhas além da contagem declarada; a validação estrita existente evita isso corretamente.
- Os dois candidatos com evidência de testes passando são `mcp_train_04_deterministic_list` e `mcp_train_09_lamp_on`. Uma avaliação Gemini controlada de um deles é o menor teste para validar a retomada da ponte, sem gerar novo patch, consumir Qwen ou fingir aprovação.
- Recomendações de código para próxima rodada: conservar metadados `done_reason`/contagem de tokens do Ollama; emitir erro explícito em corte de geração; trocar o contrato de arquivo novo por conteúdo estruturado e produzir o diff deterministamente. Não basta elevar tokens ou relaxar o validador.

Observação de ambiente: o Python global não importa `autopilot` por falta do pacote `mcp`; a `.venv` correta importa e reproduz o caso. O watcher em execução usa essa `.venv`.
