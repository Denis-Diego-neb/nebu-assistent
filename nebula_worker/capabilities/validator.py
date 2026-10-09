"""Confere o ticket de capacidade antes de o job existir (secoes 13 e 22 do GOAL).

O notebook nao confia na operacao so porque ela chegou pela rede: o token HTTP
diz *quem* chamou; o ticket diz *o que* aquele job especifico pode fazer, por
quanto tempo, e so pode ser usado uma vez.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from nebula_worker.protocol.envelope import JobEnvelope
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ticket import parse_ticket_structure, parse_time, verify_ticket_signature


@dataclass(frozen=True)
class ValidatedTicket:
    ticket_id: str
    key_id: str
    scopes: tuple[str, ...]
    expires_at: float


class TicketValidator:
    def __init__(self, trusted_keys: dict[str, Ed25519PublicKey], allowed_scopes: frozenset[str], *,
                 max_ttl_seconds: int, clock_skew_seconds: int, replay_file: Path | None = None,
                 clock=time.time) -> None:
        if not trusted_keys:
            raise ValueError("Configure ao menos uma chave publica confiavel.")
        if any("*" in scope for scope in allowed_scopes):
            raise ValueError("A politica local nao aceita escopos com curinga.")
        self.trusted_keys = dict(trusted_keys)
        self.allowed_scopes = frozenset(allowed_scopes)
        self.max_ttl_seconds = max_ttl_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self.replay_file = replay_file
        self.clock = clock
        self._lock = threading.Lock()
        self._used: dict[str, float] = self._load_used()

    def validate(self, envelope: JobEnvelope) -> ValidatedTicket:
        ticket = parse_ticket_structure(envelope.capability_ticket)
        public_key = self.trusted_keys.get(ticket["key_id"])
        # Mesma mensagem para chave desconhecida e assinatura ruim: quem sonda
        # nao descobre quais chaves o notebook aceita.
        if public_key is None or not verify_ticket_signature(public_key, ticket):
            raise WorkerError(ErrorCode.TICKET_INVALID, "Assinatura do ticket invalida.")
        if ticket["job_id"] != envelope.job_id:
            raise WorkerError(ErrorCode.TICKET_INVALID, "Ticket emitido para outro job.")
        if ticket["envelope_sha256"] != envelope.digest:
            raise WorkerError(ErrorCode.TICKET_INVALID, "Envelope alterado depois da assinatura.")
        now = self.clock()
        issued_at = parse_time(ticket["issued_at"])
        expires_at = parse_time(ticket["expires_at"])
        if issued_at > now + self.clock_skew_seconds:
            raise WorkerError(ErrorCode.TICKET_INVALID, "Ticket emitido no futuro; confira os relogios.")
        if expires_at <= issued_at or expires_at - issued_at > self.max_ttl_seconds:
            raise WorkerError(ErrorCode.TICKET_INVALID, "Validade do ticket fora do limite local.")
        if expires_at <= now - self.clock_skew_seconds:
            raise WorkerError(ErrorCode.TICKET_EXPIRED, "Ticket expirado.")
        scopes = tuple(ticket["scopes"])
        if envelope.required_scope not in scopes:
            raise WorkerError(ErrorCode.SCOPE_DENIED, "O ticket nao autoriza esta operacao.")
        if not set(scopes) <= self.allowed_scopes:
            # Nao revela quais escopos existem; so que o pedido excede a politica.
            raise WorkerError(ErrorCode.SCOPE_DENIED, "O ticket pede escopos fora da politica local.")
        with self._lock:
            self._prune(now)
            if ticket["id"] in self._used:
                raise WorkerError(ErrorCode.TICKET_REPLAYED, "Ticket ja utilizado.")
        return ValidatedTicket(ticket["id"], ticket["key_id"], scopes, expires_at)

    def consume(self, ticket: ValidatedTicket) -> None:
        """Marca como usado so quando o job foi aceito; persiste antes de seguir."""
        with self._lock:
            if ticket.ticket_id in self._used:
                raise WorkerError(ErrorCode.TICKET_REPLAYED, "Ticket ja utilizado.")
            self._used[ticket.ticket_id] = ticket.expires_at + self.clock_skew_seconds
            self._save_used()

    def _prune(self, now: float) -> None:
        expired = [ticket_id for ticket_id, until in self._used.items() if until < now]
        for ticket_id in expired:
            del self._used[ticket_id]

    def _load_used(self) -> dict[str, float]:
        if self.replay_file is None:
            return {}
        try:
            data = json.loads(self.replay_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): float(value) for key, value in data.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)}

    def _save_used(self) -> None:
        # So identificadores e prazos, nunca conteudo. Sem isto, reiniciar o
        # worker reabriria a janela de reenvio de todo ticket ainda valido.
        if self.replay_file is None:
            return
        self.replay_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.replay_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._used, sort_keys=True), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, self.replay_file)
                return
            except PermissionError:
                # Antivirus ou indexador segurando o arquivo por instantes no Windows.
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
