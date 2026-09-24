import json
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from ai_sprints import autopilot as ap
from ai_sprints.game_pacing import SprintOllamaClient, game_interval, game_threads, beamng_active, GamePacer
from integrations.gemini import GeminiBrowserReviewGate
from ai_sprints.scoreboard import SprintScoreboard


PATCH = """diff --git a/example.py b/example.py
new file mode 100644
--- /dev/null
+++ b/example.py
@@ -0,0 +1 @@
+VALUE = 1
"""
REVIEW = dict(verdict="revise", risk_level="medium", blocking_findings=["Rever contrato."],
              evidence=[dict(path="example.py", line=1, reason="Constante.")],
              required_tests=[], summary="Falta contrato.")


class RecoveryTests(unittest.TestCase):
    def test_beamng_takes_priority_over_light_game(self):
        games = ["childrenofmorta.exe", "beamng.drive.x64.exe"]
        with patch("ai_sprints.game_pacing.psutil.cpu_count", return_value=28):
            self.assertTrue(beamng_active(games))
            self.assertEqual(game_threads(games), 2)
            self.assertEqual(game_threads(["childrenofmorta.exe"]), 8)
            self.assertEqual(game_threads(["rocketleague.exe"]), 4)

    def test_rejects_extra_lines_that_git_could_silently_drop(self):
        with self.assertRaisesRegex(ValueError, "Contagem"):
            ap.validate_patch(PATCH + "+VALUE2 = 2\n", frozenset({"example.py"}))

    def test_saved_rejection_reaches_gemini_with_new_file_and_scores_once(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            worktree = root / "worktree"
            worktree.mkdir()
            def git(*args):
                subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True)
            git("init")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-m", "base")
            runs = root / "ai_sprints" / "autopilot_runs"
            run = runs / "test_job"
            run.mkdir(parents=True)
            (run / "candidate.patch").write_text(PATCH, encoding="utf-8")
            ap._write_json(run / "pre_review.json", REVIEW)
            ap._save_state(run, "requeued", "fingerprint", resume_stage="tests_running")
            job = ap.Job("test_job", root / "candidate.json", frozenset({"example.py"}), (), 30)
            candidate = SimpleNamespace(objective="Crie constante", acceptance=("Valor 1",), evidence=())
            for name, value in [("PROJECT_ROOT", root), ("RUNS_DIR", runs), ("GLOBAL_STATE", root / "global.json")]:
                stack.enter_context(patch.object(ap, name, value))
            for name, value in [("load_job", job), ("load_candidate", candidate),
                                ("build_evidence", "base"), ("_source_fingerprint", "fingerprint"),
                                ("_create_worktree", worktree), ("_assert_sources_clean", None),
                                ("_remove_worktree", None), ("run_tests", "exit=0\nOK"),
                                ("_gemini_required", True)]:
                stack.enter_context(patch.object(ap, name, return_value=value))
            clients = stack.enter_context(patch.object(ap, "SprintOllamaClient"))
            ap.process(root / "job.json")
            clients.return_value.chat.assert_not_called()
            state = ap._read_json(run / "state.json")
            self.assertEqual(state["status"], "waiting_gemini")
            self.assertTrue(state["eligible_for_approval"])
            gate = GeminiBrowserReviewGate(root)
            prompt = ap._read_json(gate.request_path("test_job"))["prompt"]
            self.assertIn("+VALUE = 1", prompt)
            self.assertIn("Falta contrato", prompt)
            review = {**REVIEW, "rewards": {
                "worker_4b": {"delta": 2, "reason": "Credito parcial."},
                "reviewer_9b": {"delta": 3, "reason": "Detectou problema."}}}
            gate.record("test_job", review)
            ap.process(root / "job.json")
            ap.process(root / "job.json")
            state = ap._read_json(run / "state.json")
            self.assertEqual(state["status"], "rejected")
            self.assertEqual(state["summary"], "Falta contrato.")
            board = SprintScoreboard(root)._load()
            self.assertEqual(board["agents"]["worker_4b"]["score"], 2)
            self.assertEqual(board["agents"]["worker_4b"]["reviews"], 1)
            self.assertEqual(next(iter(board["sprints"].values()))["blocking_findings"], ["Rever contrato."])

    def test_game_limits_local_inference_but_not_remote(self):
        with patch("ai_sprints.game_pacing.active_games", return_value=["acs.exe"]), \
             patch("core.agents.ollama_client.requests.post") as post:
            post.return_value.json.return_value = {"message": {"content": "ok"}}
            SprintOllamaClient("http://127.0.0.1:11434", "qwen").chat("test", num_gpu=99)
            options = post.call_args.kwargs["json"]["options"]
            self.assertEqual(options["num_gpu"], 0)
            self.assertEqual(options["num_thread"], 4)
            SprintOllamaClient("http://192.168.15.4:11434", "qwen").chat("test")
            self.assertNotIn("num_gpu", post.call_args.kwargs["json"]["options"])
            self.assertEqual(game_interval(30, ["acs.exe"]), 300)
            self.assertEqual(game_interval(30, []), 30)
            self.assertEqual(game_interval(30, ["childrenofmorta.exe"]), 60)

    def test_game_runner_affinity_is_restored_when_game_closes(self):
        runner = Mock(pid=123, info={"name": "ollama.exe", "cmdline": ["ollama.exe", "runner"]})
        runner.create_time.return_value = 456
        runner.cpu_affinity.return_value = [0, 1, 2, 3]
        runner.nice.return_value = 32
        pacer = GamePacer()
        with patch("ai_sprints.game_pacing.active_games", side_effect=[["acs.exe"], []]), \
             patch("ai_sprints.game_pacing.psutil.process_iter", return_value=[runner]), \
             patch("ai_sprints.game_pacing.psutil.Process", return_value=runner):
            pacer.poll()
            runner.cpu_affinity.assert_called_with([0, 1, 2, 3])
            pacer.poll()
            runner.cpu_affinity.assert_called_with([0, 1, 2, 3])
            runner.nice.assert_called_with(32)
            self.assertFalse(pacer.saved)
