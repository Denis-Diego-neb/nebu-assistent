"""JobResult do lado do PC: o que chega do notebook e conferido antes de ser usado."""

from nebula_worker.protocol.result import TERMINAL_STATES, ResultError, parse_job_result

__all__ = ["ResultError", "TERMINAL_STATES", "parse_job_result"]
