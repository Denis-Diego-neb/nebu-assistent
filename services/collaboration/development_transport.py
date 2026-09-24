"""CLIs persistentes com ferramentas e eventos operacionais, sem raciocínio privado."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from uuid import UUID

import psutil

from .providers import Reply, executable


def command(agent, session_id=None):
    binary = executable(agent)
    if not binary:
        raise RuntimeError(f"CLI de {agent} indisponível.")
    if session_id:
        UUID(session_id)  # Apenas IDs retornados pelos CLIs, nunca opções arbitrárias.
    model = os.getenv(f"NEBULA_COLLAB_{agent.upper()}_MODEL", "opus" if agent == "opus" else "configured")
    if agent == "codex":
        args = [binary, "--ask-for-approval", "never", "exec"]
        if session_id:
            args += ["resume"]
        args += ["--json", "-c", 'sandbox_mode="workspace-write"']
        if os.name == "nt":
            args += ["-c", 'windows.sandbox="unelevated"']
        if model != "configured":
            args += ["--model", model]
        if session_id:
            args += [session_id]
        args += ["-"]
    else:
        allowed = "Read,Edit,Write,Glob,Grep,Bash,PowerShell"
        args = [binary, "--print", "--output-format", "stream-json", "--verbose",
                "--model", model, "--tools", allowed, "--allowedTools", allowed,
                "--permission-mode", "acceptEdits", "--permission-prompts", "none",
                "--strict-mcp-config"]
        if session_id:
            args += ["--resume", session_id]
    return args, model


def stop_process_tree(process):
    try:
        root = psutil.Process(process.pid)
        descendants = root.children(recursive=True)
        for child in reversed(descendants):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        root.kill()
        psutil.wait_procs([root, *descendants], timeout=3)
    except psutil.NoSuchProcess:
        pass


class Events:
    def __init__(self, agent, model, callback):
        self.agent, self.model, self.callback = agent, model, callback
        self.session = ""
        self.answer = ""
        self.tokens = None
        self.completed = False
        self.error = ""

    def emit(self, kind, text):
        if text:
            self.callback(kind, str(text)[:8000])

    def consume(self, event):
        kind = event.get("type")
        if self.agent == "codex":
            if kind == "thread.started":
                self.session = event.get("thread_id", "")
                self.emit("session", self.session)
            elif kind in {"item.started", "item.completed"}:
                item = event.get("item", {})
                item_type = item.get("type")
                if item_type == "agent_message" and kind == "item.completed":
                    self.answer = item.get("text", "")
                    self.emit("agent_update", self.answer)
                elif item_type == "command_execution":
                    text = item.get("command", "")
                    if kind == "item.completed":
                        text += f"\nSaída ({item.get('exit_code')}):\n" + item.get("aggregated_output", "")[-6000:]
                    self.emit("tool_activity", text)
                elif item_type == "file_change":
                    self.emit("tool_activity", json.dumps(item.get("changes", []), ensure_ascii=False))
            elif kind == "turn.completed":
                self.completed = True
                usage = event.get("usage", {})
                if all(type(usage.get(k)) is int for k in ("input_tokens", "output_tokens")):
                    self.tokens = usage["input_tokens"] + usage["output_tokens"]
            elif kind in {"error", "turn.failed"}:
                self.error = str(event.get("message") or event.get("error") or "Rodada falhou.")
        else:
            if kind == "system" and event.get("subtype") == "init":
                self.session = event.get("session_id", "")
                self.model = event.get("model", self.model)
                self.emit("session", self.session)
            elif kind in {"assistant", "user"}:
                for block in event.get("message", {}).get("content", []):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and kind == "assistant":
                        self.emit("agent_update", block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        args = block.get("input", {})
                        detail = args.get("command") or args.get("file_path") or args.get("path") or args.get("pattern") or ""
                        self.emit("tool_activity", f"{block.get('name')}: {detail}")
                    elif block.get("type") == "tool_result":
                        self.emit("tool_activity", str(block.get("content", ""))[-6000:])
            elif kind == "result":
                self.session = event.get("session_id", self.session)
                self.completed = not event.get("is_error") and event.get("subtype") == "success"
                self.answer = event.get("result", "")
                self.error = "; ".join(event.get("errors", []))
                usage = event.get("usage", {})
                keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
                if "input_tokens" in usage and all(type(usage.get(k, 0)) is int for k in keys):
                    self.tokens = sum(usage.get(k, 0) for k in keys)
                if event.get("permission_denials"):
                    self.emit("tool_activity", "Algumas ferramentas foram recusadas pelas permissões do CLI.")
            elif kind == "system" and event.get("subtype") == "permission_denied":
                self.emit("tool_activity", "Permissão recusada: " + str(event.get("tool_name", "ferramenta")))

    def reply(self):
        if not self.completed or not self.session or not self.answer:
            raise RuntimeError(self.error[:1000] or f"{self.agent} terminou sem resultado verificável.")
        return Reply({"text": self.answer}, self.session, self.model, self.tokens)


def develop(agent, prompt, cwd, session_id=None, on_event=None, cancel=None, timeout=1800):
    args, model = command(agent, session_id)
    cancel = cancel or threading.Event()
    events = Events(agent, model, on_event or (lambda *_: None))
    finished = threading.Event()
    timed_out = threading.Event()
    env = os.environ.copy()
    # Uma sessão dedicada não herda o marcador de uma sessão interativa Claude.
    env.pop("CLAUDECODE", None)
    with tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.Popen(args, cwd=Path(cwd), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=errors, text=True,
                                   encoding="utf-8", errors="replace", env=env,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def watch():
            deadline = time.monotonic() + timeout
            while not finished.wait(0.2):
                if cancel.is_set() or time.monotonic() >= deadline:
                    if not cancel.is_set():
                        timed_out.set()
                    stop_process_tree(process)
                    return
        monitor = threading.Thread(target=watch, daemon=True)
        monitor.start()
        try:
            events.emit("process", json.dumps({"pid": process.pid, "created": psutil.Process(process.pid).create_time()}))
            process.stdin.write(prompt)
            process.stdin.close()
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    events.consume(event)
            process.wait()
            if cancel.is_set():
                raise RuntimeError("Rodada interrompida pelo usuário; alterações já feitas permanecem no projeto.")
            if timed_out.is_set():
                raise RuntimeError("Tempo de execução esgotado; confira as alterações e testes no projeto.")
            if process.returncode:
                errors.seek(0)
                diagnostic = errors.read().decode("utf-8", errors="replace")
                # Não expor stderr cru, que pode carregar detalhes de configuração.
                detail = events.error or ("Falha no sandbox do Windows." if "sandbox" in diagnostic.lower() else "Confira login e permissões do CLI.")
                raise RuntimeError(f"{agent} encerrou com código {process.returncode}. {detail[:1000]}")
            return events.reply()
        finally:
            if process.poll() is None:
                stop_process_tree(process)
            finished.set()
            monitor.join(timeout=4)
            process.stdout.close()

