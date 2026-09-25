"""Tickets de capacidade assinados com Ed25519 pelo PC principal (secao 13 do GOAL).

O notebook guarda somente a chave publica: consegue conferir, nunca emitir.
O ticket vale para um unico job, carrega o hash do envelope (entao o prompt nao
pode ser trocado no caminho) e expira em minutos. O dominio fixo no inicio dos
bytes assinados impede reaproveitar a assinatura em outro protocolo.
"""

from __future__ import annotations

import base64
import re
import time
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ids import TICKET_ID_RE, is_ulid, new_ticket_id
from nebula_worker.protocol.serialization import canonical_json, sha256_hex

SIGNING_DOMAIN = b"nebula-capability-ticket/v1\n"
TICKET_KEYS = frozenset({
    "id", "key_id", "job_id", "scopes", "issued_at", "expires_at", "envelope_sha256", "signature",
})
KEY_ID_RE = re.compile(r"^k_[0-9a-f]{16}$")
SCOPE_RE = re.compile(r"^[a-z][a-z0-9_]*(?::[a-z0-9_]+){1,3}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SCOPES = 8


def format_time(timestamp: float) -> str:
    return datetime.fromtimestamp(int(timestamp), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text: object) -> float:
    if not isinstance(text, str) or _TIME_RE.fullmatch(text) is None:
        raise ValueError("Horario precisa estar em UTC no formato AAAA-MM-DDTHH:MM:SSZ.")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ValueError("Texto base64url invalido.")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_key_to_text(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64encode(raw)


def public_key_from_text(text: str) -> Ed25519PublicKey:
    raw = _b64decode(text)
    if len(raw) != 32:
        raise ValueError("Chave publica Ed25519 deve ter 32 bytes.")
    return Ed25519PublicKey.from_public_bytes(raw)


def key_id_for(public_key: Ed25519PublicKey) -> str:
    """Identificador derivado da propria chave: nao ha arquivo extra para sair de sincronia."""
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "k_" + sha256_hex(raw)[:16]


def private_key_to_pem(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def private_key_from_pem(data: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("A chave de assinatura precisa ser Ed25519.")
    return key


def signing_bytes(ticket: dict) -> bytes:
    unsigned = {key: value for key, value in ticket.items() if key != "signature"}
    return SIGNING_DOMAIN + canonical_json(unsigned)


def sign_ticket(private_key: Ed25519PrivateKey, *, job_id: str, scopes: list[str],
                envelope_sha256: str, ttl_seconds: int, now: float | None = None,
                ticket_id: str | None = None) -> dict:
    issued = time.time() if now is None else now
    ticket = {
        "id": ticket_id or new_ticket_id(),
        "key_id": key_id_for(private_key.public_key()),
        "job_id": job_id,
        "scopes": list(scopes),
        "issued_at": format_time(issued),
        "expires_at": format_time(issued + ttl_seconds),
        "envelope_sha256": envelope_sha256,
    }
    parse_ticket_structure({**ticket, "signature": "A"})
    ticket["signature"] = _b64encode(private_key.sign(signing_bytes(ticket)))
    return ticket


def verify_ticket_signature(public_key: Ed25519PublicKey, ticket: dict) -> bool:
    try:
        public_key.verify(_b64decode(ticket["signature"]), signing_bytes(ticket))
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False
    return True


def _ticket_invalid(message: str) -> WorkerError:
    return WorkerError(ErrorCode.TICKET_INVALID, message)


def parse_ticket_structure(ticket: object) -> dict:
    """Formato e tipos; assinatura, prazo e escopo ficam com o validador."""
    if not isinstance(ticket, dict) or set(ticket) != TICKET_KEYS:
        raise _ticket_invalid("capability_ticket com campos diferentes do contrato.")
    if not isinstance(ticket["id"], str) or TICKET_ID_RE.fullmatch(ticket["id"]) is None:
        raise _ticket_invalid("Identificador de ticket invalido.")
    if not isinstance(ticket["key_id"], str) or KEY_ID_RE.fullmatch(ticket["key_id"]) is None:
        raise _ticket_invalid("key_id invalido.")
    if not is_ulid(ticket["job_id"]):
        raise _ticket_invalid("job_id do ticket invalido.")
    scopes = ticket["scopes"]
    if (not isinstance(scopes, list) or not 1 <= len(scopes) <= MAX_SCOPES
            or len(set(map(str, scopes))) != len(scopes)):
        raise _ticket_invalid("scopes deve ser uma lista curta e sem repeticao.")
    for scope in scopes:
        # Curinga nunca e aceito, nem que a politica local o liste por engano.
        if not isinstance(scope, str) or "*" in scope or SCOPE_RE.fullmatch(scope) is None:
            raise _ticket_invalid("Escopo com formato invalido ou curinga.")
    for field in ("issued_at", "expires_at"):
        try:
            parse_time(ticket[field])
        except ValueError as exc:
            raise _ticket_invalid(f"{field}: {exc}") from exc
    if not isinstance(ticket["envelope_sha256"], str) or _SHA256_RE.fullmatch(ticket["envelope_sha256"]) is None:
        raise _ticket_invalid("envelope_sha256 invalido.")
    if not isinstance(ticket["signature"], str) or not ticket["signature"]:
        raise _ticket_invalid("Assinatura ausente.")
    return ticket
