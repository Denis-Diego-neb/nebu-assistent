"""Qwen Edge via Ollama local: so o prompt isolado do job chega ao modelo.

A resposta vem em streaming. Cancelamento e prazo fecham o socket a partir de
outra thread: a leitura bloqueada termina na hora e o Ollama, ao perceber a
desconexao, para de gerar. Assim um job cancelado nao continua ocupando a CPU
do notebook ate o fim da resposta.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from nebula_worker.protocol.errors import ErrorCode, WorkerError

# Opcoes que dependem do pedido. As demais (threads, GPU) sao decisao local do
# notebook e vem so da configuracao dele; o PC nao escolhe hardware alheio.
REQUEST_OPTIONS = frozenset({"num_predict", "temperature", "seed", "num_ctx"})


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    system: str | None
    output_format: str
    schema: dict | None
    max_output_tokens: int
    temperature: float | None = None
    seed: int | None = None
    context_tokens: int | None = None
    think: bool | None = None


@dataclass(frozen=True)
class GenerationOutput:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    stop_reason: str | None


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


class OllamaRunner:
    operations = frozenset({"generate"})

    def __init__(self, base_url: str, model: str, *, options: dict | None = None,
                 keep_alive: str = "30m", connect_timeout: float = 5.0,
                 max_response_bytes: int = 2_000_000) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("base_url do Ollama precisa ser http://host:porta.")
        self.host = parsed.hostname
        self.port = parsed.port or 11434
        self.model = model
        self.options = dict(options or {})
        self.keep_alive = keep_alive
        self.connect_timeout = connect_timeout
        self.max_response_bytes = max_response_bytes

    def is_available(self, timeout: float = 2.0) -> bool:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request("GET", "/api/tags")
            response = connection.getresponse()
            response.read(65_536)
            return response.status == 200
        except (OSError, http.client.HTTPException):
            return False
        finally:
            connection.close()

    def body(self, request: GenerationRequest) -> dict:
        options = {key: value for key, value in self.options.items() if key not in REQUEST_OPTIONS}
        options["num_predict"] = request.max_output_tokens
        for key, value in (("temperature", request.temperature), ("seed", request.seed),
                           ("num_ctx", request.context_tokens)):
            if value is not None:
                options[key] = value
            elif key in self.options:
                options[key] = self.options[key]
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        body: dict = {
            "model": self.model, "messages": messages, "stream": True,
            "keep_alive": self.keep_alive, "options": options,
        }
        if request.think is not None:
            body["think"] = request.think
        if request.output_format == "json":
            body["format"] = request.schema if request.schema is not None else "json"
        return body

    def generate(self, request: GenerationRequest, *, cancel: threading.Event,
                 deadline: float) -> GenerationOutput:
        if cancel.is_set():
            raise WorkerError(ErrorCode.CANCELLED, "Job cancelado antes de iniciar.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkerError(ErrorCode.MODEL_TIMEOUT, "Prazo do job esgotado antes da execucao.")
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.connect_timeout)
        state = {"reason": None}
        guard = threading.Lock()
        finished = threading.Event()

        def interrupt(reason: str) -> None:
            with guard:
                if state["reason"] is None:
                    state["reason"] = reason
            sock = connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def watch_cancel() -> None:
            while not finished.wait(0.2):
                if cancel.is_set():
                    interrupt("cancelled")
                    return

        def interrupted() -> None:
            # Prazo ou cancelamento que chegaram durante o connect nao tinham
            # socket para fechar; conferidos aqui, antes de enviar o prompt.
            if state["reason"] is not None:
                raise OSError("Execucao interrompida antes do envio.")

        timer = threading.Timer(remaining, interrupt, args=("timeout",))
        timer.daemon = True
        watcher = threading.Thread(target=watch_cancel, name="nebula-worker-cancel", daemon=True)
        timer.start()
        watcher.start()
        try:
            return self._stream(connection, request, interrupt, interrupted)
        except WorkerError:
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            reason = state["reason"]
            if reason == "cancelled":
                raise WorkerError(ErrorCode.CANCELLED, "Job cancelado a pedido do PC.") from exc
            if reason == "timeout":
                raise WorkerError(ErrorCode.MODEL_TIMEOUT, "O modelo excedeu o prazo do job.") from exc
            if isinstance(exc, OSError) and connection.sock is None:
                raise WorkerError(ErrorCode.MODEL_UNAVAILABLE, "O Ollama local nao respondeu.") from exc
            raise WorkerError(ErrorCode.MODEL_ERROR,
                              f"Falha na comunicacao com o Ollama ({type(exc).__name__}).") from exc
        finally:
            finished.set()
            timer.cancel()
            connection.close()

    def _stream(self, connection: http.client.HTTPConnection, request: GenerationRequest,
                interrupt, interrupted) -> GenerationOutput:
        payload = json.dumps(self.body(request), ensure_ascii=False).encode("utf-8")
        connection.connect()
        # Conectado: a leitura passa a bloquear sem limite proprio; prazo e
        # cancelamento chegam pelo shutdown do socket.
        connection.sock.settimeout(None)
        interrupted()
        connection.request("POST", "/api/chat", body=payload,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            detail = response.read(4096)
            if response.status == 404:
                raise WorkerError(ErrorCode.MODEL_UNAVAILABLE,
                                  "Modelo configurado nao esta instalado no Ollama.")
            raise WorkerError(ErrorCode.MODEL_ERROR,
                              f"Ollama respondeu HTTP {response.status}.",
                              {"ollama_error": _ollama_error(detail)})
        parts: list[str] = []
        size = 0
        final: dict | None = None
        for raw_line in response:
            line = raw_line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            if not isinstance(chunk, dict):
                raise ValueError("Linha de streaming invalida.")
            if chunk.get("error"):
                raise WorkerError(ErrorCode.MODEL_ERROR, "O Ollama interrompeu a geracao.",
                                  {"ollama_error": str(chunk["error"])[:300]})
            message = chunk.get("message") if isinstance(chunk.get("message"), dict) else {}
            piece = message.get("content") or ""
            if isinstance(piece, str) and piece:
                size += len(piece.encode("utf-8"))
                if size > self.max_response_bytes:
                    interrupt("too_large")
                    raise WorkerError(ErrorCode.OUTPUT_TOO_LARGE,
                                      "A resposta do modelo excedeu o limite do worker.")
                parts.append(piece)
            if chunk.get("done"):
                final = chunk
                break
        if final is None:
            raise ValueError("O streaming terminou sem a mensagem final do Ollama.")
        stop_reason = final.get("done_reason")
        return GenerationOutput(
            text="".join(parts),
            input_tokens=_count(final.get("prompt_eval_count")),
            output_tokens=_count(final.get("eval_count")),
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        )


def _ollama_error(detail: bytes) -> str:
    try:
        value = json.loads(detail.decode("utf-8", errors="replace"))
    except ValueError:
        return ""
    return str(value.get("error", ""))[:300] if isinstance(value, dict) else ""
