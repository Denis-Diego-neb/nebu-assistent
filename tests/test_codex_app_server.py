import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from integrations.codex.app_server import CodexAppServerClient


class CodexAppServerClientTests(unittest.TestCase):
    @patch("integrations.codex.app_server.websocket.create_connection")
    def test_supervisor_usa_thread_efemera_read_only(self, connect: Mock) -> None:
        socket = Mock()
        socket.recv.side_effect = [
            json.dumps({"id": 1, "result": {"userAgent": "codex"}}),
            json.dumps({"id": 2, "result": {"thread": {"id": "thread-1"}}}),
            json.dumps({"id": 3, "result": {"turn": {"id": "turn-1"}}}),
            json.dumps({"method": "item/agentMessage/delta", "params": {"delta": "{\"ok\":"}}),
            json.dumps({"method": "item/agentMessage/delta", "params": {"delta": "true}"}}),
            json.dumps({
                "method": "turn/completed",
                "params": {"turn": {"status": "completed"}},
            }),
        ]
        connect.return_value = socket

        with CodexAppServerClient() as client:
            answer = client.supervise(
                "avalie a Qwen", cwd=Path.cwd(), output_schema={"type": "object"}
            )

        self.assertEqual(answer, '{"ok":true}')
        sent = [json.loads(call.args[0]) for call in socket.send.call_args_list]
        thread_start = next(item for item in sent if item.get("method") == "thread/start")
        self.assertEqual(thread_start["params"]["sandbox"], "read-only")
        self.assertEqual(thread_start["params"]["approvalPolicy"], "never")
        self.assertEqual(thread_start["params"]["model"], "gpt-5.6-terra")
        self.assertTrue(thread_start["params"]["ephemeral"])
        turn_start = next(item for item in sent if item.get("method") == "turn/start")
        self.assertEqual(turn_start["params"]["outputSchema"], {"type": "object"})
        self.assertEqual(turn_start["params"]["effort"], "low")
        self.assertEqual(turn_start["params"]["summary"], "concise")

    def test_recusa_app_server_remoto(self) -> None:
        with self.assertRaisesRegex(ValueError, "local"):
            CodexAppServerClient("ws://192.168.15.4:4500")


if __name__ == "__main__":
    unittest.main()
