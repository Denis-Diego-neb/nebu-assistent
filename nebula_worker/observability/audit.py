"""Auditoria so de metadados (INV-007).

A garantia e estrutural: o registro aceita apenas campos de uma lista fechada
e valores curtos. Nao existe campo onde prompt, resposta ou segredo caibam, entao
nenhum chamador consegue vaza-los por engano.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from nebula_worker.protocol.errors import ALL_CODES

FIELDS = frozenset({
    "job_id", "trace_id", "model_alias", "operation", "ticket_id", "key_id",
    "status", "error_code", "latency_ms", "input_tokens", "output_tokens",
    "result_bytes", "stop_reason", "queue_depth", "client", "reason",
})
EVENTS = frozenset({
    "started", "stopped", "accepted", "rejected", "running", "completed",
    "failed", "cancelled", "expired", "denied",
})
REASONS = frozenset({
    "client_not_allowed", "rate_limited", "bad_token", "missing_token",
})
_MAX_TEXT = 80


class AuditLog:
    def __init__(self, path: Path, max_bytes: int = 5_000_000, backups: int = 3) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.Lock()

    def record(self, event: str, **fields: object) -> None:
        if event not in EVENTS:
            raise ValueError(f"Evento de auditoria desconhecido: {event}")
        entry: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
        }
        for key, value in fields.items():
            if key not in FIELDS:
                raise ValueError(f"Campo de auditoria nao permitido: {key}")
            if value is None:
                continue
            if key == "error_code" and value not in ALL_CODES:
                raise ValueError("error_code precisa ser um codigo do protocolo.")
            if key == "reason" and value not in REASONS:
                raise ValueError("reason precisa ser um motivo conhecido.")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"Valor de auditoria nao permitido em {key}.")
            if isinstance(value, str) and len(value) > _MAX_TEXT:
                raise ValueError(f"Valor longo demais para auditoria em {key}.")
            entry[key] = value
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate()
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(line)
            except OSError:
                # Auditoria indisponivel nao derruba o job; o proximo evento tenta de novo.
                pass

    def _rotate(self) -> None:
        try:
            if self.path.stat().st_size < self.max_bytes:
                return
        except FileNotFoundError:
            return
        for index in range(self.backups, 0, -1):
            source = self.path if index == 1 else self.path.with_name(f"{self.path.name}.{index - 1}")
            target = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                try:
                    os.replace(source, target)
                except PermissionError:
                    time.sleep(0.05)
