"""Versao do protocolo entre o PC principal e o worker do notebook."""

from __future__ import annotations

from nebula_worker.protocol.errors import ErrorCode, WorkerError

PROTOCOL_VERSION = "1.0"
SUPPORTED_VERSIONS: tuple[str, ...] = (PROTOCOL_VERSION,)


def negotiate(requested: object) -> str:
    """Aceita somente uma versao suportada; nunca rebaixa em silencio."""
    if not isinstance(requested, str) or requested not in SUPPORTED_VERSIONS:
        raise WorkerError(
            ErrorCode.UNSUPPORTED_PROTOCOL,
            f"Versao de protocolo nao suportada. Suportadas: {', '.join(SUPPORTED_VERSIONS)}.",
        )
    return requested
