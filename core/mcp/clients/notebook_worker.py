"""Cliente do worker MCP do notebook, usado pelo PC principal (secao 32 do GOAL).

O PC monta o envelope, assina o ticket, envia, acompanha e confere a correlacao
job_id + trace_id da resposta. O notebook nunca recebe mais que o envelope.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from functools import partial
from urllib.parse import urlparse

import anyio
import httpx2
import requests
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from core.capabilities.ticket import DEFAULT_TTL_SECONDS, TicketSigner
from nebula_worker.protocol.envelope import build_generate_envelope
from nebula_worker.protocol.result import TERMINAL_STATES, ResultError, parse_job_result

try:
    _GROUP = BaseExceptionGroup  # Python 3.11+
except NameError:  # pragma: no cover - Python 3.10 usa o backport do anyio
    from exceptiongroup import BaseExceptionGroup as _GROUP


class NotebookWorkerError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = dict(details or {})


class NotebookWorkerUnavailable(NotebookWorkerError):
    """O transporte falhou (worker desligado, rede, token recusado); nada foi executado a confirmar."""


def _unwrap(error: BaseException) -> BaseException:
    while isinstance(error, _GROUP) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    return error


def _http_status(error: BaseException) -> int | None:
    current: BaseException | None = error
    while current is not None:
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
        current = current.__cause__ or current.__context__
    return None


class _Session:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def call(self, name: str, arguments: dict, *, accept_rejection: bool = False) -> dict:
        result = await self._client.call_tool(name, arguments)
        payload = result.structured_content
        if not isinstance(payload, dict):
            text = "".join(getattr(block, "text", "") for block in result.content)
            try:
                payload = json.loads(text)
            except ValueError as exc:
                raise NotebookWorkerError("PROTOCOL_MISMATCH",
                                          "Resposta do worker sem JSON estruturado.") from exc
        if result.is_error and not (accept_rejection and payload.get("status") == "rejected"):
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            raise NotebookWorkerError(str(error.get("code") or "WORKER_ERROR"),
                                      str(error.get("message") or "Falha no worker do notebook."),
                                      error.get("details") if isinstance(error.get("details"), dict) else None)
        return payload


class NotebookWorkerClient:
    def __init__(self, url: str, token: str, signer: TicketSigner, *, request_timeout: float = 30.0,
                 ticket_ttl: int = DEFAULT_TTL_SECONDS, poll_interval: float = 1.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or not parsed.path.endswith("/mcp"):
            raise ValueError("URL do worker deve ser http(s)://host:porta/mcp.")
        if len(token) < 32:
            raise ValueError("Token do worker precisa de ao menos 32 caracteres.")
        self.url = url
        self._token = token
        self.signer = signer
        self.request_timeout = request_timeout
        self.ticket_ttl = ticket_ttl
        self.poll_interval = poll_interval

    @classmethod
    def from_env(cls, environ: dict | None = None, **options) -> "NotebookWorkerClient":
        env = os.environ if environ is None else environ
        url = str(env.get("NEBULA_NOTEBOOK_WORKER_URL", "")).strip()
        token = str(env.get("NEBULA_WORKER_TOKEN", "")).strip()
        if not url or not token:
            raise ValueError("Defina NEBULA_NOTEBOOK_WORKER_URL e NEBULA_WORKER_TOKEN no PC.")
        return cls(url, token, TicketSigner.load(), **options)

    @asynccontextmanager
    async def session(self):
        # O SDK transforma qualquer HTTP de erro em "Server returned an error
        # response"; o status real fica registrado aqui para o diagnostico.
        statuses: list[int] = []

        async def remember(response) -> None:
            statuses.append(response.status_code)

        try:
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {self._token}"},
                                          timeout=self.request_timeout,
                                          event_hooks={"response": [remember]}) as http:
                async with Client(streamable_http_client(self.url, http_client=http,
                                                         terminate_on_close=False)) as client:
                    yield _Session(client)
        except Exception as exc:  # noqa: BLE001 - classifica antes de propagar
            inner = _unwrap(exc)
            if isinstance(inner, NotebookWorkerError):
                raise inner from None
            status = statuses[-1] if statuses and statuses[-1] >= 400 else _http_status(inner)
            if status in (401, 403):
                raise NotebookWorkerUnavailable(
                    "UNAUTHORIZED", "O worker recusou este PC (token ou lista de clientes).") from exc
            if status == 429:
                raise NotebookWorkerUnavailable("RATE_LIMITED", "O worker limitou a taxa deste PC.") from exc
            if status == 421:
                raise NotebookWorkerUnavailable(
                    "HOST_REJECTED", "O worker recusou o Host da URL; confira host_names.") from exc
            raise NotebookWorkerUnavailable(
                "WORKER_UNREACHABLE", f"Worker do notebook indisponivel ({type(inner).__name__}).") from exc

    async def health(self) -> dict:
        async with self.session() as session:
            return await session.call("worker.health", {})

    async def capabilities(self) -> dict:
        async with self.session() as session:
            return await session.call("worker.capabilities", {})

    async def status(self, job_id: str) -> dict:
        async with self.session() as session:
            return await session.call("worker.status", {"job_id": job_id})

    async def result(self, job_id: str) -> dict:
        async with self.session() as session:
            return await session.call("worker.result", {"job_id": job_id})

    async def cancel(self, job_id: str) -> dict:
        async with self.session() as session:
            return await session.call("worker.cancel", {"job_id": job_id})

    async def run(self, envelope: dict, *, max_wait: float | None = None) -> dict:
        """Envia, acompanha e devolve o JobResult ja validado e correlacionado."""
        signed = self.signer.attach(envelope, ttl_seconds=self.ticket_ttl)
        job_id, trace_id = signed["job_id"], signed["trace_id"]
        budget = max_wait if max_wait is not None else signed["limits"]["timeout_ms"] / 1000 + 30
        deadline = time.monotonic() + budget
        async with self.session() as session:
            accepted = await session.call("worker.submit", {"envelope": signed}, accept_rejection=True)
            _correlate(accepted, job_id, trace_id)
            if accepted.get("status") == "rejected":
                error = accepted.get("error") if isinstance(accepted.get("error"), dict) else {}
                raise NotebookWorkerError(str(error.get("code") or "REJECTED"),
                                          str(error.get("message") or "Job recusado pelo worker."),
                                          error.get("details") if isinstance(error.get("details"), dict) else None)
            status = accepted.get("status")
            while status not in TERMINAL_STATES:
                if time.monotonic() >= deadline:
                    with anyio.CancelScope(shield=True):
                        try:
                            await session.call("worker.cancel", {"job_id": job_id})
                        except NotebookWorkerError:
                            pass
                    raise NotebookWorkerError("CLIENT_TIMEOUT", "O worker nao concluiu o job no prazo do PC.")
                await anyio.sleep(self.poll_interval)
                view = await session.call("worker.status", {"job_id": job_id})
                _correlate(view, job_id, trace_id)
                status = view.get("status")
            result = await session.call("worker.result", {"job_id": job_id})
        try:
            parse_job_result(result)
        except ResultError as exc:
            raise NotebookWorkerError("PROTOCOL_MISMATCH", str(exc)) from exc
        _correlate(result, job_id, trace_id)
        return result

    async def generate(self, prompt: str, **options) -> dict:
        return await self.run(build_generate_envelope(prompt, **options))

    def run_sync(self, envelope: dict, **options) -> dict:
        return anyio.run(partial(self.run, envelope, **options))

    def health_sync(self) -> dict:
        return anyio.run(self.health)


def _correlate(payload: dict, job_id: str, trace_id: str) -> None:
    if payload.get("job_id") != job_id or payload.get("trace_id") != trace_id:
        raise NotebookWorkerError("CORRELATION_MISMATCH",
                                  "Resposta do worker nao corresponde ao job enviado.")


class NotebookWorkerChat:
    """Mesma interface do ``OllamaClient`` das sprints, mas passando pelo worker.

    Serve para o reviewer das sprints deixar de falar HTTP direto com o Ollama
    do notebook (secao 19 do GOAL). ``num_gpu``/``num_thread`` sao ignorados de
    proposito: hardware do notebook e decisao do notebook.
    """

    def __init__(self, client: NotebookWorkerClient, *, model_alias: str = "qwen_edge",
                 think: bool = False, timeout: int = 600) -> None:
        self.client = client
        self.model = model_alias
        self.host = client.url
        self.think = think
        self.timeout = timeout

    def chat(self, prompt: str, system: str | None = None, temperature: float = 0.1,
             num_ctx: int = 8192, num_predict: int | None = None,
             format_schema: dict | None = None, seed: int | None = None,
             num_gpu: int | None = None, num_thread: int | None = None) -> str:
        envelope = build_generate_envelope(
            prompt, model_alias=self.model, system=system,
            output_format="json" if format_schema is not None else "text", schema=format_schema,
            timeout_ms=self.timeout * 1000, max_output_tokens=num_predict or 2048,
            temperature=temperature, seed=seed, context_tokens=num_ctx, think=self.think,
        )
        try:
            result = self.client.run_sync(envelope)
        except NotebookWorkerUnavailable as exc:
            # As sprints abrem o circuit breaker em RequestException; mesma semantica.
            raise requests.ConnectionError(str(exc)) from exc
        except NotebookWorkerError as exc:
            if exc.code in {"MODEL_UNAVAILABLE", "MODEL_TIMEOUT", "QUEUE_FULL", "CLIENT_TIMEOUT"}:
                raise requests.ConnectionError(str(exc)) from exc
            raise ValueError(str(exc)) from exc
        if result["status"] != "completed":
            error = result["error"] or {}
            message = f"{error.get('code')}: {error.get('message')}"
            if error.get("code") in {"MODEL_UNAVAILABLE", "MODEL_TIMEOUT", "DEADLINE_EXCEEDED"}:
                raise requests.ConnectionError(message)
            raise ValueError(message)
        output = result["output"]
        if output["format"] == "json":
            return json.dumps(output["payload"], ensure_ascii=False)
        return str(output["payload"])

    def is_alive(self) -> bool:
        try:
            health = self.client.health_sync()
        except NotebookWorkerError:
            return False
        model = (health.get("models") or {}).get(self.model) or {}
        return bool(health.get("ok")) and bool(model.get("available"))
