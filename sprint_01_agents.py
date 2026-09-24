from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


# ============================================================
# NEBULA — SPRINT 01
# Architecture learning / analysis loop
#
# SEGURANÇA:
# - Lê o projeto e o histórico Git.
# - NÃO altera main.py, modules/, core/ etc.
# - NÃO faz commit, merge ou push.
# - Só escreve em ai_sprints/sprint_01/
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

WORKER_HOST = "http://127.0.0.1:11434"
WORKER_MODEL = "qwen3.5:4b"

REVIEWER_HOST = "http://192.168.15.4:11434"
REVIEWER_MODEL = "qwen3.5:9b"

GOLDEN_FILE = "modules/iot/lights.py"

OUTPUT_DIR = PROJECT_ROOT / "ai_sprints" / "sprint_01"

DEFAULT_ROUNDS = 6
DEFAULT_SLEEP_SECONDS = 5
DEFAULT_NUM_CTX = 8192
DEFAULT_TEMPERATURE = 0.1
DEFAULT_KEEP_ALIVE = "30m"

MAX_DIFF_CHARS = 26000
MAX_TREE_CHARS = 14000
MAX_MAIN_SNIPPET_CHARS = 22000
MAX_PREVIOUS_CONSENSUS_CHARS = 12000
MAX_MODEL_RESPONSE_CHARS = 18000

SKIP_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "ai_sprints",
}

FOCUS_BY_ROUND = [
    "separação de responsabilidades e o padrão de delegação adotado pelo Codex",
    "dependências, imports, estado global, callbacks e acoplamentos ocultos",
    "organização de pastas, nomes e fronteiras entre módulos",
    "preservação de comportamento e compatibilidade com o código legado",
    "distinguir regras arquiteturais reutilizáveis de decisões específicas do abajur",
    "identificar candidatos seguros para futuras modularizações sem alterar nenhum arquivo",
    "detectar riscos de import circular, thread, estado compartilhado e efeitos colaterais",
    "consolidar um guia arquitetural curto, concreto e baseado apenas em evidências",
]


# ============================================================
# UTILIDADES
# ============================================================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def say(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def truncate(text: str, limit: int) -> str:
    if not text:
        return ""

    if len(text) <= limit:
        return text

    half = max(1, (limit - 120) // 2)

    return (
        text[:half]
        + "\n\n... [TRUNCADO PELO ORQUESTRADOR] ...\n\n"
        + text[-half:]
    )


def save_text(name: str, content: str) -> Path:
    ensure_output_dir()

    path = OUTPUT_DIR / name
    path.write_text(content, encoding="utf-8")

    return path


def append_jsonl(name: str, payload: dict[str, Any]) -> None:
    ensure_output_dir()

    payload = {
        "timestamp": now_iso(),
        **payload,
    }

    path = OUTPUT_DIR / name

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def safe_read(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[ERRO AO LER {path}: {exc}]"

    if limit is not None:
        return truncate(text, limit)

    return text


# ============================================================
# GIT — SOMENTE LEITURA
# ============================================================

def git(*args: str, timeout: int = 120) -> str:
    command = ["git", *args]

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git falhou:\n"
            + " ".join(command)
            + "\n\nSTDERR:\n"
            + result.stderr
        )

    return result.stdout.strip()


def validate_repository() -> None:
    result = git("rev-parse", "--is-inside-work-tree")

    if result.lower() != "true":
        raise RuntimeError("Este script precisa ser executado dentro do repositório Git da Nebula.")


def current_branch() -> str:
    try:
        return git("branch", "--show-current")
    except Exception:
        return "desconhecida"


def git_status_short() -> str:
    try:
        result = git("status", "--short")
        return result if result else "[working tree limpa]"
    except Exception as exc:
        return f"[não foi possível ler git status: {exc}]"


def find_golden_commit() -> str | None:
    """
    Procura o commit no qual GOLDEN_FILE foi adicionado.
    """
    candidates = [
        [
            "log",
            "--follow",
            "--diff-filter=A",
            "--reverse",
            "--format=%H",
            "--",
            GOLDEN_FILE,
        ],
        [
            "log",
            "--diff-filter=A",
            "--reverse",
            "--format=%H",
            "--",
            GOLDEN_FILE,
        ],
    ]

    for args in candidates:
        try:
            output = git(*args)

            commits = [line.strip() for line in output.splitlines() if line.strip()]

            if commits:
                return commits[0]
        except Exception:
            pass

    return None


def golden_diff(commit_sha: str | None) -> str:
    """
    Se achar o commit de criação, pega commit^..commit.
    Caso contrário, usa o diff atual entre lights.py e seu pai quando possível.
    """
    if not commit_sha:
        return (
            "[Não foi possível localizar automaticamente o commit que adicionou "
            f"{GOLDEN_FILE}. O arquivo atual ainda será analisado.]"
        )

    try:
        return git(
            "show",
            "--format=fuller",
            "--find-renames",
            commit_sha,
            "--",
            "main.py",
            GOLDEN_FILE,
        )
    except Exception as exc:
        return f"[Erro ao obter diff do golden example: {exc}]"


# ============================================================
# ESTRUTURA DO PROJETO
# ============================================================

def project_tree(max_depth: int = 4, max_files: int = 650) -> str:
    """
    Gera uma árvore simples sem dependências externas.
    """
    lines: list[str] = []
    count = 0

    root_depth = len(PROJECT_ROOT.parts)

    for current_root, dirs, files in os.walk(PROJECT_ROOT):
        current = Path(current_root)

        dirs[:] = sorted(
            d for d in dirs
            if d not in SKIP_DIRS
            and not d.startswith(".git")
        )

        depth = len(current.parts) - root_depth

        if depth > max_depth:
            dirs[:] = []
            continue

        if current == PROJECT_ROOT:
            rel = "."
        else:
            rel = str(current.relative_to(PROJECT_ROOT)).replace("\\", "/")

        indent = "  " * depth

        if current == PROJECT_ROOT:
            lines.append("assistente virtual/")
        else:
            lines.append(f"{indent}{current.name}/")

        for file_name in sorted(files):
            if count >= max_files:
                lines.append(f"{indent}  ... limite de {max_files} arquivos atingido ...")
                return truncate("\n".join(lines), MAX_TREE_CHARS)

            if file_name.endswith((".pyc", ".log", ".zip", ".png", ".jpg", ".jpeg", ".webp", ".exe", ".dll")):
                continue

            lines.append(f"{indent}  {file_name}")
            count += 1

    return truncate("\n".join(lines), MAX_TREE_CHARS)


# ============================================================
# ANÁLISE ESTÁTICA LEVE DO main.py
# ============================================================

def source_segment_for_node(source: str, node: ast.AST) -> str:
    lines = source.splitlines()

    start = max(0, getattr(node, "lineno", 1) - 1)
    end = getattr(node, "end_lineno", getattr(node, "lineno", 1))

    return "\n".join(lines[start:end])


def score_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """
    Score simples para encontrar funções mais 'caras' no main.py.
    Não é um diagnóstico. Só ajuda os agentes a escolher candidatos.
    """
    body_nodes = list(ast.walk(node))

    calls = sum(isinstance(n, ast.Call) for n in body_nodes)
    conditionals = sum(isinstance(n, (ast.If, ast.Match)) for n in body_nodes)
    loops = sum(isinstance(n, (ast.For, ast.While, ast.AsyncFor)) for n in body_nodes)
    tries = sum(isinstance(n, ast.Try) for n in body_nodes)
    globals_used = sum(isinstance(n, ast.Global) for n in body_nodes)

    length = (
        getattr(node, "end_lineno", node.lineno)
        - node.lineno
        + 1
    )

    return (
        length
        + calls * 2
        + conditionals * 3
        + loops * 4
        + tries * 4
        + globals_used * 5
    )


def analyze_main_candidates(limit: int = 8) -> tuple[str, str]:
    main_path = PROJECT_ROOT / "main.py"

    if not main_path.exists():
        return "[main.py não encontrado]", "[nenhum snippet]"

    source = safe_read(main_path)

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return (
            f"[Não foi possível fazer AST do main.py: {exc}]",
            truncate(source, MAX_MAIN_SNIPPET_CHARS),
        )

    funcs: list[tuple[int, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((score_function(node), node))

    funcs.sort(key=lambda item: item[0], reverse=True)
    funcs = funcs[:limit]

    summary_lines = [
        "CANDIDATOS AUTOMÁTICOS DO main.py",
        "(score é apenas heurística de tamanho/acoplamento; NÃO significa que devem ser movidos)",
        "",
    ]

    snippets: list[str] = []

    for score, node in funcs:
        end_lineno = getattr(node, "end_lineno", node.lineno)
        length = end_lineno - node.lineno + 1

        summary_lines.append(
            f"- {node.name} | linhas {node.lineno}-{end_lineno} "
            f"| {length} linhas | score {score}"
        )

        segment = source_segment_for_node(source, node)

        if len(segment) <= 5000:
            snippets.append(
                f"\n===== {node.name} (score {score}) =====\n{segment}"
            )
        else:
            snippets.append(
                f"\n===== {node.name} (score {score}) =====\n"
                + truncate(segment, 5000)
            )

    return (
        "\n".join(summary_lines),
        truncate("\n".join(snippets), MAX_MAIN_SNIPPET_CHARS),
    )


# ============================================================
# OLLAMA
# ============================================================

class OllamaAgent:
    def __init__(
        self,
        name: str,
        host: str,
        model: str,
        *,
        think: bool = False,
        num_ctx: int = DEFAULT_NUM_CTX,
        temperature: float = DEFAULT_TEMPERATURE,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
        timeout: int = 900,
    ) -> None:
        self.name = name
        self.host = host.rstrip("/")
        self.model = model
        self.think = think
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.keep_alive = keep_alive
        self.timeout = timeout

    def is_alive(self) -> bool:
        try:
            response = requests.get(
                f"{self.host}/api/tags",
                timeout=8,
            )
            return response.ok
        except requests.RequestException:
            return False

    def available_models(self) -> list[str]:
        try:
            response = requests.get(
                f"{self.host}/api/tags",
                timeout=8,
            )
            response.raise_for_status()

            data = response.json()

            return [
                item.get("name", "")
                for item in data.get("models", [])
                if item.get("name")
            ]
        except Exception:
            return []

    def chat(
        self,
        *,
        system: str,
        prompt: str,
        timeout: int | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
            },
        }

        started = time.time()

        response = requests.post(
            f"{self.host}/api/chat",
            json=payload,
            timeout=timeout or self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        elapsed = time.time() - started

        content = data.get("message", {}).get("content", "")

        append_jsonl(
            "requests.jsonl",
            {
                "agent": self.name,
                "model": self.model,
                "elapsed_seconds": round(elapsed, 3),
                "prompt_chars": len(prompt),
                "response_chars": len(content),
                "done_reason": data.get("done_reason"),
                "eval_count": data.get("eval_count"),
                "eval_duration": data.get("eval_duration"),
            },
        )

        return truncate(content.strip(), MAX_MODEL_RESPONSE_CHARS)


# ============================================================
# PROMPTS
# ============================================================

WORKER_SYSTEM = """
Você é o Worker da Sprint de arquitetura da Nebula.

Seu trabalho NÃO é alterar código.

Você deve analisar evidências reais do repositório e extrair padrões arquiteturais
que possam ser reutilizados em refactors futuros.

Regras:
- não invente arquivos, funções ou dependências;
- diferencie claramente fato observado, inferência e hipótese;
- preserve o comportamento do software como prioridade;
- use o refactor do abajur/lights.py feito pelo Codex como golden example;
- o objetivo é aprender o padrão atual da Nebula, não impor uma arquitetura genérica;
- não sugira reescrever o projeto inteiro;
- prefira modularização incremental;
- quando faltar contexto, diga que falta contexto;
- nunca diga que executou ou testou algo que não foi fornecido como evidência.
""".strip()


REVIEWER_SYSTEM = """
Você é o Reviewer técnico da Sprint de arquitetura da Nebula.

Seu papel é desconfiar de afirmações não sustentadas pelo código.

Você NÃO altera arquivos.

Revise a análise do Worker comparando-a com as evidências reais:
- diff do refactor do abajur;
- lights.py atual;
- estrutura atual do projeto;
- main.py e candidatos observados.

Procure especialmente:
- alucinações;
- generalizações baseadas em um único exemplo;
- import circular;
- estado global;
- threads;
- callbacks;
- efeitos colaterais;
- dependências escondidas;
- alterações que poderiam mudar comportamento;
- módulos novos desnecessários.

Classifique cada regra importante como:
CONFIRMADA, PLAUSÍVEL ou NÃO SUPORTADA.

Se o Worker estiver certo, diga por quê.
Se estiver errado, corrija usando somente as evidências.
""".strip()


CONSOLIDATOR_SYSTEM = """
Você é novamente o Worker, agora responsável por consolidar uma rodada após receber
a revisão crítica de outro modelo.

Você NÃO altera código.

Sua saída deve reduzir incerteza, remover afirmações não sustentadas e manter somente
regras úteis para orientar futuras modularizações em conjunto com o Codex.

Não transforme uma decisão específica do abajur em regra universal sem evidência.
""".strip()


def worker_prompt(
    round_index: int,
    focus: str,
    diff_text: str,
    lights_text: str,
    tree_text: str,
    candidate_summary: str,
    candidate_snippets: str,
    previous_consensus: str,
) -> str:
    return f"""
SPRINT 01 — RODADA {round_index}

FOCO DESTA RODADA:
{focus}

GOAL PRINCIPAL:
Aprender a arquitetura atual da Nebula a partir do golden example do Codex:
o controle do abajur foi modularizado em `modules/iot/lights.py` e `main.py`
passou a delegar a execução.

Não altere arquivos.
Não escreva patch.
Não proponha commit.

===== BRANCH / CONTEXTO =====

Branch atual:
{current_branch()}

Git status:
{git_status_short()}

===== ÁRVORE ATUAL DO PROJETO =====

{tree_text}

===== GOLDEN EXAMPLE — DIFF DO CODEX =====

{diff_text}

===== GOLDEN EXAMPLE — lights.py ATUAL =====

{lights_text}

===== CANDIDATOS ENCONTRADOS NO main.py =====

{candidate_summary}

===== TRECHOS DE ALGUNS CANDIDATOS =====

{candidate_snippets}

===== CONSENSO ACUMULADO DE RODADAS ANTERIORES =====

{previous_consensus if previous_consensus else "[primeira rodada — nenhum consenso anterior]"}

Produza uma análise estruturada contendo:

1. FATOS OBSERVADOS
   Apenas coisas que aparecem nas evidências.

2. PADRÕES ARQUITETURAIS PROVÁVEIS
   Regras que parecem orientar o refactor do Codex.

3. O QUE NÃO PODE SER GENERALIZADO
   Decisões específicas do abajur/lights.py.

4. CONTRATO ENTRE main.py E MÓDULOS
   O que parece permanecer no main e o que parece sair.

5. RISCOS
   Globais, callbacks, threads, imports, estado, dependências.

6. CANDIDATOS FUTUROS
   No máximo 3 funções/áreas que merecem investigação futura.
   NÃO diga para movê-las ainda; apenas explique por que investigar.

7. PERGUNTAS EM ABERTO
   O que ainda precisaria ser visto antes de um refactor real.

Seja concreto e cite nomes de arquivos/funções quando eles realmente estiverem
presentes nas evidências.
""".strip()


def reviewer_prompt(
    round_index: int,
    focus: str,
    worker_analysis: str,
    diff_text: str,
    lights_text: str,
    candidate_summary: str,
) -> str:
    return f"""
SPRINT 01 — REVIEW DA RODADA {round_index}

FOCO:
{focus}

===== EVIDÊNCIA: DIFF DO GOLDEN EXAMPLE =====

{diff_text}

===== EVIDÊNCIA: lights.py ATUAL =====

{lights_text}

===== CANDIDATOS DO main.py =====

{candidate_summary}

===== ANÁLISE DO WORKER 4B =====

{worker_analysis}

Faça uma revisão adversarial.

Para cada conclusão importante do Worker:
- CONFIRMADA: aparece claramente nas evidências;
- PLAUSÍVEL: faz sentido, mas ainda precisa de mais contexto;
- NÃO SUPORTADA: extrapolação ou invenção.

Depois produza:

1. ERROS / ALUCINAÇÕES
2. GENERALIZAÇÕES PREMATURAS
3. RISCOS NÃO PERCEBIDOS
4. CORREÇÕES
5. REGRAS QUE VALEM SER PRESERVADAS
6. VEREDITO DA RODADA:
   APROVADO_PARA_CONSOLIDAR
   ou
   PRECISA_DE_CORRECAO

Não escreva código novo.
""".strip()


def consolidate_prompt(
    round_index: int,
    focus: str,
    worker_analysis: str,
    reviewer_analysis: str,
    previous_consensus: str,
) -> str:
    return f"""
SPRINT 01 — CONSOLIDAÇÃO DA RODADA {round_index}

FOCO:
{focus}

===== ANÁLISE ORIGINAL DO WORKER =====

{worker_analysis}

===== REVISÃO DO 9B =====

{reviewer_analysis}

===== CONSENSO ANTERIOR =====

{previous_consensus if previous_consensus else "[nenhum]"}

Gere o NOVO CONSENSO ACUMULADO.

Formato:

# Consenso arquitetural provisório

## Confirmado por evidência
- ...

## Plausível, mas ainda precisa de validação
- ...

## Regras que NÃO devemos assumir
- ...

## Golden example: lights.py
- origem:
- destino:
- padrão de delegação:
- dependências observadas:
- comportamento preservado:
- limites do exemplo:

## Regras para futuros agentes
- ...

## Candidatos para investigação futura
- ...

## Perguntas em aberto
- ...

Não inclua afirmações que o Reviewer marcou como não suportadas, a menos que você
explique explicitamente por que a evidência contradiz a revisão.
""".strip()


# ============================================================
# RELATÓRIOS FINAIS
# ============================================================

def build_golden_example_report(
    commit_sha: str | None,
    diff_text: str,
    lights_text: str,
    consensus: str,
) -> str:
    return f"""# Refactor Example 001 — Lights / Abajur

Gerado em: {now_iso()}

## Objetivo

Registrar como golden example a modularização do controle do abajur para
`modules/iot/lights.py`, usada como referência para futuras sprints da Nebula.

## Commit de origem

`{commit_sha or "não localizado automaticamente"}`

## Arquivo destino

`{GOLDEN_FILE}`

## Consenso dos agentes

{consensus}

## Diff de referência

```diff
{truncate(diff_text, 30000)}
```

## Estado atual de lights.py

```python
{truncate(lights_text, 22000)}
```
"""


def build_candidate_report(
    candidate_summary: str,
    final_consensus: str,
) -> str:
    return f"""# Candidatos para próximas sprints

Gerado em: {now_iso()}

Este arquivo NÃO autoriza nenhuma alteração automática.

A lista serve apenas como fila de investigação para você / Codex / agentes.

## Heurística automática do main.py

```text
{candidate_summary}
```

## Conclusões dos agentes

{final_consensus}
"""


def build_session_summary(
    rounds_done: int,
    started_at: str,
    commit_sha: str | None,
    reviewer_online: bool,
    final_consensus: str,
) -> str:
    return f"""# Sprint 01 — Session Summary

Início: {started_at}
Fim: {now_iso()}
Rodadas concluídas: {rounds_done}

## Modelos

- Worker: `{WORKER_MODEL}` em `{WORKER_HOST}`
- Reviewer: `{REVIEWER_MODEL}` em `{REVIEWER_HOST}`
- Reviewer online no início: `{reviewer_online}`

## Golden example

- Arquivo: `{GOLDEN_FILE}`
- Commit: `{commit_sha or "não localizado automaticamente"}`

## Segurança aplicada

- nenhum arquivo funcional foi editado;
- nenhum commit foi criado;
- nenhum merge foi feito;
- nenhum push foi feito;
- saídas foram gravadas somente em `{OUTPUT_DIR.relative_to(PROJECT_ROOT)}`.

## Consenso final

{final_consensus}
"""


# ============================================================
# LOOP PRINCIPAL
# ============================================================

def run_sprint(
    rounds: int,
    sleep_seconds: int,
    stop_on_reviewer_offline: bool,
) -> None:
    started_at = now_iso()

    ensure_output_dir()

    say("Validando repositório Git...")
    validate_repository()

    say("Preparando agentes...")

    worker = OllamaAgent(
        "worker_pc_4b",
        WORKER_HOST,
        WORKER_MODEL,
        think=False,
    )

    reviewer = OllamaAgent(
        "reviewer_notebook_9b",
        REVIEWER_HOST,
        REVIEWER_MODEL,
        think=False,
    )

    if not worker.is_alive():
        raise RuntimeError(
            f"O Ollama do PC não respondeu em {WORKER_HOST}."
        )

    worker_models = worker.available_models()

    if WORKER_MODEL not in worker_models:
        raise RuntimeError(
            f"O modelo {WORKER_MODEL} não aparece no PC.\n"
            f"Modelos encontrados: {worker_models}"
        )

    reviewer_online = reviewer.is_alive()

    if reviewer_online:
        reviewer_models = reviewer.available_models()

        if REVIEWER_MODEL not in reviewer_models:
            say(
                f"AVISO: notebook respondeu, mas {REVIEWER_MODEL} não apareceu. "
                f"Encontrados: {reviewer_models}"
            )
            reviewer_online = False
    else:
        say("AVISO: reviewer do notebook está offline.")

    if stop_on_reviewer_offline and not reviewer_online:
        raise RuntimeError(
            "Reviewer offline e --stop-on-reviewer-offline foi solicitado."
        )

    say("Lendo estrutura atual do projeto...")
    tree_text = project_tree()

    say("Procurando golden example no Git...")
    commit_sha = find_golden_commit()

    if commit_sha:
        say(f"Commit do lights.py encontrado: {commit_sha[:12]}")
    else:
        say("Não localizei automaticamente o commit de criação de lights.py.")

    diff_text = truncate(
        golden_diff(commit_sha),
        MAX_DIFF_CHARS,
    )

    lights_path = PROJECT_ROOT / GOLDEN_FILE

    lights_text = (
        safe_read(lights_path, 22000)
        if lights_path.exists()
        else f"[{GOLDEN_FILE} não encontrado na árvore atual]"
    )

    say("Analisando funções candidatas do main.py...")
    candidate_summary, candidate_snippets = analyze_main_candidates()

    save_text("project_tree.txt", tree_text)
    save_text("golden_diff.txt", diff_text)
    save_text("main_candidates.txt", candidate_summary)
    save_text("main_candidate_snippets.txt", candidate_snippets)

    append_jsonl(
        "sprint_log.jsonl",
        {
            "event": "sprint_started",
            "project_root": str(PROJECT_ROOT),
            "branch": current_branch(),
            "golden_file": GOLDEN_FILE,
            "golden_commit": commit_sha,
            "worker_online": True,
            "reviewer_online": reviewer_online,
            "rounds_requested": rounds,
        },
    )

    consensus = ""
    rounds_done = 0
    consecutive_errors = 0

    for index in range(1, rounds + 1):
        focus = FOCUS_BY_ROUND[(index - 1) % len(FOCUS_BY_ROUND)]

        say("=" * 60)
        say(f"RODADA {index}/{rounds}")
        say(f"Foco: {focus}")

        try:
            say("4B analisando...")

            worker_analysis = worker.chat(
                system=WORKER_SYSTEM,
                prompt=worker_prompt(
                    index,
                    focus,
                    diff_text,
                    lights_text,
                    tree_text,
                    candidate_summary,
                    candidate_snippets,
                    truncate(consensus, MAX_PREVIOUS_CONSENSUS_CHARS),
                ),
            )

            save_text(
                f"round_{index:02d}_worker.md",
                worker_analysis,
            )

            if reviewer_online:
                say("9B revisando no notebook...")

                try:
                    reviewer_analysis = reviewer.chat(
                        system=REVIEWER_SYSTEM,
                        prompt=reviewer_prompt(
                            index,
                            focus,
                            worker_analysis,
                            diff_text,
                            lights_text,
                            candidate_summary,
                        ),
                    )

                except Exception as exc:
                    reviewer_online = False

                    reviewer_analysis = (
                        "# Reviewer offline nesta rodada\n\n"
                        f"Erro: `{type(exc).__name__}: {exc}`\n\n"
                        "A sprint continuará apenas com o Worker, mas qualquer "
                        "conclusão nova deve ser tratada como provisória."
                    )

                    say(f"Reviewer caiu: {exc}")

            else:
                reviewer_analysis = (
                    "# Reviewer offline\n\n"
                    "Nenhuma revisão cruzada foi feita nesta rodada. "
                    "Conclusões devem permanecer provisórias."
                )

            save_text(
                f"round_{index:02d}_reviewer.md",
                reviewer_analysis,
            )

            say("4B consolidando a rodada...")

            consensus = worker.chat(
                system=CONSOLIDATOR_SYSTEM,
                prompt=consolidate_prompt(
                    index,
                    focus,
                    worker_analysis,
                    reviewer_analysis,
                    truncate(consensus, MAX_PREVIOUS_CONSENSUS_CHARS),
                ),
            )

            save_text(
                f"round_{index:02d}_consensus.md",
                consensus,
            )

            save_text(
                "architecture_draft.md",
                consensus,
            )

            rounds_done += 1
            consecutive_errors = 0

            append_jsonl(
                "sprint_log.jsonl",
                {
                    "event": "round_completed",
                    "round": index,
                    "focus": focus,
                    "reviewer_online": reviewer_online,
                    "consensus_chars": len(consensus),
                },
            )

            say(f"Rodada {index} concluída.")

        except KeyboardInterrupt:
            say("Interrompido manualmente.")
            break

        except Exception as exc:
            consecutive_errors += 1

            say(f"ERRO NA RODADA {index}: {exc}")

            append_jsonl(
                "sprint_log.jsonl",
                {
                    "event": "round_error",
                    "round": index,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "consecutive_errors": consecutive_errors,
                },
            )

            if consecutive_errors >= 3:
                say("3 erros consecutivos. Encerrando por segurança.")
                break

        if index < rounds and sleep_seconds > 0:
            say(f"Pausa de {sleep_seconds}s antes da próxima rodada...")
            time.sleep(sleep_seconds)

    if not consensus:
        consensus = (
            "# Sprint sem consenso final\n\n"
            "Nenhuma rodada foi concluída com sucesso."
        )

    save_text(
        "001_lights.md",
        build_golden_example_report(
            commit_sha,
            diff_text,
            lights_text,
            consensus,
        ),
    )

    save_text(
        "candidate_refactors.md",
        build_candidate_report(
            candidate_summary,
            consensus,
        ),
    )

    save_text(
        "session_summary.md",
        build_session_summary(
            rounds_done,
            started_at,
            commit_sha,
            reviewer_online,
            consensus,
        ),
    )

    append_jsonl(
        "sprint_log.jsonl",
        {
            "event": "sprint_finished",
            "rounds_completed": rounds_done,
            "reviewer_online_at_end": reviewer_online,
        },
    )

    say("=" * 60)
    say("SPRINT FINALIZADA")
    say(f"Rodadas concluídas: {rounds_done}")
    say(f"Resultados: {OUTPUT_DIR}")
    say("Nenhum arquivo funcional do projeto foi alterado.")


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sprint 01 da Nebula: estudo colaborativo 4B + 9B "
            "do golden example de modularização do Codex."
        )
    )

    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help=f"Número de rodadas de análise. Padrão: {DEFAULT_ROUNDS}",
    )

    parser.add_argument(
        "--sleep",
        type=int,
        default=DEFAULT_SLEEP_SECONDS,
        help=(
            "Pausa em segundos entre rodadas. "
            f"Padrão: {DEFAULT_SLEEP_SECONDS}"
        ),
    )

    parser.add_argument(
        "--stop-on-reviewer-offline",
        action="store_true",
        help="Encerra se o notebook/reviewer estiver offline.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.rounds < 1:
        raise SystemExit("--rounds precisa ser >= 1")

    if args.rounds > 50:
        raise SystemExit(
            "--rounds acima de 50 foi bloqueado por segurança. "
            "Use várias execuções se realmente precisar."
        )

    if args.sleep < 0:
        raise SystemExit("--sleep não pode ser negativo.")

    try:
        run_sprint(
            rounds=args.rounds,
            sleep_seconds=args.sleep,
            stop_on_reviewer_offline=args.stop_on_reviewer_offline,
        )

    except KeyboardInterrupt:
        print("\nSprint interrompida.", flush=True)

    except Exception as exc:
        ensure_output_dir()

        append_jsonl(
            "sprint_log.jsonl",
            {
                "event": "fatal_error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

        print(
            f"\nERRO FATAL: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )

        raise SystemExit(1)


if __name__ == "__main__":
    main()
