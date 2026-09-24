"""Registro pequeno de chamadas MCP compartilhado com o Nebula Home Hub."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4


_LOCK = threading.RLock()
_MAX_BYTES = 512_000


def default_audit_path() -> Path:
    configured = os.environ.get("NEBULA_MCP_AUDIT_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    state_root = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(state_root) if state_root else Path.home() / "AppData" / "Local"
    return base / "Nebula" / "logs" / "mcp-events.jsonl"


def _clean_message(value: object) -> str:
    return " ".join(str(value or "").split())[:300]


class MCPAuditLog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_audit_path()

    def record(self, *, tool: str, ok: bool, duration_ms: int, message: str = "") -> dict:
        event = {
            "id": uuid4().hex,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "tool": str(tool)[:128],
            "ok": bool(ok),
            "duration_ms": max(0, int(duration_ms)),
            "message": _clean_message(message),
        }
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > _MAX_BYTES:
                    rotated = self.path.with_suffix(self.path.suffix + ".1")
                    rotated.unlink(missing_ok=True)
                    self.path.replace(rotated)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except OSError:
                # A auditoria nao deve impedir o controle de um dispositivo.
                pass
        return event


def read_recent_audit_events(
    limit: int = 8, path: Path | str | None = None,
) -> list[dict]:
    audit_path = Path(path) if path is not None else default_audit_path()
    limit = max(0, min(int(limit), 20))
    if not limit:
        return []
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict] = []
    for line in lines[-limit:]:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


__all__ = ["MCPAuditLog", "default_audit_path", "read_recent_audit_events"]
