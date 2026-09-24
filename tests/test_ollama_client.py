import unittest
from unittest.mock import Mock, patch

from core.agents.ollama_client import OllamaClient


class OllamaClientTests(unittest.TestCase):
    @patch("core.agents.ollama_client.requests.post")
    def test_envia_schema_seed_e_thinking(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {"message": {"content": '{"ok":true}'}}
        post.return_value = response
        schema = {"type": "object"}

        result = OllamaClient("http://ollama", "qwen", think=True).chat(
            "revise", temperature=0.0, format_schema=schema, seed=42, num_gpu=0,
        )

        self.assertEqual(result, '{"ok":true}')
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["format"], schema)
        self.assertEqual(payload["options"]["seed"], 42)
        self.assertEqual(payload["options"]["num_gpu"], 0)
        self.assertTrue(payload["think"])


if __name__ == "__main__":
    unittest.main()
