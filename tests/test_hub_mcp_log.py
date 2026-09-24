import tempfile
import unittest
from pathlib import Path

from notebook_power_server.power_server import ServerMonitor


def sprint_payload(event):
    return {
        "counts": {},
        "recent": [],
        "evaluated": 0,
        "total": 0,
        "paused": False,
        "mcp_events": [event],
    }


class HomeHubMCPLogTests(unittest.TestCase):
    def test_evento_mcp_aparece_uma_vez_no_log_do_hub(self) -> None:
        event = {
            "id": "abc123",
            "at": "2026-09-23T12:00:00-03:00",
            "tool": "modo_rpm_status",
            "ok": True,
            "duration_ms": 18,
            "message": "Modo RPM ativo.",
        }
        with tempfile.TemporaryDirectory() as temp:
            monitor = ServerMonitor(Path(temp) / "server.log")
            monitor.receive_sprints(sprint_payload(event))
            monitor.receive_sprints(sprint_payload(event))
            lines = [line for line in monitor.recent if "MCP OK" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("modo_rpm_status (18 ms)", lines[0])

    def test_rejeita_evento_sem_contrato(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            monitor = ServerMonitor(Path(temp) / "server.log")
            with self.assertRaisesRegex(ValueError, "MCP"):
                monitor.receive_sprints(sprint_payload({"id": "x"}))


if __name__ == "__main__":
    unittest.main()
