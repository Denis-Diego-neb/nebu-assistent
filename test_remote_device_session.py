from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import remote_server


class RemoteDeviceSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.created_tokens: list[str] = []

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        for token in self.created_tokens:
            remote_server.STATE.sessions.discard(token)

    def test_device_session_requires_power_token(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/device-session",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 401)

    def test_device_session_cookie_opens_panel(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/device-session",
            data=b"{}",
            method="POST",
            headers={
                "X-Nebula-Power-Token": remote_server.POWER_TOKEN,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            cookie = response.headers.get("Set-Cookie", "")
        token = payload["token"]
        self.created_tokens.append(token)
        self.assertTrue(payload["ok"])
        self.assertNotEqual(token, remote_server.STATE.device_token)
        self.assertIn(f"nebula_session={token}", cookie)

        session = urllib.request.Request(
            self.base + "/api/session",
            headers={"Cookie": f"nebula_session={token}"},
        )
        with urllib.request.urlopen(session, timeout=5) as response:
            self.assertTrue(json.loads(response.read().decode("utf-8"))["ok"])

    def test_media_status_is_available_to_authenticated_phone(self) -> None:
        with patch.object(
            remote_server.MEDIA_CONTROLLER,
            "status",
            return_value={"available": True, "title": "SAD!"},
        ) as status:
            request = urllib.request.Request(
                self.base + "/api/media?artwork_id=known",
                headers={"X-Nebula-Power-Token": remote_server.POWER_TOKEN},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["title"], "SAD!")
        status.assert_called_once_with("known")

    def test_media_action_targets_pc_player(self) -> None:
        with patch.object(
            remote_server.MEDIA_CONTROLLER,
            "action",
            return_value={"ok": True, "message": "feito"},
        ) as action:
            request = urllib.request.Request(
                self.base + "/api/media/action",
                data=json.dumps({"action": "next"}).encode("utf-8"),
                method="POST",
                headers={
                    "X-Nebula-Power-Token": remote_server.POWER_TOKEN,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        action.assert_called_once_with("next")


if __name__ == "__main__":
    unittest.main()
