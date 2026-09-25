"""Codigos de erro estaveis do protocolo; o texto e para pessoas, o codigo para codigo."""

from __future__ import annotations


class ErrorCode:
    INVALID_ENVELOPE = "INVALID_ENVELOPE"
    UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"
    UNKNOWN_MODEL = "UNKNOWN_MODEL"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TICKET_INVALID = "TICKET_INVALID"
    TICKET_EXPIRED = "TICKET_EXPIRED"
    TICKET_REPLAYED = "TICKET_REPLAYED"
    SCOPE_DENIED = "SCOPE_DENIED"
    DUPLICATE_JOB = "DUPLICATE_JOB"
    QUEUE_FULL = "QUEUE_FULL"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    NOT_READY = "NOT_READY"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_ERROR = "MODEL_ERROR"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ALL_CODES = frozenset(
    value for name, value in vars(ErrorCode).items() if not name.startswith("_")
)


class WorkerError(Exception):
    """Falha de dominio que vira ``error`` estruturado, nunca traceback."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"Codigo de erro desconhecido: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, object]:
        error: dict[str, object] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = dict(self.details)
        return error
