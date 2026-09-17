from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pc_start_agent


class PcStartAgentTests(unittest.TestCase):
    def test_selects_latest_semantic_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Nebula-1.9.9.exe", "Nebula-1.22.0.exe", "Nebula-1.21.12.exe"):
                (root / name).touch()
            with patch.object(pc_start_agent, "PROJECT_DIR", root):
                self.assertEqual(
                    pc_start_agent.configured_executable(),
                    root / "Nebula-1.22.0.exe",
                )

    def test_launch_restores_current_nebula(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "Nebula-1.22.4.exe"
            current.touch()
            with (
                patch.object(pc_start_agent, "PROJECT_DIR", Path(directory)),
                patch.object(
                    pc_start_agent,
                    "running_nebula_names",
                    return_value={"nebula-1.22.4.exe"},
                ),
                patch.object(pc_start_agent, "show_nebula", return_value=True),
                patch.object(pc_start_agent.subprocess, "Popen") as launch,
            ):
                self.assertEqual(
                    pc_start_agent.launch_nebula(),
                    "Janela da Nebula restaurada.",
                )
            launch.assert_not_called()

    def test_launch_replaces_obsolete_nebula(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "Nebula-1.22.4.exe"
            current.touch()
            with (
                patch.object(pc_start_agent, "PROJECT_DIR", Path(directory)),
                patch.object(
                    pc_start_agent,
                    "running_nebula_names",
                    return_value={"nebula-1.22.2.exe"},
                ),
                patch.object(pc_start_agent.subprocess, "run") as stop,
                patch.object(pc_start_agent.subprocess, "Popen") as launch,
            ):
                message = pc_start_agent.launch_nebula()
            stop.assert_called_once()
            launch.assert_called_once()
            self.assertIn("1.22.4", message)


if __name__ == "__main__":
    unittest.main()
