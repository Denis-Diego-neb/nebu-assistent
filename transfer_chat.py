"""Histórico privado para troca direta de textos e arquivos entre as Nebulas."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import uuid
from pathlib import Path


MAX_FILE_BYTES = 25 * 1024 * 1024
ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula" / "transfer-chat"
FILES = ROOT / "files"
HISTORY = ROOT / "messages.json"


class TransferStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        FILES.mkdir(parents=True, exist_ok=True)

    def _read(self) -> list[dict[str, object]]:
        try:
            data = json.loads(HISTORY.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _write(self, messages: list[dict[str, object]]) -> None:
        ROOT.mkdir(parents=True, exist_ok=True)
        temporary = HISTORY.with_suffix(".tmp")
        temporary.write_text(json.dumps(messages[-300:], ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(HISTORY)

    @staticmethod
    def _name(value: object) -> str:
        name = Path(str(value or "arquivo")).name.strip()[:180] or "arquivo"
        return re.sub(r"[\x00-\x1f]", "", name)

    def add(self, payload: dict[str, object], data: bytes | None = None) -> dict[str, object]:
        message_id = str(payload.get("id") or uuid.uuid4().hex)
        if not re.fullmatch(r"[0-9a-f]{32}", message_id):
            raise ValueError("Identificador de mensagem inválido.")
        text = str(payload.get("text") or "").strip()[:8_000]
        filename = self._name(payload.get("filename")) if payload.get("filename") else ""
        if not text and not filename:
            raise ValueError("Escreva uma mensagem ou escolha um arquivo.")
        if data is not None and len(data) > MAX_FILE_BYTES:
            raise ValueError("O arquivo ultrapassa 25 MB.")
        with self.lock:
            messages = self._read()
            existing = next((item for item in messages if item.get("id") == message_id), None)
            if existing:
                return dict(existing)
            stored = ""
            if filename and data is not None:
                stored = message_id + Path(filename).suffix[:16]
                (FILES / stored).write_bytes(data)
            message = {
                "id": message_id,
                "sender": str(payload.get("sender") or "Computador")[:80],
                "text": text,
                "filename": filename,
                "stored": stored,
                "size": len(data) if data is not None else int(payload.get("size") or 0),
                "mime": str(payload.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream"),
                "created_at": float(payload.get("created_at") or time.time()),
            }
            messages.append(message)
            messages.sort(key=lambda item: float(item.get("created_at") or 0))
            self._write(messages)
            return dict(message)

    def messages(self) -> list[dict[str, object]]:
        with self.lock:
            return [dict(item) for item in self._read()]

    def file(self, message_id: str) -> tuple[dict[str, object], Path]:
        with self.lock:
            item = next((m for m in self._read() if m.get("id") == message_id), None)
            if not item or not item.get("stored"):
                raise FileNotFoundError(message_id)
            path = FILES / str(item["stored"])
            if not path.is_file():
                raise FileNotFoundError(message_id)
            return dict(item), path


CHAT_STORE = TransferStore()
