"""Execuções dedicadas dos CLIs; nunca injeta comandos em chats já abertos."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class Reply:
    data: dict
    session_id: str
    model: str
    tokens: int | None


def executable(agent):
    override = os.environ.get(f"NEBULA_COLLAB_{agent.upper()}_EXE", "")
    if override:
        path = Path(override)
        return str(path.resolve()) if path.is_file() and path.suffix.lower() == ".exe" else None
    names = {"codex": ("openai.chatgpt-*", "bin/windows-x86_64/codex.exe"),
             "opus": ("anthropic.claude-code-*", "resources/native-binary/claude.exe")}
    direct = shutil.which("codex.exe" if agent == "codex" else "claude.exe")
    if direct:
        return direct
    pattern, suffix = names[agent]
    roots = sorted((Path.home() / ".vscode" / "extensions").glob(pattern),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return next((str(p / suffix) for p in roots if (p / suffix).is_file()), None)


def availability():
    return {agent: {"available": executable(agent) is not None, "transport": "dedicated_cli",
                    "authentication": "checked_on_run", "model": os.getenv(
                        f"NEBULA_COLLAB_{agent.upper()}_MODEL", "opus" if agent == "opus" else "configured")}
            for agent in ("codex", "opus")}


def parse_codex(output, model):
    session, answer, usage = "", "", None
    completed = False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "thread.started":
            session = event.get("thread_id", "")
        elif event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message":
            answer = event["item"].get("text", "")
        elif event.get("type") == "turn.completed":
            completed = True
            raw = event.get("usage", {})
            if all(type(raw.get(k)) is int and raw[k] >= 0 for k in ("input_tokens", "output_tokens")):
                # Tokens de cache já estão incluídos em input_tokens do Codex.
                usage = raw["input_tokens"] + raw["output_tokens"]
    if not completed or not session or not answer:
        raise RuntimeError("Codex terminou sem confirmação verificável da rodada.")
    return Reply(_object(answer), session, model, usage)


def _object(value):
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, dict):
        raise RuntimeError("Resposta estruturada inválida do agente.")
    return result


def parse_claude(output, model):
    envelope = _object(output)
    if envelope.get("is_error") or envelope.get("subtype") != "success" or not envelope.get("session_id"):
        raise RuntimeError("Claude não concluiu a rodada; verifique autenticação e limites do CLI.")
    usage = envelope.get("usage", {})
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    measured = (sum(usage.get(k, 0) for k in keys)
                if all(type(usage.get(k, 0)) is int and usage.get(k, 0) >= 0 for k in keys)
                and "input_tokens" in usage and "output_tokens" in usage else None)
    models = list(envelope.get("modelUsage", {}))
    return Reply(_object(envelope.get("structured_output") or envelope.get("result")),
                 envelope["session_id"], ", ".join(models) or model, measured)


class CLIProvider:
    def __init__(self, timeout=240):
        self.timeout = timeout

    def develop(self, agent, prompt, cwd, **kwargs):
        from .development_transport import develop
        return develop(agent, prompt, cwd, **kwargs)

    def complete(self, agent, prompt, schema, cwd):
        command = executable(agent)
        if not command:
            raise RuntimeError(f"CLI de {agent} indisponível.")
        model = os.getenv(f"NEBULA_COLLAB_{agent.upper()}_MODEL", "opus" if agent == "opus" else "configured")
        with tempfile.TemporaryDirectory(prefix="nebula-collab-schema-") as temporary:
            schema_file = Path(temporary) / "response.json"
            schema_file.write_text(json.dumps(schema), encoding="utf-8")
            if agent == "codex":
                args = [command, "exec", "--json", "--ephemeral", "--sandbox", "read-only",
                        "--output-schema", str(schema_file), "--color", "never"]
                if model != "configured":
                    args += ["--model", model]
                args.append("-")
            else:
                args = [command, "--print", "--output-format", "json", "--model", model,
                        "--json-schema", json.dumps(schema), "--tools", "",
                        "--strict-mcp-config", "--no-session-persistence",
                        "--permission-mode", "dontAsk"]
            # O agente produz uma proposta de código. A aplicação é feita pelo
            # coordenador após validar arquivos, reservas e hashes de origem.
            result = subprocess.run(args, input=prompt, cwd=cwd, text=True,
                                    encoding="utf-8", errors="replace", capture_output=True,
                                    timeout=self.timeout, shell=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise RuntimeError(f"CLI de {agent} falhou (código {result.returncode}); confira login e disponibilidade.")
        return parse_codex(result.stdout, model) if agent == "codex" else parse_claude(result.stdout, model)
