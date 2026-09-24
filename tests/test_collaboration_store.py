from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from services.collaboration.api import CollaborationAPI
from services.collaboration.store import CollaborationStore, Conflict, path_key, priority


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CollaborationStore(self.temp.name)
        self.idea = self.store.create_idea("Corrigir a iluminação e o painel.")["id"]

    def task(self, owner="codex", paths=None, **kwargs):
        return self.store.add_task(self.idea, "codex", title="Seção", owner=owner,
                                   paths=paths or ["main.py"], reason="Corrige a causa", **kwargs)

    def test_two_process_connections_cannot_claim_overlapping_paths(self):
        tasks = [self.task(paths=["Modules/IoT"]), self.task("opus", ["modules/iot/lights.py"])]
        other = CollaborationStore(self.temp.name)

        def claim(pair):
            store, task = pair
            try:
                store.claim(task["id"], task["owner"])
                return True
            except Conflict:
                return False

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(claim, [(self.store, tasks[0]), (other, tasks[1])]))
        self.assertEqual(sum(results), 1)

    def test_dependency_owner_and_pause_are_enforced(self):
        first = self.task()
        second = self.task("opus", ["ui.js"], dependencies=[first["id"]])
        with self.assertRaises(Conflict):
            self.store.claim(second["id"], "opus")
        with self.assertRaises(Conflict):
            self.store.claim(first["id"], "opus")
        self.store.claim(first["id"], "codex")
        self.store.finish(first["id"], "codex", summary="Feito", evidence="Teste passou")
        self.store.pause(True)
        with self.assertRaises(Conflict):
            self.store.claim(second["id"], "opus")
        self.store.pause(False)
        self.assertEqual(self.store.claim(second["id"], "opus")["status"], "running")

    def test_unknown_usage_is_estimated_and_never_zero(self):
        ticket = self.store.reserve_tokens(self.idea, "opus", 5000)
        self.store.settle_tokens(ticket)
        budget = self.store.snapshot()["budgets"][self.idea]["opus"]
        self.assertEqual(budget["estimated"], 5000)
        self.assertEqual(budget["unknown_calls"], 1)
        self.assertEqual(budget["reserved"], 0)
        with self.assertRaises(Conflict):
            self.store.settle_tokens(ticket)
        with self.assertRaises(Conflict):
            self.store.reserve_tokens(self.idea, "opus", 56000)

    def test_budget_reports_overrun_and_stops_future_rounds(self):
        ticket = self.store.reserve_tokens(self.idea, "codex", 4000)
        self.store.settle_tokens(ticket, 70000)
        self.assertEqual(self.store.snapshot()["budgets"][self.idea]["codex"]["measured"], 70000)
        with self.assertRaises(Conflict):
            self.store.reserve_tokens(self.idea, "codex", 1)

    def test_markdown_preserves_both_concurrent_code_sections(self):
        first, second = self.task(), self.task("opus", ["ui.js"])
        self.store.claim(first["id"], "codex")
        self.store.claim(second["id"], "opus")
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(CollaborationStore(self.temp.name).finish,
                task["id"], task["owner"], summary=task["owner"] + " terminou", evidence="Teste passou")
                for task in (first, second)]
            for future in futures:
                future.result()
        markdown = self.store.log_path.read_text(encoding="utf-8")
        self.assertIn("codex terminou", markdown)
        self.assertIn("opus terminou", markdown)
        self.assertEqual(markdown.count("· code_section"), 2)

    def test_foreground_confirmation_cannot_be_spoofed_by_user_api(self):
        api = CollaborationAPI(self.temp.name)
        code, _ = api.handle("POST", "/api/collaboration/messages", {
            "idea_id": self.idea, "text": "Confirmado", "actor": "opus", "kind": "confirmation"})
        self.assertEqual(code, 201)
        state = api.store.snapshot()
        self.assertEqual(state["confirmations"], [])
        self.assertEqual(state["messages"][-1]["actor"], "user")

    def test_aborted_run_preserves_reservation_until_explicit_resume(self):
        task = self.task()
        run = self.store.start_run(self.idea)
        self.store.claim(task["id"], "codex")
        self.store.end_run(run, "blocked")
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "interrupted")
        other = self.task("opus")
        with self.assertRaises(Conflict):
            self.store.claim(other["id"], "opus")
        self.store.start_run(self.idea)
        self.assertEqual(self.store.snapshot()["tasks"][0]["status"], "queued")

    def test_path_traversal_windows_alias_and_nan_rejected(self):
        for path in ("../file.py", "C:\\file.py", "foo/../file.py", ".git/config", "/a.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                path_key(path)
        self.assertEqual(path_key("Foo\\Bar.py"), "foo/bar.py")
        with self.assertRaises(ValueError):
            priority(1, 1, 1, float("nan"), 2000)


if __name__ == "__main__":
    unittest.main()
