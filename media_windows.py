"""Leitura e controle das sessoes globais de midia do Windows 10."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import threading
from collections.abc import Callable
from typing import Any

from PIL import Image


MAX_ARTWORK_BYTES = 350_000
MAX_ARTWORK_EDGE = 640


class MediaControlError(RuntimeError):
    """Falha compreensivel ao acessar a sessao de midia do Windows."""


def _default_manager_factory():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
    )

    return GlobalSystemMediaTransportControlsSessionManager.request_async()


def _status_name(value: object) -> str:
    name = str(getattr(value, "name", "")).casefold()
    if name in {"playing", "paused", "stopped", "closed", "opened", "changing"}:
        return name
    numeric = int(value) if isinstance(value, int) else None
    return {4: "playing", 5: "paused", 3: "stopped"}.get(numeric, "unknown")


def _seconds(value: object) -> float:
    total_seconds = getattr(value, "total_seconds", None)
    if callable(total_seconds):
        return max(0.0, float(total_seconds()))
    return 0.0


async def _read_thumbnail(reference: object | None) -> tuple[bytes | None, str | None]:
    if reference is None:
        return None, None
    try:
        from winrt.windows.storage.streams import Buffer, InputStreamOptions

        stream = await reference.open_read_async()  # type: ignore[attr-defined]
        size = min(int(stream.size), 4_000_000)
        if size <= 0:
            return None, None
        result = await stream.read_async(Buffer(size), size, InputStreamOptions.NONE)
        raw = bytes(memoryview(result))
        content_type = str(getattr(stream, "content_type", "") or "image/jpeg")
        with Image.open(io.BytesIO(raw)) as artwork:
            artwork = artwork.convert("RGB")
            artwork.thumbnail((MAX_ARTWORK_EDGE, MAX_ARTWORK_EDGE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            artwork.save(output, "JPEG", quality=84, optimize=True)
            compact = output.getvalue()
        if len(compact) > MAX_ARTWORK_BYTES:
            return None, None
        return compact, "image/jpeg"
    except (OSError, RuntimeError, ValueError):
        return None, None


class WindowsMediaController:
    def __init__(self, manager_factory: Callable[[], Any] | None = None) -> None:
        self._manager_factory = manager_factory or _default_manager_factory
        self._lock = threading.RLock()
        self._artwork_key: tuple[str, str, str, str] | None = None
        self._artwork: bytes | None = None
        self._artwork_type: str | None = None
        self._artwork_id: str | None = None

    async def _manager(self):
        return await self._manager_factory()

    async def _status_async(self, known_artwork_id: str | None) -> dict[str, object]:
        manager = await self._manager()
        session = manager.get_current_session()
        if session is None:
            return {
                "available": False,
                "message": "Nenhuma musica ativa no Windows.",
            }

        properties = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        timeline = session.get_timeline_properties()
        controls = playback.controls
        source = str(getattr(session, "source_app_user_model_id", "") or "")
        title = str(getattr(properties, "title", "") or "Midia sem titulo")
        artist = str(getattr(properties, "artist", "") or "")
        album = str(getattr(properties, "album_title", "") or "")
        artwork_key = (source, title, artist, album)

        with self._lock:
            cached = artwork_key == self._artwork_key
        if not cached:
            artwork, artwork_type = await _read_thumbnail(
                getattr(properties, "thumbnail", None)
            )
            with self._lock:
                self._artwork_key = artwork_key
                self._artwork = artwork
                self._artwork_type = artwork_type
                self._artwork_id = (
                    hashlib.sha256(artwork).hexdigest()[:20] if artwork else None
                )

        with self._lock:
            artwork = self._artwork
            artwork_type = self._artwork_type
            artwork_id = self._artwork_id

        result: dict[str, object] = {
            "available": True,
            "title": title,
            "artist": artist,
            "album": album,
            "source": source,
            "playback_status": _status_name(playback.playback_status),
            "position_seconds": round(_seconds(timeline.position), 2),
            "duration_seconds": round(_seconds(timeline.end_time), 2),
            "artwork_id": artwork_id,
            "controls": {
                "play": bool(getattr(controls, "is_play_enabled", True)),
                "pause": bool(getattr(controls, "is_pause_enabled", True)),
                "next": bool(getattr(controls, "is_next_enabled", True)),
                "previous": bool(getattr(controls, "is_previous_enabled", True)),
            },
        }
        if artwork and artwork_id != known_artwork_id:
            result["artwork"] = base64.b64encode(artwork).decode("ascii")
            result["artwork_type"] = artwork_type
        return result

    def status(self, known_artwork_id: str | None = None) -> dict[str, object]:
        try:
            return asyncio.run(self._status_async(known_artwork_id))
        except (ImportError, OSError, PermissionError, RuntimeError) as exc:
            raise MediaControlError(
                "Nao consegui acessar a midia do Windows."
            ) from exc

    async def _action_async(self, action: str) -> bool:
        manager = await self._manager()
        session = manager.get_current_session()
        if session is None:
            raise MediaControlError("Nenhuma musica ativa no Windows.")
        methods = {
            "play_pause": "try_toggle_play_pause_async",
            "play": "try_play_async",
            "pause": "try_pause_async",
            "next": "try_skip_next_async",
            "previous": "try_skip_previous_async",
        }
        method_name = methods.get(action)
        if method_name is None:
            raise ValueError("Comando de midia invalido.")
        return bool(await getattr(session, method_name)())

    def action(self, action: str) -> dict[str, object]:
        try:
            accepted = asyncio.run(self._action_async(str(action).strip().casefold()))
        except (ImportError, OSError, PermissionError, RuntimeError) as exc:
            if isinstance(exc, (MediaControlError, ValueError)):
                raise
            raise MediaControlError("O Windows recusou o comando de midia.") from exc
        if not accepted:
            raise MediaControlError("O player nao aceitou esse comando.")
        return {"ok": True, "message": "Comando enviado ao player."}


MEDIA_CONTROLLER = WindowsMediaController()


__all__ = ["MEDIA_CONTROLLER", "MediaControlError", "WindowsMediaController"]
