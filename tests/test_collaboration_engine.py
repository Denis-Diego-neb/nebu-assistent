import json
from pathlib import Path
import tempfile
import unittest

from services.collaboration.engine import Coordinator
from services.collaboration.providers import Reply, parse_claude, parse_codex
from services.collaboration.store import CollaborationStore


class FakeProvider:
    def __init__(self, root, reject=False, edit_external=False):
        self.root, self.reject, self.edit_external = root, reject, edit_external
        self.calls = []

    def complete(self, agent, prompt, schema, cwd):
        self.calls.append(agent)
        props = schema["properties"]
        if "tasks" in props:
            data = {"confirmation": "Confirmo minha participação.", "summary": "Uma seção basta.", "tasks": [{
                "title": "Corrigir soma", "owner": "codex", "paths": ["calc.py"], "reason": "Erro reproduzível",
                "impact": 4, "urgency": 3, "risk": 2, "confidence": 0.9, "estimated_tokens": 4000}]}
        elif "files" in props:
            data = {"summary": "Soma corrigida.", "files": [{"path": "calc.py", "content": "def soma(a, b):\n    return a + b\n"}]}
        else:
            data = {"approved": not self.reject, "summary": "Revisão encerrada."}
            if self.edit_external:
                (Path(self.root) / "calc.py").write_text("# trabalho externo\n", encoding="utf-8")
        return Reply(data, "session-" + agent, "modelo-teste", 123)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "calc.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
        self.store = CollaborationStore(self.root)
        self.idea = self.store.create_idea("Corrigir soma")["id"]

    def run_job(self, **kwargs):
        provider = FakeProvider(self.root, **kwargs)
        engine = Coordinator(self.store, provider)
        engine.start(self.idea)
        engine.thread.join(timeout=10)
        self.assertFalse(engine.thread.is_alive())
        return self.store.snapshot(), provider

    def test_end_to_end_two_real_result_confirmations_and_one_edit(self):
        state, provider = self.run_job()
        self.assertEqual(state["ideas"][0]["status"], "completed")
        self.assertEqual({c["agent"] for c in state["confirmations"]}, {"codex", "opus"})
        self.assertEqual(provider.calls, ["codex", "opus", "codex", "opus"])
        self.assertIn("return a + b", (self.root / "calc.py").read_text())
        self.assertIn("code_section", self.store.log_path.read_text(encoding="utf-8"))
        self.assertIsNone(state["active_run"])

    def test_external_edit_is_preserved(self):
        state, _ = self.run_job(edit_external=True)
        self.assertEqual(state["ideas"][0]["status"], "blocked")
        self.assertEqual((self.root / "calc.py").read_text(), "# trabalho externo\n")

    def test_rejected_code_is_not_applied_and_can_retry(self):
        state, _ = self.run_job(reject=True)
        self.assertEqual(state["tasks"][0]["status"], "failed")
        self.assertIn("return a - b", (self.root / "calc.py").read_text())
        state, provider = self.run_job()
        self.assertEqual(provider.calls, ["codex", "opus"])
        self.assertEqual(state["ideas"][0]["status"], "completed")
        self.assertEqual(len(state["confirmations"]), 2)

    def test_measured_tokens_parsed_without_double_counting_cache(self):
        output = "\n".join(json.dumps(x) for x in [
            {"type": "thread.started", "thread_id": "real-thread"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}},
            {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 90, "output_tokens": 10}},
        ])
        self.assertEqual(parse_codex(output, "configured").tokens, 110)
        envelope = {"subtype": "success", "session_id": "real-session", "result": '{"ok":true}',
                    "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 20},
                    "modelUsage": {"real-model": {}}}
        result = parse_claude(json.dumps(envelope), "opus")
        self.assertEqual(result.tokens, 35)
        self.assertEqual(result.model, "real-model")


if __name__ == "__main__":
    unittest.main()
