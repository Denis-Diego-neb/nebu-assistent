# Painel de colaboração — contrato com o frontend (Codex → Opus)

## Desenvolvimento pelo telefone — 1.28.1

O botão Enviar usa `POST /api/collaboration/develop` com
`{text, idea_id?, token_budget?}`. Ele cria ou retoma duas sessões próprias no
projeto selecionado em Projetos: Codex implementa, Claude revisa, testa e corrige.
Os CLIs podem ler/editar os arquivos e executar comandos. Uma pergunta continua
sendo uma pergunta; um pedido de mudança é executado. O transporte não injeta
texto nas conversas já abertas no VS Code.

Os IDs das sessões ficam em `development_sessions` por pedido/agente no SQLite.
`active_chat.mode=development` identifica a rodada; `agent_update` e
`tool_activity` mostram progresso, comandos e resultados reais, sem eventos de
raciocínio. `POST /api/collaboration/stop` interrompe o processo e descendentes;
alterações já feitas permanecem. Pausar impede o próximo agente, sem matar o
comando atual. CLI com erro aparece no chat e permite ao outro continuar.

As duas sessões trabalham sequencialmente e a rodada bloqueia outra rodada de
escrita da Dupla no mesmo projeto. Reservas antigas running/interrupted precisam
ser resolvidas antes do desenvolvimento. Editores externos continuam livres:
os agentes recebem instrução de preservar mudanças existentes. O modo direto
não tem a revisão antes da escrita do coordenador legado: Claude revisa o que
Codex realmente escreveu. Codex usa workspace-write; Claude usa ferramentas
nomeadas e permissões acceptEdits/allowedTools, sem bypass de permissões.

O caminho `project_root` e a disponibilidade `development_available` são
expostos no snapshot. É exigida raiz Git e o armazenamento é separado por
projeto. As rotas `/run` e `/chat` antigas permanecem para compatibilidade; os
controles novos usam `/develop`.

Codex implementa esta pasta; Opus integra o painel e `remote_server.py`.
Não editar esta pasta simultaneamente. A integração importa:

```python
from services.collaboration.api import CollaborationAPI
api = CollaborationAPI(project_root)  # uma instância por projeto
status, payload = api.handle(method, path, body)
```

As rotas abaixo devem ficar atrás da autenticação já existente da Nebula.
`handle` não abre porta, não altera autenticação nem depende de GUI.

- `GET /api/collaboration`: snapshot com `ideas`, `tasks`, `messages`,
  `confirmations`, `budgets`, `providers`, `running`, `log_path`.
- `POST /api/collaboration/ideas` com `{text, token_budget?}`: cria pedido.
- `POST /api/collaboration/run` com `{idea_id}`: inicia planejamento e execução
  em background pelos dois CLIs; retorna 202. Uma execução por projeto.
- `POST /api/collaboration/pause` com `{paused: true|false}`: pausa entre etapas.
- `POST /api/collaboration/messages` com `{idea_id, text}`: usuário orienta o
  pedido. Mensagens de agente só entram pelo backend/CLI autenticado local.
- `POST /api/collaboration/chat` com `{idea_id?, text}`: inicia uma rodada de
  conversa com respostas de ambos os CLIs, sem planejar ou aplicar código.
  Sem `idea_id`, abre um pedido. Retorna 202; acompanhe `active_chat` e eventos
  `chat_reply` / `chat_error` no snapshot. Falha de um agente não impede o outro.
  O histórico e o consumo pertencem ao pedido, incluindo mensagens posteriores.
- `GET /api/collaboration/log`: retorna `{markdown}`; renderizar como texto
  escapado ou Markdown sanitizado, nunca como HTML cru.

No chat principal exibir mensagens do usuário, `chat_reply`, `chat_error` e
`confirmations`. Respostas incluem modelo e sessão reais do transporte.
Na aba de coordenação exibir decisões operacionais, tarefas, bloqueios, reservas,
evidências e consumo. Não registrar raciocínio privado das IAs.

As sessões do painel são execuções dedicadas via Codex CLI / Claude Code CLI;
não se deve anunciar controle sobre chats já abertos no VS Code. A origem e o
modelo retornados pelo CLI acompanham cada confirmação. Uso não reportado é
`null`, nunca zero inventado. Orçamentos bloqueiam novas rodadas: não constituem
limite exato de tokens dentro de uma chamada já iniciada.

O estado transacional fica em SQLite em `.nebula-collaboration/`. O Markdown
é uma projeção dos eventos: ambos os agentes enviam seções ao serviço, que
serializa a escrita, evitando duas gravações concorrentes no mesmo `.md`.

Prioridade: `(impacto*3 + urgência*2 + redução_de_risco*2) * confiança / custo`.
As notas ficam visíveis e podem ser revistas entre etapas com justificativa.
Bloqueios de caminhos são normalizados (inclusive maiúsculas/minúsculas) e
pastas conflitam com seus descendentes. Interrupção não libera uma reserva de
trabalho automaticamente: ela precisa de conclusão ou liberação explícita.

## Participar a partir das sessões atuais do VS Code

O painel e os dois editores compartilham o mesmo armazenamento. Uma sessão
existente pode registrar sua própria participação sem criar outro agente:

```powershell
.\.venv\Scripts\python.exe -m services.collaboration snapshot
.\.venv\Scripts\python.exe -m services.collaboration claim --agent opus --id TASK_ID
.\.venv\Scripts\python.exe -m services.collaboration message --agent opus --id IDEA_ID --text "API pronta para integrar."
.\.venv\Scripts\python.exe -m services.collaboration finish --agent opus --id TASK_ID --text "Painel integrado." --evidence "Testes das rotas passaram."
```

As chamadas são operações locais com a identidade declarada pela própria sessão.
Não representam assinatura criptográfica do provedor. A API do navegador só
aceita mensagens do usuário; não permite escolher autor ou forjar confirmação.

`Executar` inicia sessões dedicadas dos CLIs. A primeira versão aceita até seis
seções de arquivos de texto por rodada; ambas as IAs planejam, o responsável
propõe e a outra revisa antes da aplicação. Hashes de origem e reservas protegem
os arquivos. Essas reservas protegem operações que aderem ao serviço; editores
externos não são bloqueados no sistema operacional. Mudanças externas detectadas
durante a geração interrompem a seção. Originais ficam em `backups/`.

São verificadas a sintaxe Python e a validade JSON. Testes funcionais, execução
arbitrária de comandos, instalação e deploy não são automáticos nesta etapa.
O diário informa essa limitação em cada seção. Pausar vale entre etapas; após a
rodada parar, use Retomar e Executar para continuar. Uma queda inesperada mantém
a reserva visível em vez de permitir outra execução sobre o processo anterior.

Documentação dos transportes: [Codex não interativo](https://developers.openai.com/codex/noninteractive/)
e [Claude Code programático](https://code.claude.com/docs/en/headless).
