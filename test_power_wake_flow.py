from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from notebook_power_server.power_server import (
    HomeBrain,
    ServerMonitor,
    launch_notebook_assistant,
)


class PowerWakeFlowTests(unittest.TestCase):
    def test_server_monitor_counts_connections_and_writes_log(self) -> None:
        with TemporaryDirectory() as directory:
            log_file = Path(directory) / "server.log"
            monitor = ServerMonitor(log_file)
            monitor.record_event("Servidor iniciado.")
            monitor.record_request("GET", "/health", 200, "192.168.15.40")
            monitor.record_request("POST", "/wake", 401, "192.168.15.41")
            snapshot = monitor.snapshot()

            self.assertEqual(snapshot["total"], 2)
            self.assertEqual(snapshot["successful"], 1)
            self.assertEqual(snapshot["denied"], 1)
            self.assertEqual(snapshot["active_clients"], 2)
            self.assertEqual(snapshot["last_client"], "192.168.15.41")
            log_text = log_file.read_text(encoding="utf-8")
            self.assertIn("Servidor iniciado.", log_text)
            self.assertIn("GET", log_text)
            self.assertIn("/wake", log_text)

    def test_existing_notebook_assistant_is_restored(self) -> None:
        with (
            patch(
                "notebook_power_server.power_server.notebook_assistant_running",
                return_value=True,
            ),
            patch(
                "notebook_power_server.power_server.show_notebook_assistant",
                return_value=True,
            ) as show,
            patch("notebook_power_server.power_server.subprocess.Popen") as launch,
        ):
            launch_notebook_assistant()
        show.assert_called_once_with()
        launch.assert_not_called()

    def test_new_notebook_assistant_waits_for_show_endpoint(self) -> None:
        with (
            patch(
                "notebook_power_server.power_server.notebook_assistant_running",
                side_effect=[False, False],
            ),
            patch(
                "notebook_power_server.power_server.show_notebook_assistant",
                side_effect=[False, True],
            ),
            patch(
                "notebook_power_server.power_server.NOTEBOOK_ASSISTANT",
                Path(__file__),
            ),
            patch("notebook_power_server.power_server.subprocess.Popen") as launch,
            patch("notebook_power_server.power_server.time.sleep"),
        ):
            message = launch_notebook_assistant()
        launch.assert_called_once()
        self.assertIn("aberta", message)

    def test_each_wake_command_has_a_new_id(self) -> None:
        brain = HomeBrain()
        first = brain.queue_pc_launch()
        second = brain.queue_pc_launch()
        self.assertEqual(first["action"], "launch_nebula")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(brain.current_pc_command(), second)

    def test_unsigned_wake_has_no_unlock_grant(self) -> None:
        command = HomeBrain().queue_pc_launch()
        self.assertIsNone(command["unlock_proof"])
        self.assertNotIn("unlock_authorized", command)

    def test_hub_relays_phone_signature_without_granting_login(self) -> None:
        proof = {"payload": "signed-content", "signature": "phone-signature"}
        command = HomeBrain().queue_pc_launch(proof)
        self.assertEqual(command["unlock_proof"], proof)
        self.assertNotIn("unlock_authorized", command)

    def test_fallback_opens_notebook_when_pc_does_not_answer(self) -> None:
        brain = HomeBrain()
        command = brain.queue_pc_launch()
        with (
            patch("notebook_power_server.power_server.time.sleep"),
            patch.object(brain, "_pc", side_effect=RuntimeError("offline")),
            patch(
                "notebook_power_server.power_server.launch_notebook_assistant",
                return_value="aberta no notebook",
            ) as launch,
        ):
            brain._notebook_fallback_worker(str(command["id"]))
        launch.assert_called_once_with()
        self.assertEqual(brain.state["fallback"], "notebook")

    def test_fallback_stays_closed_when_pc_answers(self) -> None:
        brain = HomeBrain()
        command = brain.queue_pc_launch()
        with (
            patch("notebook_power_server.power_server.time.sleep"),
            patch.object(brain, "_pc", return_value={"state": {}}),
            patch(
                "notebook_power_server.power_server.launch_notebook_assistant"
            ) as launch,
        ):
            brain._notebook_fallback_worker(str(command["id"]))
        launch.assert_not_called()
        self.assertTrue(brain.state["pc_online"])


if __name__ == "__main__":
    unittest.main()
