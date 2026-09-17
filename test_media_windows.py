from __future__ import annotations

import base64
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from media_windows import WindowsMediaController


class FakeSession:
    source_app_user_model_id = "brave.exe"

    def __init__(self) -> None:
        self.actions: list[str] = []
        self.properties = SimpleNamespace(
            title="SAD!",
            artist="XXXTENTACION",
            album_title="?",
            thumbnail=object(),
        )

    async def try_get_media_properties_async(self):
        return self.properties

    def get_playback_info(self):
        return SimpleNamespace(
            playback_status=SimpleNamespace(name="PLAYING"),
            controls=SimpleNamespace(
                is_play_enabled=True,
                is_pause_enabled=True,
                is_next_enabled=True,
                is_previous_enabled=True,
            ),
        )

    def get_timeline_properties(self):
        return SimpleNamespace(
            position=timedelta(seconds=42),
            end_time=timedelta(seconds=180),
        )

    async def _accept(self, action: str):
        self.actions.append(action)
        return True

    async def try_toggle_play_pause_async(self): return await self._accept("play_pause")
    async def try_play_async(self): return await self._accept("play")
    async def try_pause_async(self): return await self._accept("pause")
    async def try_skip_next_async(self): return await self._accept("next")
    async def try_skip_previous_async(self): return await self._accept("previous")


class FakeManager:
    def __init__(self, session) -> None:
        self.session = session

    def get_current_session(self):
        return self.session


class WindowsMediaControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = FakeSession()

        async def manager_factory():
            return FakeManager(self.session)

        self.controller = WindowsMediaController(manager_factory)

    def test_status_exposes_browser_track_timeline_and_artwork_once(self) -> None:
        artwork = b"compact-artwork"
        with patch("media_windows._read_thumbnail", AsyncMock(return_value=(artwork, "image/jpeg"))):
            first = self.controller.status()
            second = self.controller.status(str(first["artwork_id"]))

        self.assertEqual(first["title"], "SAD!")
        self.assertEqual(first["artist"], "XXXTENTACION")
        self.assertEqual(first["source"], "brave.exe")
        self.assertEqual(first["playback_status"], "playing")
        self.assertEqual(first["position_seconds"], 42.0)
        self.assertEqual(first["duration_seconds"], 180.0)
        self.assertEqual(base64.b64decode(str(first["artwork"])), artwork)
        self.assertNotIn("artwork", second)

    def test_actions_target_current_windows_media_session(self) -> None:
        for action in ("previous", "play_pause", "next"):
            self.assertTrue(self.controller.action(action)["ok"])
        self.assertEqual(self.session.actions, ["previous", "play_pause", "next"])

    def test_status_without_active_media_is_explicit(self) -> None:
        async def empty_manager():
            return FakeManager(None)

        self.assertFalse(WindowsMediaController(empty_manager).status()["available"])


if __name__ == "__main__":
    unittest.main()
