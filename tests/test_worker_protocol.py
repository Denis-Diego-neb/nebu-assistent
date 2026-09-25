"""Contrato JobEnvelope/JobResult compartilhado entre PC e notebook."""

import copy
import json
import unittest

from nebula_worker.protocol.envelope import build_generate_envelope, envelope_digest, parse_envelope
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ids import is_ulid, new_ulid
from nebula_worker.protocol.result import ResultError, job_result, parse_job_result
from nebula_worker.protocol.version import negotiate


def envelope(**changes) -> dict:
    value = build_generate_envelope("diga oi")
    value["capability_ticket"] = {"placeholder": True}
    value.update(changes)
    return value


class ProtocoloTests(unittest.TestCase):
    def assertCode(self, code, raw, **kwargs):
        with self.assertRaises(WorkerError) as ctx:
            parse_envelope(raw, **kwargs)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)

    def test_ulid_ordenavel_e_valido(self):
        first, second = new_ulid(1_000.0), new_ulid(1_000.001)
        self.assertTrue(is_ulid(first) and is_ulid(second))
        self.assertLess(first[:10], second[:10])
        self.assertFalse(is_ulid("../../etc"))
        self.assertFalse(is_ulid("01jxxxxxxxxxxxxxxxxxxxxxxx"))

    def test_envelope_minimo_do_goal_e_aceito(self):
        parsed = parse_envelope(envelope())
        self.assertEqual(parsed.required_scope, "model:qwen_edge:generate")
        self.assertEqual(parsed.output.format, "text")

    def test_versao_desconhecida_nao_rebaixa(self):
        self.assertCode(ErrorCode.UNSUPPORTED_PROTOCOL, envelope(protocol_version="2.0"))
        self.assertCode(ErrorCode.UNSUPPORTED_PROTOCOL, envelope(protocol_version=1.0))
        with self.assertRaises(WorkerError):
            negotiate("0.9")

    def test_campos_de_contexto_global_nao_cabem_no_envelope(self):
        # INV-002: nao existe campo para objetivo global, historico ou perfil.
        for campo in ("global_goal", "full_chat_history", "user_profile", "main_pc_filesystem_root"):
            self.assertCode(ErrorCode.INVALID_ENVELOPE, envelope(**{campo: "x"}))
        extra_input = envelope()
        extra_input["input"]["history"] = []
        self.assertCode(ErrorCode.INVALID_ENVELOPE, extra_input)

    def test_tipos_exatos(self):
        booleano = envelope()
        booleano["limits"]["timeout_ms"] = True
        self.assertCode(ErrorCode.INVALID_ENVELOPE, booleano)
        texto_vazio = envelope()
        texto_vazio["input"]["payload"] = "   "
        self.assertCode(ErrorCode.INVALID_ENVELOPE, texto_vazio)
        self.assertCode(ErrorCode.INVALID_ENVELOPE, envelope(job_id="nao-e-ulid"))
        self.assertCode(ErrorCode.UNSUPPORTED_OPERATION, envelope(operation="shell"))
        self.assertCode(ErrorCode.INVALID_ENVELOPE, envelope(model_alias="Qwen Edge"))

    def test_schema_so_com_saida_json(self):
        with self.assertRaises(WorkerError):
            build_generate_envelope("x", output_format="text", schema={"type": "object"})
        ok = build_generate_envelope("x", output_format="json", schema={"type": "object"})
        self.assertEqual(ok["output"]["schema"], {"type": "object"})

    def test_ticket_obrigatorio_na_chegada(self):
        sem_ticket = build_generate_envelope("x")
        self.assertCode(ErrorCode.TICKET_INVALID, sem_ticket)
        parse_envelope(sem_ticket, require_ticket=False)

    def test_numeros_nao_finitos_recusados(self):
        with self.assertRaises(WorkerError):
            build_generate_envelope("x", temperature=float("nan"))

    def test_hash_ignora_so_o_ticket_e_sobrevive_ao_json(self):
        raw = envelope()
        digest = envelope_digest(raw)
        viajou = json.loads(json.dumps(raw))
        viajou["capability_ticket"] = {"outro": 1}
        self.assertEqual(envelope_digest(viajou), digest)
        alterado = copy.deepcopy(raw)
        alterado["input"]["payload"] = "diga tchau"
        self.assertNotEqual(envelope_digest(alterado), digest)

    def test_resultado_sucesso_e_erro_mutuamente_exclusivos(self):
        ids = {"job_id": new_ulid(), "trace_id": new_ulid()}
        ok = job_result(**ids, status="completed", output={"format": "json", "payload": {"ok": True}})
        self.assertIsNone(ok["error"])
        with self.assertRaises(ResultError):
            job_result(**ids, status="completed", output={"format": "json", "payload": {}},
                       error={"code": "MODEL_ERROR", "message": "x"})
        with self.assertRaises(ResultError):
            job_result(**ids, status="failed", output={"format": "text", "payload": "x"},
                       error={"code": "MODEL_ERROR", "message": "x"})
        with self.assertRaises(ResultError):
            job_result(**ids, status="failed", error={"code": "INVENTADO", "message": "x"})
        with self.assertRaises(ResultError):
            parse_job_result({**ok, "extra": 1})
        with self.assertRaises(ResultError):
            parse_job_result({**ok, "status": "running"})


if __name__ == "__main__":
    unittest.main()
