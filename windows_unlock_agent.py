"""Agente de pré-login que transforma uma autorização do hub em uso único."""

from __future__ import annotations

import json
import base64
import hashlib
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


POWER_TOKEN = os.environ.get("NEBULA_POWER_TOKEN", "").strip()
NOTEBOOK_ENDPOINTS = (
    "http://100.78.67.81:8766",
    "http://192.168.15.4:8766",
    "http://192.168.15.86:8766",
)
PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Nebula"
STATE_FILE = PROGRAM_DATA / "unlock_agent.json"
AUTHORIZATION_FILE = PROGRAM_DATA / "unlock.authorized"
LOG_FILE = PROGRAM_DATA / "unlock_agent.log"
POLL_SECONDS = 2
MAX_COMMAND_AGE_SECONDS = 180
AUTHORIZATION_SECONDS = 120


def log(message: str) -> None:
    PROGRAM_DATA.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as stream:
        stream.write(f"{stamp} {message}\n")


def load_last_command() -> str:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("last_command", "")) if isinstance(data, dict) else ""


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as stream:
            stream.write(text)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_command() -> dict[str, object] | None:
    last_error: Exception | None = None
    for endpoint in NOTEBOOK_ENDPOINTS:
        request = Request(
            endpoint + "/pc/command",
            headers={
                "X-Nebula-Power-Token": POWER_TOKEN,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            command = payload.get("command") if isinstance(payload, dict) else None
            return command if isinstance(command, dict) else None
        except (HTTPError, URLError, OSError, ValueError) as exc:
            last_error = exc
    if last_error is not None:
        raise RuntimeError(str(last_error)) from last_error
    return None


def accept_command(command: dict[str, object], last_command: str, now: float) -> str:
    command_id = str(command.get("id", ""))
    if not command_id or command_id == last_command:
        return last_command
    proof = command.get("unlock_proof")
    if not isinstance(proof, dict):
        return last_command
    try:
        if len(str(proof.get("payload", ""))) > 1024 or len(str(proof.get("signature", ""))) > 512:
            return last_command
        payload = base64.b64decode(proof["payload"], validate=True)
        signature = base64.b64decode(proof["signature"], validate=True)
        version, target, issued, nonce = payload.decode("ascii").split("\n")
        created_at = int(issued)
        if (version != "nebula-unlock-v1" or len(nonce) != 36 or
                target != (PROGRAM_DATA / "unlock_target.txt").read_text(encoding="ascii").strip() or
                not -15 <= now - created_at <= MAX_COMMAND_AGE_SECONDS):
            return last_command
        key = serialization.load_der_public_key((PROGRAM_DATA / "phone_public.der").read_bytes())
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            return last_command
        key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        # Persist replay protection before granting login. A changed hub command
        # ID or an agent restart must not make the same signature usable again.
        state = json.loads(STATE_FILE.read_text(encoding="ascii")) if STATE_FILE.exists() else {}
        used = state.get("used", {})
        if not isinstance(used, dict):
            return last_command
        digest = hashlib.sha256(payload).hexdigest()
        if digest in used:
            return last_command
        used = {k: v for k, v in used.items() if float(v) >= now - MAX_COMMAND_AGE_SECONDS - 15}
        used[digest] = created_at
        atomic_text(STATE_FILE, json.dumps({"last_command": command_id, "used": used}))
    except (InvalidSignature, OSError, ValueError, TypeError, KeyError, AttributeError):
        return last_command
    atomic_text(AUTHORIZATION_FILE, str(int(min(now + AUTHORIZATION_SECONDS, created_at + MAX_COMMAND_AGE_SECONDS))))
    log(f"Autorização de uso único recebida: {command_id}.")
    return command_id


def run() -> None:
    if len(POWER_TOKEN) < 24:
        log("Agente desativado: configure NEBULA_POWER_TOKEN com pelo menos 24 caracteres.")
        return
    last_command = load_last_command()
    log("Agente de desbloqueio iniciado.")
    offline_logged = False
    while True:
        try:
            command = fetch_command()
            offline_logged = False
            if command is not None:
                last_command = accept_command(command, last_command, time.time())
        except (OSError, RuntimeError, ValueError) as exc:
            if not offline_logged:
                log(f"Hub indisponível: {exc}")
                offline_logged = True
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
