import tempfile
import threading
import unittest
from pathlib import Path

from services.collaboration.api import CollaborationAPI
from services.collaboration.providers import Reply


class ChatProvider:
    def __init__(self, fail=None, gate=None):
        self.calls = []
        self.fail, self.gate = fail, gate

    def complete(self, agent, prompt, schema, cwd):
        self.calls.append((agent, prompt))
        if self.gate:
            self.gate.wait(5)
        if agent == self.fail:
            raise RuntimeError("login indisponível")
        return Reply({"text": "Resposta de " + agent}, "session-" + agent, "model-test", 100)


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def finish(self, api):
        api.coordinator.chat_thread.join(10)
        self.assertFalse(api.coordinator.chat_thread.is_alive())
        state = api.store.snapshot()
        self.assertIsNone(state.get("active_chat"))
        return state

    def test_new_chat_both_reply_followup_has_history_and_no_code_tasks(self):
        provider = ChatProvider()
        api = CollaborationAPI(self.temp.name, provider)
        status, result = api.handle("POST", "/api/collaboration/chat", {"text": "Olá"})
        self.assertEqual(status, 202)
        state = self.finish(api)
        self.assertEqual([m["actor"] for m in state["messages"] if m["kind"] == "chat_reply"], ["codex", "opus"])
        self.assertEqual(state["tasks"], [])
        self.assertEqual(state["confirmations"], [])
        self.assertEqual(state["ideas"][0]["status"], "pending")
        self.assertIsNone(state["active_run"])
        self.assertEqual(state["budgets"][result["idea_id"]]["opus"]["measured"], 100)
        api.handle("POST", "/api/collaboration/chat", {"idea_id": result["idea_id"], "text": "E agora?"})
        self.finish(api)
        self.assertIn("Resposta de opus", provider.calls[2][1])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [Path(self.temp.name) / ".nebula-collaboration"])

    def test_one_failure_still_allows_other_agent_and_reports_error(self):
        api = CollaborationAPI(self.temp.name, ChatProvider(fail="codex"))
        api.handle("POST", "/api/collaboration/chat", {"text": "oi"})
        state = self.finish(api)
        self.assertTrue(any(m["kind"] == "chat_error" for m in state["messages"]))
        self.assertTrue(any(m["kind"] == "chat_reply" and m["actor"] == "opus" for m in state["messages"]))

    def test_overlapping_message_rejected_without_recording_it(self):
        gate = threading.Event()
        api = CollaborationAPI(self.temp.name, ChatProvider(gate=gate))
        _, result = api.handle("POST", "/api/collaboration/chat", {"text": "primeira"})
        try:
            status, _ = api.handle("POST", "/api/collaboration/chat", {"idea_id": result["idea_id"], "text": "duplicada"})
            self.assertEqual(status, 409)
        finally:
            gate.set()
            state = self.finish(api)
        self.assertFalse(any(m["data"].get("text") == "duplicada" for m in state["messages"]))

    def test_invalid_message_creates_nothing(self):
        api = CollaborationAPI(self.temp.name, ChatProvider())
        self.assertEqual(api.handle("POST", "/api/collaboration/chat", {"text": " "})[0], 400)
        self.assertEqual(api.store.snapshot()["ideas"], [])


if __name__ == "__main__":
    unittest.main()
