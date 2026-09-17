import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch
import remote_server
from notebook_power_server import power_server


class ToolsApiTests(unittest.TestCase):
    def start(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:" + str(server.server_port)

    def request(self, url, payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token: headers["X-Nebula-Power-Token"] = token
        req = Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        try:
            with urlopen(req, timeout=3) as response: return response.status, json.load(response)
        except HTTPError as error:
            with error: return error.code, json.load(error)

    def test_pc_tools_require_authentication(self):
        base = self.start(remote_server.Handler)
        for path, data in (("/api/wifi-bpm/status", None), ("/api/rocket-overlay/status", None),
                           ("/api/wifi-bpm/ingest", {}), ("/api/wifi-bpm/reset", {}),
                           ("/api/rocket-overlay/action", {"action": "start"})):
            self.assertEqual(self.request(base + path, data)[0], 401)

    def test_missing_sensor_and_invalid_samples(self):
        base = self.start(remote_server.Handler)
        token = remote_server.POWER_TOKEN
        code, result = self.request(base + "/api/wifi-bpm/status", token=token)
        self.assertEqual(code, 200)
        self.assertIsNone(result["bpm"])
        self.assertEqual(self.request(base + "/api/wifi-bpm/ingest", {"rssi": -40}, token)[0], 400)
        self.assertEqual(self.request(base + "/api/rocket-overlay/action", {"action": []}, token)[0], 400)

    def test_overlay_request_reaches_bridge(self):
        base = self.start(remote_server.Handler)
        with patch.object(remote_server.OVERLAY_BRIDGE, "request", return_value={"ok": True}) as action:
            self.assertEqual(self.request(base + "/api/rocket-overlay/action", {"action": "start"}, remote_server.POWER_TOKEN)[0], 200)
            action.assert_called_once_with("start", None)

    def test_hub_auth_and_universal_dispatch(self):
        base = self.start(power_server.Handler)
        with patch.object(power_server, "UNIVERSAL") as controller, patch.object(power_server, "MONITOR"):
            controller.devices.return_value = {"devices": [], "count": 0}
            controller.action.return_value = {"ok": True}
            self.assertEqual(self.request(base + "/universal/devices")[0], 401)
            controller.devices.assert_not_called()
            self.assertEqual(self.request(base + "/universal/devices", token=power_server.POWER_TOKEN)[0], 200)
            self.assertEqual(self.request(base + "/universal/action", {"device_id": "local:lamp", "action": "turn_on"}, power_server.POWER_TOKEN)[0], 200)
            controller.action.assert_called_once_with("local:lamp", "turn_on")


if __name__ == "__main__": unittest.main()
