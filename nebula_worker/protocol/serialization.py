"""JSON canonico: a mesma estrutura produz sempre os mesmos bytes nos dois lados."""

from __future__ import annotations

import hashlib
import json


def canonical_json(value: object) -> bytes:
    # Chaves ordenadas e sem espacos. NaN/Infinity ficam proibidos: nao existem
    # em JSON e fariam o hash depender da implementacao.
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
