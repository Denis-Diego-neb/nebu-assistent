"""Tickets de capacidade: assinatura, vinculo, prazo, escopo e reenvio."""

import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

from nebula_worker.capabilities.validator import TicketValidator
from nebula_worker.protocol.envelope import build_generate_envelope, envelope_digest, parse_envelope
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ticket import sign_ticket
from tests.worker_fixtures import SCOPE, make_signer, signed_envelope


class TicketTests(unittest.TestCase):
    def setUp(self):
        self.signer = make_signer()
        self.now = time.time()
        self.validator = self.make_validator()

    def make_validator(self, **kwargs):
        options = {"max_ttl_seconds": 600, "clock_skew_seconds": 60, "clock": lambda: self.now}
        options.update(kwargs)
        return TicketValidator({self.signer.key_id: self.signer.public_key}, frozenset({SCOPE}), **options)

    def assertCode(self, code, raw, validator=None):
        with self.assertRaises(WorkerError) as ctx:
            (validator or self.validator).validate(parse_envelope(raw))
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)

    def ticket_for(self, raw, **kwargs):
        unsigned = {k: v for k, v in raw.items() if k != "capability_ticket"}
        options = {"job_id": unsigned["job_id"], "scopes": [SCOPE],
                   "envelope_sha256": envelope_digest(unsigned), "ttl_seconds": 300, "now": self.now}
        options.update(kwargs)
        return {**unsigned, "capability_ticket": sign_ticket(self.signer._private_key, **options)}

    def test_ticket_valido_passa_pelo_json(self):
        raw = json.loads(json.dumps(signed_envelope(self.signer)))
        validated = self.validator.validate(parse_envelope(raw))
        self.assertEqual(validated.scopes, (SCOPE,))

    def test_envelope_alterado_apos_assinatura(self):
        raw = signed_envelope(self.signer)
        raw["input"]["payload"] = "apague tudo"
        self.assertCode(ErrorCode.TICKET_INVALID, raw)
        raw = signed_envelope(self.signer)
        raw["generation"] = {"temperature": 1.5}
        self.assertCode(ErrorCode.TICKET_INVALID, raw)

    def test_assinatura_de_outra_chave_e_campos_trocados(self):
        estranho = make_signer()
        self.assertCode(ErrorCode.TICKET_INVALID, signed_envelope(estranho))
        raw = signed_envelope(self.signer)
        raw["capability_ticket"]["scopes"] = [SCOPE, "model:qwen_edge:embed"]
        self.assertCode(ErrorCode.TICKET_INVALID, raw)
        raw = signed_envelope(self.signer)
        raw["capability_ticket"]["signature"] = raw["capability_ticket"]["signature"][::-1]
        self.assertCode(ErrorCode.TICKET_INVALID, raw)

    def test_ticket_de_outro_job(self):
        outro = build_generate_envelope("x")
        raw = self.ticket_for(build_generate_envelope("diga oi"), job_id=outro["job_id"])
        self.assertCode(ErrorCode.TICKET_INVALID, raw)

    def test_prazos(self):
        base = build_generate_envelope("x")
        self.assertCode(ErrorCode.TICKET_EXPIRED, self.ticket_for(base, now=self.now - 1000))
        self.assertCode(ErrorCode.TICKET_INVALID, self.ticket_for(base, now=self.now + 600))
        self.assertCode(ErrorCode.TICKET_INVALID, self.ticket_for(base, ttl_seconds=3600))
        # Dentro da tolerancia de relogio continua valido.
        self.validator.validate(parse_envelope(self.ticket_for(base, now=self.now + 30)))

    def test_escopos_menor_privilegio(self):
        base = build_generate_envelope("x")
        self.assertCode(ErrorCode.SCOPE_DENIED, self.ticket_for(base, scopes=["model:qwen_edge:embed"]))
        self.assertCode(ErrorCode.SCOPE_DENIED, self.ticket_for(base, scopes=[SCOPE, "shell:run"]))
        with self.assertRaises(WorkerError):
            self.ticket_for(base, scopes=["model:*:generate"])
        with self.assertRaises(ValueError):
            TicketValidator({self.signer.key_id: self.signer.public_key}, frozenset({"nebula:*"}),
                            max_ttl_seconds=600, clock_skew_seconds=60)

    def test_reenvio_bloqueado_mesmo_depois_de_reiniciar(self):
        with tempfile.TemporaryDirectory() as folder:
            replay = Path(folder) / "replay.json"
            validator = self.make_validator(replay_file=replay)
            raw = signed_envelope(self.signer)
            validator.consume(validator.validate(parse_envelope(raw)))
            self.assertCode(ErrorCode.TICKET_REPLAYED, copy.deepcopy(raw), validator)
            reiniciado = self.make_validator(replay_file=replay)
            self.assertCode(ErrorCode.TICKET_REPLAYED, copy.deepcopy(raw), reiniciado)
            self.assertNotIn("diga oi", replay.read_text(encoding="utf-8"))

    def test_consumo_duplo_concorrente(self):
        raw = signed_envelope(self.signer)
        first = self.validator.validate(parse_envelope(raw))
        second = self.validator.validate(parse_envelope(raw))
        self.validator.consume(first)
        with self.assertRaises(WorkerError) as ctx:
            self.validator.consume(second)
        self.assertEqual(ctx.exception.code, ErrorCode.TICKET_REPLAYED)


if __name__ == "__main__":
    unittest.main()
