"""JobResult, JobAccepted e JobStatus: as unicas respostas que o worker devolve."""

from __future__ import annotations

from nebula_worker.protocol.errors import ALL_CODES
from nebula_worker.protocol.ids import is_ulid
from nebula_worker.protocol.version import PROTOCOL_VERSION

STATES = (
    "received", "validating", "queued", "running",
    "completed", "failed", "cancelled", "rejected", "expired",
)
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "rejected", "expired"})
_RESULT_KEYS = frozenset({"protocol_version", "job_id", "trace_id", "status", "output", "usage", "error"})
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "latency_ms", "stop_reason"})


class ResultError(ValueError):
    """Resposta do worker fora do contrato; o PC nao deve confiar nela."""


def job_result(*, job_id: str, trace_id: str, status: str, output: dict | None = None,
               usage: dict | None = None, error: dict | None = None) -> dict:
    """Sucesso e erro sao mutuamente exclusivos: ``output`` so existe em completed."""
    result = {
        "protocol_version": PROTOCOL_VERSION,
        "job_id": job_id,
        "trace_id": trace_id,
        "status": status,
        "output": output,
        "usage": usage,
        "error": error,
    }
    parse_job_result(result)
    return result


def parse_job_result(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != _RESULT_KEYS:
        raise ResultError("JobResult com campos diferentes do contrato.")
    if raw["protocol_version"] != PROTOCOL_VERSION:
        raise ResultError("JobResult com versao de protocolo inesperada.")
    if not is_ulid(raw["job_id"]) or not is_ulid(raw["trace_id"]):
        raise ResultError("JobResult sem job_id/trace_id validos.")
    status = raw["status"]
    if status not in TERMINAL_STATES:
        raise ResultError("JobResult precisa de status terminal.")
    output, error = raw["output"], raw["error"]
    if status == "completed":
        if not isinstance(output, dict) or error is not None:
            raise ResultError("Resultado completed exige output e nenhum error.")
        if output.get("format") not in ("text", "json") or "payload" not in output:
            raise ResultError("output precisa de format e payload.")
        if not set(output) <= {"format", "payload", "truncated"}:
            raise ResultError("output com campos desconhecidos.")
    else:
        if output is not None or not isinstance(error, dict):
            raise ResultError("Resultado sem sucesso exige error e nenhum output.")
        if error.get("code") not in ALL_CODES or not isinstance(error.get("message"), str):
            raise ResultError("error precisa de code conhecido e message.")
        if not set(error) <= {"code", "message", "details"}:
            raise ResultError("error com campos desconhecidos.")
    usage = raw["usage"]
    if usage is not None and (not isinstance(usage, dict) or not set(usage) <= _USAGE_KEYS):
        raise ResultError("usage fora do contrato.")
    return raw


def job_accepted(*, job_id: str | None, trace_id: str | None, status: str,
                 queue_position: int | None = None, error: dict | None = None) -> dict:
    # job_id/trace_id ficam None so quando um envelope rejeitado nem os trazia validos.
    accepted: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "job_id": job_id,
        "trace_id": trace_id,
        "status": status,
    }
    if queue_position is not None:
        accepted["queue_position"] = queue_position
    if error is not None:
        accepted["error"] = error
    return accepted
