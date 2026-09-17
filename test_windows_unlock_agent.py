from __future__ import annotations
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import windows_unlock_agent as agent

class WindowsUnlockAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in {"PROGRAM_DATA": self.root, "STATE_FILE": self.root / "state.json",
                            "AUTHORIZATION_FILE": self.root / "authorized", "LOG_FILE": self.root / "agent.log"}.items():
            patcher = patch.object(agent, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.key = ec.generate_private_key(ec.SECP256R1())
        (self.root / "phone_public.der").write_bytes(self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
        (self.root / "unlock_target.txt").write_text("test-pc", encoding="ascii")

    def command(self, issued=1000, target="test-pc", key=None, nonce="00000000-0000-0000-0000-000000000001"):
        payload = f"nebula-unlock-v1\n{target}\n{issued}\n{nonce}".encode()
        signature = (key or self.key).sign(payload, ec.ECDSA(hashes.SHA256()))
        return {"id": "one", "unlock_proof": {
            "payload": base64.b64encode(payload).decode(),
            "signature": base64.b64encode(signature).decode()}}

    def test_signed_authorization_creates_short_ticket(self):
        self.assertEqual(agent.accept_command(self.command(), "", 1010), "one")
        self.assertEqual(agent.AUTHORIZATION_FILE.read_text(), "1130")

    def test_plain_hub_authorization_cannot_unlock(self):
        agent.accept_command({"id":"one", "unlock_authorized":True, "created_at":1000}, "", 1010)
        self.assertFalse(agent.AUTHORIZATION_FILE.exists())

    def test_rejects_wrong_key_target_expired_future_and_malformed(self):
        invalid = [self.command(key=ec.generate_private_key(ec.SECP256R1())),
                   self.command(target="another-pc"), self.command(issued=1),
                   self.command(issued=2000), {"id":"one", "unlock_proof":{"payload":"??"}}]
        for command in invalid:
            with self.subTest(command=command):
                agent.accept_command(command, "", 1010)
                self.assertFalse(agent.AUTHORIZATION_FILE.exists())

    def test_tampered_payload_is_rejected(self):
        command = self.command()
        command["unlock_proof"]["payload"] = self.command(issued=1001)["unlock_proof"]["payload"]
        agent.accept_command(command, "", 1010)
        self.assertFalse(agent.AUTHORIZATION_FILE.exists())

    def test_replay_rejected_after_restart_and_changed_hub_id(self):
        command = self.command()
        agent.accept_command(command, "", 1010)
        agent.AUTHORIZATION_FILE.unlink()
        command["id"] = "replayed"
        agent.accept_command(command, "", 1011)
        self.assertFalse(agent.AUTHORIZATION_FILE.exists())

    def test_replay_rejected_even_after_new_authorization(self):
        original = self.command()
        agent.accept_command(original, "", 1010)
        newer = self.command(nonce="00000000-0000-0000-0000-000000000002")
        newer["id"] = "two"
        agent.accept_command(newer, "one", 1011)
        agent.AUTHORIZATION_FILE.unlink()
        original["id"] = "replay"
        agent.accept_command(original, "two", 1012)
        self.assertFalse(agent.AUTHORIZATION_FILE.exists())

    def test_ticket_does_not_outlive_signed_request(self):
        agent.accept_command(self.command(), "", 1170)
        self.assertEqual(agent.AUTHORIZATION_FILE.read_text(), "1180")

    def test_missing_key_and_corrupt_replay_state_fail_closed(self):
        agent.STATE_FILE.write_text("bad json")
        agent.accept_command(self.command(), "", 1010)
        self.assertFalse(agent.AUTHORIZATION_FILE.exists())
        agent.STATE_FILE.unlink()
        (self.root / "phone_public.der").unlink()
        agent.accept_command(self.command(), "", 1010)
        self.assertFalse(agent.AUTHORIZATION_FILE.exists())

    def test_state_write_failure_cannot_grant_login(self):
        with patch.object(agent, "atomic_text", side_effect=OSError("disk full")):
            agent.accept_command(self.command(), "", 1010)
        self.assertFalse(agent.AUTHORIZATION_FILE.exists())

if __name__ == "__main__":
    unittest.main()
