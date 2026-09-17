import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import transfer_chat


class TransferStoreTests(unittest.TestCase):
    def test_text_file_and_duplicate_are_persisted_safely(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.multiple(
                transfer_chat,
                ROOT=root,
                FILES=root / "files",
                HISTORY=root / "messages.json",
            ):
                store = transfer_chat.TransferStore()
                payload = {
                    "id": "a" * 32,
                    "sender": "Notebook",
                    "text": "https://exemplo.local",
                    "filename": "imagem.png",
                    "created_at": 10,
                }
                first = store.add(payload, b"PNG")
                second = store.add(payload, b"OUTRO")
                self.assertEqual(first, second)
                self.assertEqual(len(store.messages()), 1)
                metadata, path = store.file("a" * 32)
                self.assertEqual(metadata["filename"], "imagem.png")
                self.assertEqual(path.read_bytes(), b"PNG")

    def test_rejects_large_file_and_invalid_identifier(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.multiple(
                transfer_chat,
                ROOT=root,
                FILES=root / "files",
                HISTORY=root / "messages.json",
                MAX_FILE_BYTES=2,
            ):
                store = transfer_chat.TransferStore()
                with self.assertRaises(ValueError):
                    store.add({"id": "inválido", "text": "oi"})
                with self.assertRaises(ValueError):
                    store.add({"id": "b" * 32, "filename": "x.bin"}, b"123")


if __name__ == "__main__":
    unittest.main()
