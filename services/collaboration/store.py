"""Fila, reservas e orçamento transacionais; Markdown derivado dos eventos."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
import time
from uuid import uuid4

AGENTS = ("codex", "opus")
LOGGER = logging.getLogger(__name__)


class _Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Conflict(RuntimeError):
    """A operação conflita com estado, orçamento ou reserva existente."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text(value, label="texto", limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label}: informe texto entre 1 e {limit} caracteres.")
    return value.strip()


def agent_name(value):
    if value not in AGENTS:
        raise ValueError("Agente desconhecido.")
    return value


def path_key(value):
    raw = text(value, "caminho", 240).replace("\\", "/")
    parts = raw.rstrip("/").split("/")
    if raw.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise ValueError("Use um caminho relativo sem .. ou componentes vazios.")
    if any(c in raw for c in ':*?\x00\n\r') or parts[0].casefold() in {".git", ".nebula-collaboration"}:
        raise ValueError("Caminho reservado ou inválido.")
    return str(PurePosixPath(*parts)).casefold()


def overlap(left, right):
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def priority(impact, urgency, risk, confidence, estimated_tokens):
    for value in (impact, urgency, risk):
        if type(value) is not int or not 1 <= value <= 5:
            raise ValueError("Notas de impacto, urgência e risco devem ser de 1 a 5.")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 < confidence <= 1:
        raise ValueError("Confiança deve estar entre 0 e 1.")
    if type(estimated_tokens) is not int or not 100 <= estimated_tokens <= 500000:
        raise ValueError("Estimativa deve estar entre 100 e 500000 tokens.")
    return round((impact * 3 + urgency * 2 + risk * 2) * confidence * 1000 / estimated_tokens, 3)


class CollaborationStore:
    def __init__(self, project_root):
        self.root = Path(project_root).resolve()
        self.directory = self.root / ".nebula-collaboration"
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / ".gitignore").write_text("*\n", encoding="utf-8")
        self.database = self.directory / "state.sqlite3"
        self.log_path = self.directory / "SESSOES.md"
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, idea TEXT, data TEXT NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO state VALUES(1, ?)", (json.dumps({
                "ideas": [], "tasks": [], "confirmations": [], "budgets": {},
                "paused": False, "active_run": None,
            }),))

    def _connect(self):
        conn = sqlite3.connect(self.database, timeout=15, factory=_Connection)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            state = json.loads(conn.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            yield conn, state
            conn.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state, ensure_ascii=False),))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        try:
            self.export_markdown()
        except PermissionError:
            # O evento já foi confirmado no SQLite. Um leitor do Windows pode
            # bloquear momentaneamente a troca do Markdown; a próxima exportação
            # recompõe o diário a partir dos eventos, sem perder esta operação.
            LOGGER.warning("Não foi possível atualizar SESSOES.md; o SQLite permanece atualizado.", exc_info=True)

    @staticmethod
    def event(conn, actor, kind, idea, data):
        conn.execute("INSERT INTO events(at,actor,kind,idea,data) VALUES(?,?,?,?,?)",
                     (now(), actor, kind, idea, json.dumps(data, ensure_ascii=False)))

    @staticmethod
    def find(items, item_id):
        for item in items:
            if item["id"] == item_id:
                return item
        raise ValueError("Registro não encontrado.")

    def snapshot(self):
        with self._connect() as conn:
            conn.execute("BEGIN")
            state = json.loads(conn.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            rows = conn.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 200").fetchall()
        state["messages"] = [dict(row, data=json.loads(row["data"])) for row in reversed(rows)]
        state["tasks"].sort(key=lambda task: (-task["priority"], task["created_at"], task["id"]))
        state["log_path"] = str(self.log_path)
        return state

    def create_idea(self, content, token_budget=60000):
        content = text(content, "ideia")
        if type(token_budget) is not int or not 2000 <= token_budget <= 2000000:
            raise ValueError("Orçamento deve estar entre 2000 e 2000000 tokens por agente.")
        idea = {"id": uuid4().hex, "text": content, "status": "pending", "created_at": now()}
        with self.transaction() as (conn, state):
            state["ideas"].append(idea)
            state["budgets"][idea["id"]] = {a: {"limit": token_budget, "measured": 0,
                "estimated": 0, "reserved": 0, "unknown_calls": 0} for a in AGENTS}
            self.event(conn, "user", "idea", idea["id"], {"text": content})
        return idea

    def message(self, idea_id, actor, content, kind="coordination"):
        if actor not in (*AGENTS, "user", "system"):
            raise ValueError("Autor inválido.")
        content = text(content)
        with self.transaction() as (conn, state):
            self.find(state["ideas"], idea_id)
            self.event(conn, actor, kind, idea_id, {"text": content})

    def begin_chat(self, idea_id, content):
        content = text(content)
        chat_id = uuid4().hex
        with self.transaction() as (conn, state):
            self.find(state["ideas"], idea_id)
            if state.get("active_chat") or state.get("active_run"):
                raise Conflict("As duas ainda estão respondendo. Aguarde esta rodada terminar.")
            state["active_chat"] = {"id": chat_id, "idea_id": idea_id, "started_at": now()}
            self.event(conn, "user", "user_message", idea_id, {"text": content})
        return chat_id

    def end_chat(self, chat_id):
        with self.transaction() as (conn, state):
            if (state.get("active_chat") or {}).get("id") != chat_id:
                raise Conflict("Conversa não corresponde à rodada ativa.")
            state["active_chat"] = None

    def chat_reply(self, idea_id, actor, reply):
        content = text(reply.data.get("text"))
        agent_name(actor)
        with self.transaction() as (conn, state):
            self.find(state["ideas"], idea_id)
            self.event(conn, actor, "chat_reply", idea_id, {
                "text": content, "model": reply.model, "session_id": reply.session_id,
            })

    def begin_development(self, content, idea_id=None, token_budget=60000):
        content = text(content)
        if type(token_budget) is not int or not 2000 <= token_budget <= 2000000:
            raise ValueError("Orçamento deve estar entre 2000 e 2000000 tokens por agente.")
        chat_id = uuid4().hex
        with self.transaction() as (conn, state):
            if state.get("active_chat") or state.get("active_run") or state["paused"]:
                raise Conflict("Já existe uma rodada ativa ou a Dupla está pausada.")
            if any(t["status"] in {"running", "interrupted"} for t in state["tasks"]):
                raise Conflict("Há arquivos reservados por uma tarefa anterior. Resolva essa tarefa antes de desenvolver.")
            if idea_id:
                self.find(state["ideas"], idea_id)
            else:
                idea_id = uuid4().hex
                state["ideas"].append({"id": idea_id, "text": content, "status": "pending", "created_at": now()})
                state["budgets"][idea_id] = {a: {"limit": token_budget, "measured": 0,
                    "estimated": 0, "reserved": 0, "unknown_calls": 0} for a in AGENTS}
            state["active_chat"] = {"id": chat_id, "idea_id": idea_id,
                                    "mode": "development", "started_at": now()}
            self.event(conn, "user", "user_message", idea_id, {"text": content})
        return idea_id, chat_id

    def development_session(self, idea_id, actor, session_id=None):
        from uuid import UUID
        agent_name(actor)
        if session_id is None:
            return self.snapshot().get("development_sessions", {}).get(idea_id, {}).get(actor)
        UUID(session_id)
        with self.transaction() as (_, state):
            self.find(state["ideas"], idea_id)
            state.setdefault("development_sessions", {}).setdefault(idea_id, {})[actor] = session_id

    def development_process(self, chat_id, process):
        with self.transaction() as (_, state):
            if (state.get("active_chat") or {}).get("id") != chat_id:
                raise Conflict("Rodada não está mais ativa.")
            state["active_chat"]["process"] = process

    def confirm(self, idea_id, actor, content, session_id, model):
        agent_name(actor)
        item = {"idea_id": idea_id, "agent": actor, "text": text(content, limit=600),
                "session_id": text(session_id, limit=200), "model": text(model, limit=200), "at": now()}
        with self.transaction() as (conn, state):
            self.find(state["ideas"], idea_id)
            if any(c["idea_id"] == idea_id and c["agent"] == actor for c in state["confirmations"]):
                raise Conflict("Este agente já confirmou o pedido.")
            state["confirmations"].append(item)
            self.event(conn, actor, "confirmation", idea_id, item)
        return item

    def add_task(self, idea_id, actor, *, title, owner, paths, reason,
                 impact=3, urgency=3, risk=3, confidence=0.8, estimated_tokens=4000, dependencies=None):
        if actor != "user":
            agent_name(actor)
        agent_name(owner)
        if not isinstance(paths, list) or not 1 <= len(paths) <= 20:
            raise ValueError("Informe de 1 a 20 arquivos ou pastas.")
        resources = sorted(set(path_key(p) for p in paths))
        score = priority(impact, urgency, risk, confidence, estimated_tokens)
        deps = dependencies or []
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise ValueError("Dependências inválidas.")
        task = {"id": uuid4().hex, "idea_id": idea_id, "title": text(title, limit=300),
                "owner": owner, "paths": resources, "reason": text(reason, limit=1200),
                "impact": impact, "urgency": urgency, "risk": risk, "confidence": confidence,
                "estimated_tokens": estimated_tokens, "priority": score,
                "dependencies": deps, "status": "queued", "created_at": now()}
        with self.transaction() as (conn, state):
            self.find(state["ideas"], idea_id)
            for dependency in deps:
                if self.find(state["tasks"], dependency)["idea_id"] != idea_id:
                    raise ValueError("Dependência pertence a outro pedido.")
            state["tasks"].append(task)
            self.event(conn, actor, "task_planned", idea_id, task)
        return task

    def claim(self, task_id, actor):
        agent_name(actor)
        with self.transaction() as (conn, state):
            task = self.find(state["tasks"], task_id)
            if state["paused"] or task["status"] != "queued" or task["owner"] != actor:
                raise Conflict("Tarefa pausada, já reservada ou pertence a outro agente.")
            for dependency in task["dependencies"]:
                if self.find(state["tasks"], dependency)["status"] != "completed":
                    raise Conflict("Dependência ainda não concluída.")
            for other in state["tasks"]:
                if other["status"] in {"running", "interrupted"}:
                    if other["owner"] == actor:
                        raise Conflict("O agente já possui uma seção reservada.")
                    if any(overlap(a, b) for a in task["paths"] for b in other["paths"]):
                        raise Conflict(f"Arquivos reservados por {other['owner']}: {other['title']}")
            task.update(status="running", started_at=now())
            self.event(conn, actor, "task_claimed", task["idea_id"], {"task_id": task_id, "paths": task["paths"]})
        return task

    def finish(self, task_id, actor, *, summary, evidence, success=True):
        agent_name(actor)
        if type(success) is not bool:
            raise ValueError("success deve ser booleano.")
        summary, evidence = text(summary), text(evidence, "verificação")
        with self.transaction() as (conn, state):
            task = self.find(state["tasks"], task_id)
            if task["owner"] != actor or task["status"] not in {"running", "interrupted"}:
                raise Conflict("Só o responsável pode concluir uma tarefa reservada.")
            task.update(status="completed" if success else "failed", finished_at=now(), summary=summary, evidence=evidence)
            self.event(conn, actor, "code_section", task["idea_id"], {
                "task_id": task_id, "title": task["title"], "paths": task["paths"],
                "summary": summary, "evidence": evidence, "success": success,
            })
        return task

    def reserve_tokens(self, idea_id, actor, amount):
        agent_name(actor)
        if type(amount) is not int or amount <= 0:
            raise ValueError("Reserva inválida.")
        ticket = uuid4().hex
        with self.transaction() as (conn, state):
            budget = state["budgets"][self.find(state["ideas"], idea_id)["id"]][actor]
            if state["paused"] or budget["measured"] + budget["estimated"] + budget["reserved"] + amount > budget["limit"]:
                raise Conflict("Execução pausada ou orçamento insuficiente para outra rodada.")
            budget["reserved"] += amount
            state.setdefault("token_tickets", {})[ticket] = {"idea": idea_id, "actor": actor, "amount": amount}
            self.event(conn, actor, "tokens_reserved", idea_id, {"ticket": ticket, "estimated_tokens": amount})
        return ticket

    def settle_tokens(self, ticket, measured=None):
        if measured is not None and (type(measured) is not int or measured < 0):
            raise ValueError("Consumo inválido.")
        with self.transaction() as (conn, state):
            reservation = state.get("token_tickets", {}).pop(ticket, None)
            if not reservation:
                raise Conflict("Reserva de tokens já encerrada ou inexistente.")
            budget = state["budgets"][reservation["idea"]][reservation["actor"]]
            budget["reserved"] -= reservation["amount"]
            if measured is None:
                budget["estimated"] += reservation["amount"]
                budget["unknown_calls"] += 1
            else:
                budget["measured"] += measured
            self.event(conn, reservation["actor"], "tokens_used", reservation["idea"], {"measured": measured,
                "estimated": reservation["amount"] if measured is None else None})

    def pause(self, paused):
        if type(paused) is not bool:
            raise ValueError("paused deve ser booleano.")
        with self.transaction() as (conn, state):
            state["paused"] = paused
            self.event(conn, "user", "pause", None, {"paused": paused})

    def start_run(self, idea_id):
        run_id = uuid4().hex
        with self.transaction() as (conn, state):
            idea = self.find(state["ideas"], idea_id)
            if state["active_run"] or state.get("active_chat") or state["paused"] or idea["status"] not in {"pending", "blocked", "failed"}:
                raise Conflict("Já existe execução ativa, pedido processado ou pausa pendente.")
            # A retomada explícita só ocorre após end_run liberar o processo.
            # Queda do host mantém active_run e exige recuperação manual.
            for task in state["tasks"]:
                if task["idea_id"] == idea_id and task["status"] in {"interrupted", "failed"}:
                    task["status"] = "queued"
            state["active_run"] = {"id": run_id, "idea_id": idea_id, "started_at": now()}
            idea["status"] = "running"
            self.event(conn, "system", "run_started", idea_id, {"run_id": run_id})
        return run_id

    def end_run(self, run_id, status):
        if status not in {"completed", "blocked", "failed"}:
            raise ValueError("Estado final inválido.")
        with self.transaction() as (conn, state):
            run = state["active_run"]
            if not run or run["id"] != run_id:
                raise Conflict("Execução não corresponde à reserva.")
            self.find(state["ideas"], run["idea_id"])["status"] = status
            for task in state["tasks"]:
                if task["idea_id"] == run["idea_id"] and task["status"] == "running":
                    task["status"] = "interrupted"
            state["active_run"] = None
            self.event(conn, "system", "run_finished", run["idea_id"], {"status": status})

    def export_markdown(self):
        # A mesma trava SQLite serializa também os exportadores de processos distintos.
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
            lines = ["# Nebula — sessões de colaboração", "",
                     "Registro operacional. Conteúdo dos agentes preservado como texto.", ""]
            for row in rows:
                lines += [f"## {row['seq']} · {row['at']} · {row['actor']} · {row['kind']}", ""]
                data = json.loads(row["data"])
                # Bloco indentado impede que Markdown de modelos injete links/imagens.
                for line in json.dumps(data, ensure_ascii=False, indent=2).splitlines():
                    lines.append("    " + line)
                lines.append("")
            fd, temporary = tempfile.mkstemp(dir=self.directory, suffix=".md.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write("\n".join(lines) + "\n")
                for attempt in range(5):
                    try:
                        os.replace(temporary, self.log_path)
                        break
                    except PermissionError:
                        if attempt == 4:
                            raise
                        time.sleep(0.05 * 2 ** attempt)
            finally:
                Path(temporary).unlink(missing_ok=True)
            conn.commit()
        return self.log_path
