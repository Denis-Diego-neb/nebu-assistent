"""Recebe, valida, enfileira, executa, limita, cancela, devolve, limpa e audita.

E a lista da secao 28 do GOAL, e so ela. O dispatcher nao conhece MCP nem
HTTP: o gateway traduz chamadas de rede para estes metodos, e os testes os
exercitam direto. Um job por vez: o notebook tem uma CPU/GPU para o modelo e
duas geracoes simultaneas so deixariam as duas lentas.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

from nebula_worker import WORKER_VERSION
from nebula_worker.capabilities.validator import TicketValidator
from nebula_worker.jobs.store import JobRecord, JobStore
from nebula_worker.models.ollama_client import GenerationRequest
from nebula_worker.models.registry import ModelRegistry
from nebula_worker.observability.audit import AuditLog
from nebula_worker.protocol.envelope import JobEnvelope, parse_envelope
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ids import is_ulid
from nebula_worker.protocol.result import TERMINAL_STATES, job_accepted, job_result
from nebula_worker.protocol.version import PROTOCOL_VERSION, SUPPORTED_VERSIONS
from nebula_worker.sandbox.workspace import Workspaces
from nebula_worker.worker.result_filter import clean


@dataclass(frozen=True)
class Limits:
    max_input_chars: int = 60_000
    max_output_tokens: int = 4096
    max_timeout_ms: int = 900_000
    max_context_tokens: int = 32_768
    max_queue: int = 8
    result_ttl_seconds: int = 900
    forget_after_seconds: int = 3600
    max_result_bytes: int = 262_144
    max_ticket_ttl_seconds: int = 600
    clock_skew_seconds: int = 60
    cancel_wait_seconds: float = 3.0

    def public(self) -> dict[str, int]:
        return {
            "max_input_chars": self.max_input_chars,
            "max_output_tokens": self.max_output_tokens,
            "max_timeout_ms": self.max_timeout_ms,
            "max_context_tokens": self.max_context_tokens,
            "max_queue": self.max_queue,
            "result_ttl_seconds": self.result_ttl_seconds,
            "max_ticket_ttl_seconds": self.max_ticket_ttl_seconds,
        }


class Dispatcher:
    def __init__(self, *, models: ModelRegistry, validator: TicketValidator, workspaces: Workspaces,
                 audit: AuditLog, limits: Limits, monotonic=time.monotonic,
                 autostart: bool = True) -> None:
        self.models = models
        self.validator = validator
        self.workspaces = workspaces
        self.audit = audit
        self.limits = limits
        self.monotonic = monotonic
        self._store = JobStore()
        self._condition = threading.Condition()
        self._running: JobRecord | None = None
        self._closed = False
        self._started = monotonic()
        self._thread = threading.Thread(target=self._loop, name="nebula-worker-runner", daemon=True)
        if autostart:
            self.start()

    # ------------------------------------------------------------------ ciclo

    def start(self) -> None:
        self.workspaces.sweep()
        self._thread.start()
        self.audit.record("started")

    def close(self, timeout: float = 10.0) -> None:
        with self._condition:
            self._closed = True
            if self._running is not None:
                self._running.cancel.set()
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout)
        self.audit.record("stopped")

    # ----------------------------------------------------------- operacoes MCP

    def submit(self, raw: object) -> dict:
        try:
            envelope = parse_envelope(raw)
        except WorkerError as exc:
            job_id = raw.get("job_id") if isinstance(raw, dict) and is_ulid(raw.get("job_id")) else None
            trace_id = raw.get("trace_id") if isinstance(raw, dict) and is_ulid(raw.get("trace_id")) else None
            return self._reject(job_id, trace_id, exc)
        with self._condition:
            known = self._known(envelope)
        if known is not None:
            return known
        try:
            # Ticket antes da politica: quem nao tem ticket valido nao descobre
            # quais modelos ou limites existem aqui.
            ticket = self.validator.validate(envelope)
            self._check_policy(envelope)
        except WorkerError as exc:
            return self._reject(envelope.job_id, envelope.trace_id, exc)
        with self._condition:
            known = self._known(envelope)
            if known is not None:
                return known
            if self._closed:
                return self._reject(envelope.job_id, envelope.trace_id,
                                    WorkerError(ErrorCode.INTERNAL_ERROR, "Worker encerrando."))
            if self._store.count("queued") >= self.limits.max_queue:
                return self._reject(envelope.job_id, envelope.trace_id,
                                    WorkerError(ErrorCode.QUEUE_FULL, "Fila do worker cheia; tente depois."))
            try:
                self.validator.consume(ticket)
            except WorkerError as exc:
                return self._reject(envelope.job_id, envelope.trace_id, exc)
            now = self.monotonic()
            record = JobRecord(
                job_id=envelope.job_id, trace_id=envelope.trace_id,
                model_alias=envelope.model_alias, operation=envelope.operation,
                digest=envelope.digest, ticket_id=ticket.ticket_id, accepted_at=now,
                # O prazo corre desde o aceite: resultado que chegaria tarde demais
                # para o PC nao ocupa a fila nem o modelo.
                deadline=now + envelope.limits.timeout_ms / 1000,
                envelope=envelope,
            )
            self._store.add(record)
            position = self._queue_position(record)
            self._condition.notify_all()
        self.audit.record("accepted", job_id=record.job_id, trace_id=record.trace_id,
                          model_alias=record.model_alias, operation=record.operation,
                          ticket_id=ticket.ticket_id, key_id=ticket.key_id, queue_depth=position)
        return job_accepted(job_id=record.job_id, trace_id=record.trace_id, status="queued",
                            queue_position=position)

    def status(self, job_id: object) -> dict:
        with self._condition:
            record = self._record(job_id)
            view = {
                "protocol_version": PROTOCOL_VERSION,
                "job_id": record.job_id,
                "trace_id": record.trace_id,
                "status": record.state,
                "elapsed_ms": int((self.monotonic() - record.accepted_at) * 1000),
            }
            if record.state == "queued":
                view["queue_position"] = self._queue_position(record)
            return view

    def result(self, job_id: object) -> dict:
        with self._condition:
            record = self._record(job_id)
            if record.state not in TERMINAL_STATES:
                raise WorkerError(ErrorCode.NOT_READY, f"Job ainda em {record.state}.",
                                  {"status": record.state})
            if record.state == "expired":
                return job_result(
                    job_id=record.job_id, trace_id=record.trace_id, status="expired",
                    error=WorkerError(ErrorCode.EXPIRED, "Resultado expirado no worker.").to_dict(),
                )
            return job_result(job_id=record.job_id, trace_id=record.trace_id, status=record.state,
                              output=record.output, usage=record.usage, error=record.error)

    def cancel(self, job_id: object) -> dict:
        cancelled_queued = None
        with self._condition:
            record = self._record(job_id)
            if record.state == "queued":
                record.cancel.set()
                self._finish(record, "cancelled",
                             error=WorkerError(ErrorCode.CANCELLED, "Job cancelado antes de iniciar."))
                cancelled_queued = record
            elif record.state == "running":
                record.cancel.set()
                limit = self.monotonic() + self.limits.cancel_wait_seconds
                while record.state == "running" and self.monotonic() < limit:
                    self._condition.wait(0.1)
            view = {"job_id": record.job_id, "trace_id": record.trace_id,
                    "status": record.state, "cancelled": record.state == "cancelled"}
        if cancelled_queued is not None:
            self.audit.record("cancelled", job_id=record.job_id, trace_id=record.trace_id,
                              error_code=ErrorCode.CANCELLED)
        return view

    def health(self) -> dict:
        with self._condition:
            queued = self._store.count("queued")
            running = self._running is not None
        return {
            "ok": True,
            "service": "nebula-worker",
            "worker_version": WORKER_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "uptime_s": int(self.monotonic() - self._started),
            "queue_depth": queued,
            "running": running,
            "models": self.models.availability(),
        }

    def capabilities(self) -> dict:
        return {
            "protocol_versions": list(SUPPORTED_VERSIONS),
            "models": {alias: {"operations": operations}
                       for alias, operations in self.models.operations().items()},
            "output_formats": ["text", "json"],
            "limits": self.limits.public(),
            "remote_shell": False,
            "remote_filesystem": False,
        }

    # ----------------------------------------------------------------- interno

    def _known(self, envelope: JobEnvelope) -> dict | None:
        existing = self._store.get(envelope.job_id)
        if existing is None:
            return None
        if existing.digest != envelope.digest:
            return self._reject(envelope.job_id, envelope.trace_id,
                                WorkerError(ErrorCode.DUPLICATE_JOB, "job_id ja usado com outro conteudo."))
        # Reenvio identico depois de um timeout de rede: devolve o estado atual
        # em vez de executar de novo (idempotencia pelo job_id + hash).
        view = job_accepted(job_id=existing.job_id, trace_id=existing.trace_id, status=existing.state)
        if existing.state == "queued":
            view["queue_position"] = self._queue_position(existing)
        return view

    def _reject(self, job_id: str | None, trace_id: str | None, error: WorkerError) -> dict:
        self.audit.record("rejected", job_id=job_id, trace_id=trace_id, error_code=error.code)
        return job_accepted(job_id=job_id, trace_id=trace_id, status="rejected", error=error.to_dict())

    def _check_policy(self, envelope: JobEnvelope) -> None:
        runner = self.models.get(envelope.model_alias)
        if envelope.operation not in runner.operations:
            raise WorkerError(ErrorCode.UNSUPPORTED_OPERATION, "Operacao nao suportada por este modelo.")
        size = len(envelope.input.payload) + len(envelope.input.system or "")
        if size > self.limits.max_input_chars:
            raise WorkerError(ErrorCode.LIMIT_EXCEEDED, "Entrada maior que o limite do worker.",
                              {"max_input_chars": self.limits.max_input_chars})
        if envelope.limits.max_output_tokens > self.limits.max_output_tokens:
            raise WorkerError(ErrorCode.LIMIT_EXCEEDED, "max_output_tokens acima do limite do worker.",
                              {"max_output_tokens": self.limits.max_output_tokens})
        if envelope.limits.timeout_ms > self.limits.max_timeout_ms:
            raise WorkerError(ErrorCode.LIMIT_EXCEEDED, "timeout_ms acima do limite do worker.",
                              {"max_timeout_ms": self.limits.max_timeout_ms})
        context = envelope.generation.context_tokens
        if context is not None and context > self.limits.max_context_tokens:
            raise WorkerError(ErrorCode.LIMIT_EXCEEDED, "context_tokens acima do limite do worker.",
                              {"max_context_tokens": self.limits.max_context_tokens})

    def _record(self, job_id: object) -> JobRecord:
        record = self._store.get(job_id) if is_ulid(job_id) else None
        if record is None:
            raise WorkerError(ErrorCode.JOB_NOT_FOUND, "Job desconhecido neste worker.")
        return record

    def _queue_position(self, record: JobRecord) -> int:
        for index, waiting in enumerate(self._store.queued(), start=1):
            if waiting is record:
                return index
        return 0

    def _finish(self, record: JobRecord, status: str, *, output: dict | None = None,
                usage: dict | None = None, error: WorkerError | None = None) -> None:
        record.output = output if status == "completed" else None
        record.usage = usage
        record.error = error.to_dict() if error is not None and status != "completed" else None
        self._store.transition(record, status, self.monotonic())
        self._condition.notify_all()

    def _loop(self) -> None:
        while True:
            expired: list[JobRecord] = []
            late: JobRecord | None = None
            record: JobRecord | None = None
            envelope: JobEnvelope | None = None
            with self._condition:
                while not self._closed and record is None and late is None and not expired:
                    expired = self._store.expire(
                        self.monotonic(), self.limits.result_ttl_seconds,
                        self.limits.forget_after_seconds,
                    )
                    waiting = self._store.queued()
                    if waiting:
                        candidate = waiting[0]
                        if self.monotonic() >= candidate.deadline:
                            self._finish(candidate, "failed", error=WorkerError(
                                ErrorCode.DEADLINE_EXCEEDED, "O prazo do job acabou antes da execucao."))
                            late = candidate
                        else:
                            self._store.transition(candidate, "running", self.monotonic())
                            self._running = candidate
                            record, envelope = candidate, candidate.envelope
                    elif not expired:
                        self._condition.wait(1.0)
                if self._closed:
                    return
            for item in expired:
                self.audit.record("expired", job_id=item.job_id, trace_id=item.trace_id)
            if late is not None:
                self.audit.record("failed", job_id=late.job_id, trace_id=late.trace_id,
                                  error_code=ErrorCode.DEADLINE_EXCEEDED)
            if record is not None and envelope is not None:
                self.audit.record("running", job_id=record.job_id, trace_id=record.trace_id,
                                  model_alias=record.model_alias)
                self._execute(record, envelope)

    def _execute(self, record: JobRecord, envelope: JobEnvelope) -> None:
        started = self.monotonic()
        status, output, usage, error = "failed", None, None, None
        try:
            self.workspaces.create(record.job_id)
            runner = self.models.get(envelope.model_alias)
            generated = runner.generate(GenerationRequest(
                prompt=envelope.input.payload,
                system=envelope.input.system,
                output_format=envelope.output.format,
                schema=envelope.output.schema,
                max_output_tokens=envelope.limits.max_output_tokens,
                temperature=envelope.generation.temperature,
                seed=envelope.generation.seed,
                context_tokens=envelope.generation.context_tokens,
                think=envelope.generation.think,
            ), cancel=record.cancel, deadline=record.deadline)
            usage = {"input_tokens": generated.input_tokens,
                     "output_tokens": generated.output_tokens,
                     "stop_reason": generated.stop_reason}
            output = clean(generated, envelope.output, self.limits.max_result_bytes)
            status = "completed"
        except WorkerError as exc:
            error = exc
            status = "cancelled" if exc.code == ErrorCode.CANCELLED else "failed"
        except Exception as exc:  # noqa: BLE001 - nenhum traceback sai do notebook
            error = WorkerError(ErrorCode.INTERNAL_ERROR, f"Falha interna do worker ({type(exc).__name__}).")
        finally:
            self.workspaces.cleanup(record.job_id)
        usage = {**(usage or {}), "latency_ms": int((self.monotonic() - started) * 1000)}
        with self._condition:
            if status != "completed" and record.cancel.is_set():
                status = "cancelled"
                error = WorkerError(ErrorCode.CANCELLED, "Job cancelado a pedido do PC.")
            self._finish(record, status, output=output, usage=usage, error=error)
            self._running = None
        self.audit.record(
            status, job_id=record.job_id, trace_id=record.trace_id, model_alias=record.model_alias,
            error_code=error.code if error is not None and status != "completed" else None,
            latency_ms=usage.get("latency_ms"), input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"), stop_reason=usage.get("stop_reason"),
            result_bytes=_result_bytes(output) if status == "completed" else None,
        )


def _result_bytes(output: dict | None) -> int | None:
    if output is None:
        return None
    try:
        return len(json.dumps(output.get("payload"), ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return None
