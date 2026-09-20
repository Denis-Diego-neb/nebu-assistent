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
O resultado aprovado fica em `ai_sprints/autopilot_runs/<id>/` para revisao
humana. O processo nao faz commit, merge nem push.

Comandos:

```powershell
python ai_sprints/autopilot.py --watch
python ai_sprints/autopilot.py --pause
python ai_sprints/autopilot.py --resume
python ai_sprints/autopilot.py --stop
python ai_sprints/autopilot.py --status
```
