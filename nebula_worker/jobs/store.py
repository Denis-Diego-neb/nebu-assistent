"""Registro em memoria dos jobs; o prompt vive so ate o fim da execucao.

Nada daqui vai para disco. Reiniciar o worker descarta jobs e resultados: o PC
recebe JOB_NOT_FOUND e reenvia com outro job_id, em vez de o notebook guardar
conteudo privado para sobreviver a reinicios (INV-007).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from nebula_worker.jobs.state import FINISHED, check_transition
from nebula_worker.protocol.envelope import JobEnvelope


@dataclass
class JobRecord:
    job_id: str
    trace_id: str
    model_alias: str
    operation: str
    digest: str
    ticket_id: str
    accepted_at: float
    deadline: float
    envelope: JobEnvelope | None
    state: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    output: dict | None = None
    usage: dict | None = None
    error: dict | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


class JobStore:
    def __init__(self, max_records: int = 256) -> None:
        self.max_records = max_records
        self._records: dict[str, JobRecord] = {}

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._records

    def get(self, job_id: str) -> JobRecord | None:
        return self._records.get(job_id)

    def add(self, record: JobRecord) -> None:
        if record.job_id in self._records:
            raise ValueError("Job ja registrado.")
        self._records[record.job_id] = record
        self._trim()

    def transition(self, record: JobRecord, target: str, now: float) -> None:
        check_transition(record.state, target)
        record.state = target
        if target == "running":
            record.started_at = now
        elif target in FINISHED:
            record.finished_at = now
            # O prompt deixa de existir aqui, com sucesso, falha ou cancelamento.
            record.envelope = None
        elif target == "expired":
            record.output = None
            record.usage = None

    def queued(self) -> list[JobRecord]:
        waiting = [record for record in self._records.values() if record.state == "queued"]
        return sorted(waiting, key=lambda record: record.accepted_at)

    def count(self, *states: str) -> int:
        return sum(1 for record in self._records.values() if record.state in states)

    def expire(self, now: float, result_ttl: float, forget_after: float) -> list[JobRecord]:
        """Resultados antigos viram expired; registros expirados ha muito somem."""
        expired = []
        for job_id, record in list(self._records.items()):
            if record.state in FINISHED and record.finished_at is not None \
                    and now - record.finished_at >= result_ttl:
                self.transition(record, "expired", now)
                expired.append(record)
            elif record.state == "expired" and record.finished_at is not None \
                    and now - record.finished_at >= result_ttl + forget_after:
                del self._records[job_id]
        return expired

    def _trim(self) -> None:
        # Limite duro de memoria: descarta primeiro o que ja expirou, depois os
        # terminados mais antigos. Jobs vivos nunca sao descartados aqui.
        if len(self._records) <= self.max_records:
            return
        for wanted in ("expired", "finished"):
            candidates = [
                record for record in self._records.values()
                if (record.state == "expired" if wanted == "expired" else record.state in FINISHED)
            ]
            candidates.sort(key=lambda record: record.finished_at or record.accepted_at)
            for record in candidates:
                if len(self._records) <= self.max_records:
                    return
                del self._records[record.job_id]
