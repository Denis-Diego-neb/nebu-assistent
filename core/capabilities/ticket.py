"""Assinatura dos tickets de capacidade no PC principal.

A chave privada fica so aqui, no perfil do usuario do PC. O notebook recebe a
chave publica e confere; se o notebook for comprometido, ainda assim nao
consegue fabricar tickets (a autoridade continua centralizada, secao 30).
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nebula_worker.protocol.envelope import envelope_digest, parse_envelope, required_scope
from nebula_worker.protocol.ticket import (
    key_id_for,
    private_key_from_pem,
    private_key_to_pem,
    public_key_to_text,
    sign_ticket,
)

DEFAULT_TTL_SECONDS = 300


def default_key_file() -> Path:
    configured = os.environ.get("NEBULA_WORKER_SIGNING_KEY", "").strip()
    if configured:
        return Path(configured)
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return base / "Nebula" / "notebook_worker" / "signing_key.pem"


class TicketSigner:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self.key_id = key_id_for(private_key.public_key())

    @classmethod
    def load(cls, path: Path | None = None) -> "TicketSigner":
        path = path or default_key_file()
        try:
            return cls(private_key_from_pem(path.read_bytes()))
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Chave de assinatura nao encontrada em {path}. "
                "Gere com: python -m scripts.notebook_worker_keys"
            ) from exc

    @classmethod
    def generate(cls, path: Path | None = None, *, overwrite: bool = False) -> "TicketSigner":
        path = path or default_key_file()
        if path.exists() and not overwrite:
            raise FileExistsError(f"Ja existe uma chave em {path}; use a rotacao explicita.")
        signer = cls(Ed25519PrivateKey.generate())
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(private_key_to_pem(signer._private_key))
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        return signer

    @property
    def public_key(self):
        return self._private_key.public_key()

    @property
    def public_key_text(self) -> str:
        return public_key_to_text(self.public_key)

    def issue(self, envelope: dict, *, ttl_seconds: int = DEFAULT_TTL_SECONDS,
              scopes: list[str] | None = None) -> dict:
        """Ticket de menor privilegio: por padrao, so o escopo da propria operacao."""
        unsigned = {key: value for key, value in envelope.items() if key != "capability_ticket"}
        parse_envelope(unsigned, require_ticket=False)
        return sign_ticket(
            self._private_key,
            job_id=unsigned["job_id"],
            scopes=scopes or [required_scope(unsigned["model_alias"], unsigned["operation"])],
            envelope_sha256=envelope_digest(unsigned),
            ttl_seconds=ttl_seconds,
        )

    def attach(self, envelope: dict, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict:
        signed = {key: value for key, value in envelope.items() if key != "capability_ticket"}
        signed["capability_ticket"] = self.issue(signed, ttl_seconds=ttl_seconds)
        return signed
