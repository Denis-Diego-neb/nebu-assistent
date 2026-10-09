"""Contrato compartilhado entre o PC principal e o worker do notebook.

Os dois lados importam daqui; nenhum mantem uma copia propria do formato.
"""

from nebula_worker.protocol.envelope import (
    JobEnvelope,
    build_generate_envelope,
    envelope_digest,
    parse_envelope,
    required_scope,
)
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ids import is_ulid, new_ulid
from nebula_worker.protocol.result import (
    TERMINAL_STATES,
    ResultError,
    job_accepted,
    job_result,
    parse_job_result,
)
from nebula_worker.protocol.version import PROTOCOL_VERSION, SUPPORTED_VERSIONS

__all__ = [
    "ErrorCode", "JobEnvelope", "PROTOCOL_VERSION", "ResultError", "SUPPORTED_VERSIONS",
    "TERMINAL_STATES", "WorkerError", "build_generate_envelope", "envelope_digest",
    "is_ulid", "job_accepted", "job_result", "new_ulid", "parse_envelope",
    "parse_job_result", "required_scope",
]
