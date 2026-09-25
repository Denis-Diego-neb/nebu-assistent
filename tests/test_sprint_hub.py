import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from notebook_power_server import power_server as hub
from ai_sprints.hub_report import snapshot


class SprintHubTests(unittest.TestCase):
    def test_authenticated_summary_and_pause_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temporary:
            monitor = hub.ServerMonitor(Path(temporary) / "log")
            with patch.object(hub, "MONITOR", monitor):
                server = ThreadingHTTPServer(("127.0.0.1", 0), hub.Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    conn = http.client.HTTPConnection(*server.server_address)
                    conn.request("GET", "/sprints")
                    response = conn.getresponse()
                    self.assertEqual(response.status, 401)
                    response.read()
                    headers = {"X-Nebula-Power-Token": hub.POWER_TOKEN, "Content-Type": "application/json"}
                    payload = {"counts": {"waiting_gemini": 2}, "recent": [], "paused": False, "evaluated": 0}
                    monitor.command_sprints("pause")
                    conn.request("POST", "/sprints", json.dumps(payload), headers)
                    self.assertEqual(json.load(conn.getresponse())["command"], "pause")
                    conn.request("POST", "/sprints", json.dumps(payload), headers)
                    self.assertEqual(json.load(conn.getresponse())["command"], "pause")
                    payload["paused"] = True
                    conn.request("POST", "/sprints", json.dumps(payload), headers)
                    self.assertIsNone(json.load(conn.getresponse())["command"])
                    self.assertEqual(monitor.sprint_snapshot()["data"]["counts"]["waiting_gemini"], 2)
                    conn.close()
                finally:
                    server.shutdown()
                    server.server_close()

    def test_pending_scores_are_not_reported_as_zero_quality(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "ai_sprints/autopilot_runs/job/state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"status": "waiting_gemini", "updated_at": "2026-09-21T03:00:00"}))
            with patch("ai_sprints.hub_report.active_games", return_value=[]):
                result = snapshot(root)
            self.assertEqual(result["evaluated"], 0)
            self.assertEqual(result["recent"], [])
            self.assertIn("aguardando Gemini", result["alerts"][0])


class ConfiguracaoDoReporterTests(unittest.TestCase):
    """Watcher reiniciado por um shell antigo parava de reportar ao hub."""

    def test_sem_variavel_no_ambiente_le_do_registro_do_usuario(self):
        import os
        from ai_sprints import hub_report

        if os.name != "nt":
            self.skipTest("registro so existe no Windows")
        with patch.dict(os.environ, {"NEBULA_SPRINT_HUB_URL": ""}), \
                patch("winreg.QueryValueEx", return_value=("http://hub:8766", 1)), \
                patch("winreg.OpenKey") as abrir:
            abrir.return_value.__enter__.return_value = object()
            self.assertEqual(hub_report._config("NEBULA_SPRINT_HUB_URL"), "http://hub:8766")

    def test_ambiente_tem_prioridade(self):
        import os
        from ai_sprints import hub_report

        with patch.dict(os.environ, {"NEBULA_SPRINT_HUB_URL": "http://env:1"}):
            self.assertEqual(hub_report._config("NEBULA_SPRINT_HUB_URL"), "http://env:1")
