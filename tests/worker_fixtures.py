"""Apoio dos testes do worker do notebook: chaves, envelopes assinados e dubles."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.capabilities.ticket import TicketSigner
from nebula_worker.capabilities.validator import TicketValidator
from nebula_worker.models.ollama_client import GenerationOutput
from nebula_worker.models.registry import ModelRegistry
from nebula_worker.observability.audit import AuditLog
from nebula_worker.protocol.envelope import build_generate_envelope
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.sandbox.workspace import Workspaces
from nebula_worker.worker.dispatcher import Dispatcher, Limits

SCOPE = "model:qwen_edge:generate"


def make_signer() -> TicketSigner:
    return TicketSigner(Ed25519PrivateKey.generate())


def signed_envelope(signer: TicketSigner, prompt: str = "diga oi", **options) -> dict:
    return signer.attach(build_generate_envelope(prompt, **options))


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.01) -> bool:
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeRunner:
    """Executor falso: registra o pedido e responde sem rede nem modelo."""

    operations = frozenset({"generate"})

    def __init__(self, text: str = '{"ok": true}', stop_reason: str = "stop") -> None:
        self.output = GenerationOutput(text, 7, 5, stop_reason)
        self.requests = []
        self.available = True
        self.block = threading.Event()
        self.started = threading.Event()
        self.error: WorkerError | None = None

    def is_available(self) -> bool:
        return self.available

    def generate(self, request, *, cancel, deadline):
        self.requests.append(request)
        self.started.set()
        while self.block.is_set():
            if cancel.is_set():
                raise WorkerError(ErrorCode.CANCELLED, "cancelado")
            if time.monotonic() >= deadline:
                raise WorkerError(ErrorCode.MODEL_TIMEOUT, "prazo")
            time.sleep(0.005)
        if self.error is not None:
            raise self.error
        return self.output


def make_dispatcher(root: Path, runner: FakeRunner, signer: TicketSigner, *,
                    limits: Limits | None = None, replay_file: Path | None = None,
                    autostart: bool = True) -> tuple[Dispatcher, AuditLog]:
    audit = AuditLog(root / "audit.jsonl")
    validator = TicketValidator(
        {signer.key_id: signer.public_key}, frozenset({SCOPE}),
        max_ttl_seconds=600, clock_skew_seconds=60, replay_file=replay_file,
    )
    dispatcher = Dispatcher(
        models=ModelRegistry({"qwen_edge": runner}), validator=validator,
        workspaces=Workspaces(root / "jobs"), audit=audit, limits=limits or Limits(),
        autostart=autostart,
    )
    return dispatcher, audit


class FakeOllama:
    """Ollama falso em loopback, com streaming NDJSON como o original."""

    def __init__(self, pieces=('{"ok"', ": true}"), done_reason: str = "stop", status: int = 200,
                 hold: threading.Event | None = None) -> None:
        self.pieces = list(pieces)
        self.done_reason = done_reason
        self.status = status
        self.hold = hold
        self.requests: list[dict] = []
        self.disconnected = threading.Event()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_GET(self):
                body = b'{"models": []}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                fake.requests.append(json.loads(self.rfile.read(length)))
                if fake.status != 200:
                    body = json.dumps({"error": "model 'x' not found"}).encode()
                    self.send_response(fake.status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    for piece in fake.pieces:
                        self._chunk({"message": {"role": "assistant", "content": piece}, "done": False})
                    if fake.hold is not None:
                        # Mantem o streaming aberto ate o cliente desconectar.
                        while fake.hold.is_set():
                            self._chunk({"message": {"role": "assistant", "content": " "}, "done": False})
                            time.sleep(0.02)
                    self._chunk({"message": {"role": "assistant", "content": ""}, "done": True,
                                 "done_reason": fake.done_reason, "prompt_eval_count": 11,
                                 "eval_count": 6})
                    self.wfile.write(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    fake.disconnected.set()

            def _chunk(self, value: dict) -> None:
                data = (json.dumps(value) + "\n").encode()
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

        class QuietServer(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                # Conexao derrubada de proposito nos testes de cancelamento.
                pass

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "FakeOllama":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        if self.hold is not None:
            self.hold.clear()
        self.server.shutdown()
        self.server.server_close()
