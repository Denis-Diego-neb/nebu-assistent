"""JobEnvelope do lado do PC: montagem e validacao pelo mesmo parser do notebook."""

from nebula_worker.protocol.envelope import (
    JobEnvelope,
    build_generate_envelope,
    envelope_digest,
    parse_envelope,
    required_scope,
)

__all__ = [
    "JobEnvelope", "build_generate_envelope", "envelope_digest", "parse_envelope", "required_scope",
]
