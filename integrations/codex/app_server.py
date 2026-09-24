"""Cliente minimo do Codex app-server para supervisao excepcional das Qwen."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import websocket


class CodexAppServerClient:
    def __init__(
        self,
        url: str = "ws://127.0.0.1:4500",
        timeout: int = 300,
        model: str = "gpt-5.6-terra",
        effort: str = "low",
    ):
        if not url.startswith(("ws://127.0.0.1:", "ws://localhost:")):
            raise ValueError("O supervisor Codex deve usar um app-server local.")
        self.url = url
        self.timeout = timeout
        self.model = model
        self.effort = effort
        self._next_id = 1
        self._socket: Any = None
        self._pending: list[dict[str, Any]] = []

    def __enter__(self) -> "CodexAppServerClient":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> None:
        if self._socket is not None:
            return
        self._socket = websocket.create_connection(
            self.url,
            timeout=self.timeout,
            suppress_origin=True,
            http_proxy_host=None,
            http_proxy_port=None,
        )
        self._request("initialize", {
            "clientInfo": {
                "name": "nebula-autopilot",
                "title": "Nebula Autopilot",
                "version": "0.1.0",
            },
            "capabilities": None,
        })
        self._socket.send(json.dumps({"method": "initialized"}))

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _receive(self) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("Codex app-server nao conectado.")
        message = json.loads(self._socket.recv())
        if not isinstance(message, dict):
            raise RuntimeError("Mensagem invalida do Codex app-server.")
        return message

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("Codex app-server nao conectado.")
        request_id = self._next_id
        self._next_id += 1
        self._socket.send(json.dumps({"id": request_id, "method": method, "params": params}))
        while True:
            message = self._receive()
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"Codex app-server recusou {method}: {message['error']}")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError(f"Resposta invalida para {method}.")
                return result
            if "id" in message and "method" in message:
                self._socket.send(json.dumps({
                    "id": message["id"],
                    "error": {"code": -32601, "message": "Nebula supervisor nao executa callbacks."},
                }))
                raise RuntimeError("Codex solicitou uma acao nao permitida no modo supervisor.")
            self._pending.append(message)

    def supervise(
        self,
        prompt: str,
        *,
        cwd: Path,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        """Executa uma rodada efemera, read-only e sem aprovacoes de comandos."""
        return self.complete(
            prompt,
            cwd=cwd,
            output_schema=output_schema,
            developer_instructions=(
                "Atue apenas como supervisor das IAs locais da Nebula. Analise o material "
                "fornecido, nao edite arquivos e nao execute comandos. Responda no schema pedido."
            ),
        )

    def complete(
        self,
        prompt: str,
        *,
        cwd: Path,
        output_schema: dict[str, Any] | None = None,
        developer_instructions: str,
    ) -> str:
        """Executa uma resposta estruturada sem permitir escrita ou comandos."""
        self.connect()
        started = self._request("thread/start", {
            "model": self.model,
            "cwd": str(cwd.resolve()),
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "developerInstructions": developer_instructions,
        })
        thread = started.get("thread", {})
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError("Codex nao retornou threadId.")
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
            "effort": self.effort,
            "summary": "concise",
        }
        if output_schema is not None:
            params["outputSchema"] = output_schema
        self._request("turn/start", params)

        pieces: list[str] = []
        messages = self._pending
        self._pending = []
        while True:
            message = messages.pop(0) if messages else self._receive()
            method = message.get("method")
            if method == "item/agentMessage/delta":
                delta = message.get("params", {}).get("delta")
                if isinstance(delta, str):
                    pieces.append(delta)
            elif method == "turn/completed":
                turn = message.get("params", {}).get("turn", {})
                if turn.get("status") != "completed":
                    raise RuntimeError(
                        f"Turno Codex terminou com status {turn.get('status')}: {turn.get('error')}"
                    )
                answer = "".join(pieces).strip()
                if not answer:
                    raise RuntimeError("Codex terminou sem resposta textual.")
                return answer
            elif "id" in message and "method" in message:
                self._socket.send(json.dumps({
                    "id": message["id"],
                    "error": {"code": -32601, "message": "Callback bloqueado pelo supervisor."},
                }))
                raise RuntimeError("Codex solicitou uma acao no modo supervisor read-only.")


def app_server_ready(url: str, timeout: float = 1.0) -> bool:
    """Consulta o readyz correspondente a um app-server WebSocket local."""
    if not url.startswith(("ws://127.0.0.1:", "ws://localhost:")):
        return False
    ready_url = "http://" + url.removeprefix("ws://").rstrip("/") + "/readyz"
    try:
        with urlopen(ready_url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def ensure_local_app_server(url: str, *, log_path: Path, startup_timeout: int = 20) -> bool:
    """Inicia o app-server local sob demanda e aguarda o readyz."""
    if app_server_ready(url):
        return True
    if not url.startswith(("ws://127.0.0.1:", "ws://localhost:")):
        raise ValueError("O app-server reserva deve escutar apenas no loopback.")
    executable = shutil.which("codex")
    if not executable:
        return False
    command = [executable, "app-server", "--listen", url]
    if os.name == "nt" and Path(executable).suffix.casefold() in {".cmd", ".bat"}:
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", *command]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=log_path.parent.parent,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if app_server_ready(url):
            return True
        time.sleep(0.25)
    process.terminate()
    return False
