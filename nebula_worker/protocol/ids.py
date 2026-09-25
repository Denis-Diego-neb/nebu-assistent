"""Identificadores ULID: ordenaveis no tempo e seguros como nome de pasta."""

from __future__ import annotations

import re
import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
TICKET_ID_RE = re.compile(r"^cap_[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def new_ulid(now: float | None = None) -> str:
    """48 bits de milissegundos + 80 bits aleatorios, em base32 de Crockford."""
    milliseconds = int((time.time() if now is None else now) * 1000)
    if not 0 <= milliseconds < 2 ** 48:
        raise ValueError("Horario fora do intervalo de um ULID.")
    value = (milliseconds << 80) | secrets.randbits(80)
    characters = []
    for _ in range(26):
        characters.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(characters))


def new_ticket_id() -> str:
    return "cap_" + new_ulid()


def is_ulid(value: object) -> bool:
    return isinstance(value, str) and ULID_RE.fullmatch(value) is not None
