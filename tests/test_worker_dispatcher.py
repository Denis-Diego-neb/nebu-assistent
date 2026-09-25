"""Dispatcher do notebook: receber, validar, enfileirar, executar, cancelar, expirar, auditar."""

import copy
import tempfile
import time
import unittest
from pathlib import Path

from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.result import parse_job_result
from nebula_worker.worker.dispatcher import Limits
from tests.worker_fixtures import FakeRunner, make_dispatcher, make_signer, signed_envelope, wait_for

SEGREDO = "PROMPT-SECRETO-QUE-NAO-PODE-IR-PARA-O-DISCO"


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.signer = make_signer()
        self.runner = FakeRunner()
        self.dispatcher = None

    def tearDown(self):
        self.runner.block.clear()
        if self.dispatcher is not None:
            self.dispatcher.close()
        self.folder.cleanup()

    def start(self, **kwargs):
        self.dispatcher, self.audit = make_dispatcher(self.root, self.runner, self.signer, **kwargs)
        return self.dispatcher

    def finished(self, job_id):
        return self.dispatcher.status(job_id)["status"] in {"completed", "failed", "cancelled"}

    def test_fluxo_completo_com_resultado_tipado(self):
        dispatcher = self.start()
        raw = signed_envelope(self.signer, SEGREDO, output_format="json", temperature=0, seed=3,
                              context_tokens=4096)
        accepted = dispatcher.submit(raw)
        self.assertEqual(accepted["status"], "queued")
        self.assertEqual((accepted["job_id"], accepted["trace_id"]), (raw["job_id"], raw["trace_id"]))
        self.assertTrue(wait_for(lambda: self.finished(raw["job_id"])))
        result = parse_job_result(dispatcher.result(raw["job_id"]))
        self.assertEqual(result["output"], {"format": "json", "payload": {"ok": True}})
        self.assertEqual(result["usage"]["input_tokens"], 7)
        request = self.runner.requests[0]
        self.assertEqual((request.prompt, request.temperature, request.seed, request.context_tokens),
                         (SEGREDO, 0.0, 3, 4096))

    def test_prompt_nao_vai_para_auditoria_nem_fica_na_memoria(self):
        dispatcher = self.start()
        raw = signed_envelope(self.signer, SEGREDO)
        dispatcher.submit(raw)
        self.assertTrue(wait_for(lambda: self.finished(raw["job_id"])))
        audit_text = (self.root / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn(raw["job_id"], audit_text)
        self.assertNotIn(SEGREDO, audit_text)
        self.assertIsNone(dispatcher._store.get(raw["job_id"]).envelope)

    def test_scratch_por_job_criado_e_apagado(self):
        dispatcher = self.start()
        seen = []
        original = self.runner.generate

        def spy(request, *, cancel, deadline):
            seen.extend(path.name for path in (self.root / "jobs").iterdir())
            return original(request, cancel=cancel, deadline=deadline)

        self.runner.generate = spy
        raw = signed_envelope(self.signer)
        dispatcher.submit(raw)
        self.assertTrue(wait_for(lambda: self.finished(raw["job_id"])))
        self.assertEqual(seen, [raw["job_id"]])
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    def test_um_job_por_vez_e_fila_limitada(self):
        dispatcher = self.start(limits=Limits(max_queue=2))
        self.runner.block.set()
        first = signed_envelope(self.signer, "um")
        dispatcher.submit(first)
        self.assertTrue(self.runner.started.wait(5))
        second, third, fourth = (signed_envelope(self.signer, t) for t in ("dois", "tres", "quatro"))
        self.assertEqual(dispatcher.submit(second)["queue_position"], 1)
        self.assertEqual(dispatcher.submit(third)["queue_position"], 2)
        full = dispatcher.submit(fourth)
        self.assertEqual((full["status"], full["error"]["code"]), ("rejected", ErrorCode.QUEUE_FULL))
        self.assertEqual(dispatcher.status(first["job_id"])["status"], "running")
        self.assertEqual(len(self.runner.requests), 1)
        self.runner.block.clear()
        self.assertTrue(wait_for(lambda: self.finished(third["job_id"])))
        self.assertEqual([r.prompt for r in self.runner.requests], ["um", "dois", "tres"])

    def test_cancelar_na_fila_nao_chama_o_modelo(self):
        dispatcher = self.start()
        self.runner.block.set()
        running = signed_envelope(self.signer, "rodando")
        waiting = signed_envelope(self.signer, "esperando")
        dispatcher.submit(running)
        self.assertTrue(self.runner.started.wait(5))
        dispatcher.submit(waiting)
        cancelled = dispatcher.cancel(waiting["job_id"])
        self.assertEqual((cancelled["status"], cancelled["cancelled"]), ("cancelled", True))
        self.runner.block.clear()
        self.assertTrue(wait_for(lambda: self.finished(running["job_id"])))
        self.assertEqual([r.prompt for r in self.runner.requests], ["rodando"])
        result = dispatcher.result(waiting["job_id"])
        self.assertEqual((result["status"], result["error"]["code"]), ("cancelled", ErrorCode.CANCELLED))

    def test_cancelar_em_execucao_interrompe_o_executor(self):
        dispatcher = self.start()
        self.runner.block.set()
        raw = signed_envelope(self.signer)
        dispatcher.submit(raw)
        self.assertTrue(self.runner.started.wait(5))
        view = dispatcher.cancel(raw["job_id"])
        self.assertEqual(view["status"], "cancelled")
        self.assertEqual(dispatcher.result(raw["job_id"])["error"]["code"], ErrorCode.CANCELLED)
        again = dispatcher.cancel(raw["job_id"])
        self.assertEqual((again["status"], again["cancelled"]), ("cancelled", True))

    def test_prazo_em_execucao_e_na_fila(self):
        dispatcher = self.start()
        self.runner.block.set()
        running = signed_envelope(self.signer, "demorado", timeout_ms=300)
        dispatcher.submit(running)
        late = signed_envelope(self.signer, "atrasado", timeout_ms=100)
        dispatcher.submit(late)
        self.assertTrue(wait_for(lambda: self.finished(late["job_id"])))
        self.assertEqual(dispatcher.result(running["job_id"])["error"]["code"], ErrorCode.MODEL_TIMEOUT)
        self.assertEqual(dispatcher.result(late["job_id"])["error"]["code"], ErrorCode.DEADLINE_EXCEEDED)
        self.assertEqual([r.prompt for r in self.runner.requests], ["demorado"])

    def test_reenvio_identico_e_idempotente_e_conteudo_diferente_e_recusado(self):
        dispatcher = self.start()
        raw = signed_envelope(self.signer)
        dispatcher.submit(raw)
        self.assertTrue(wait_for(lambda: self.finished(raw["job_id"])))
        again = dispatcher.submit(copy.deepcopy(raw))
        self.assertEqual(again["status"], "completed")
        self.assertEqual(len(self.runner.requests), 1)
        clash = signed_envelope(self.signer, "outro", job_id=raw["job_id"])
        rejected = dispatcher.submit(clash)
        self.assertEqual(rejected["error"]["code"], ErrorCode.DUPLICATE_JOB)

    def test_ticket_antes_da_politica(self):
        dispatcher = self.start(limits=Limits(max_output_tokens=100))
        estranho = make_signer()
        grande = signed_envelope(estranho, max_output_tokens=5000)
        # Sem ticket valido, o chamador nao descobre o limite local.
        self.assertEqual(dispatcher.submit(grande)["error"]["code"], ErrorCode.TICKET_INVALID)
        limite = dispatcher.submit(signed_envelope(self.signer, max_output_tokens=5000))
        self.assertEqual(limite["error"]["code"], ErrorCode.LIMIT_EXCEEDED)
        alias = dispatcher.submit(signed_envelope(self.signer, model_alias="qwen_core"))
        self.assertEqual(alias["error"]["code"], ErrorCode.SCOPE_DENIED)

    def test_envelope_invalido_rejeitado_sem_registro(self):
        dispatcher = self.start()
        rejected = dispatcher.submit({"protocol_version": "1.0", "job_id": "x"})
        self.assertEqual((rejected["status"], rejected["job_id"]), ("rejected", None))
        with self.assertRaises(WorkerError) as ctx:
            dispatcher.status("01ARZ3NDEKTSV4RRFFQ69G5FAV")
        self.assertEqual(ctx.exception.code, ErrorCode.JOB_NOT_FOUND)
        with self.assertRaises(WorkerError):
            dispatcher.status("../../segredo")

    def test_resultado_antes_de_terminar(self):
        dispatcher = self.start()
        self.runner.block.set()
        raw = signed_envelope(self.signer)
        dispatcher.submit(raw)
        self.assertTrue(self.runner.started.wait(5))
        with self.assertRaises(WorkerError) as ctx:
            dispatcher.result(raw["job_id"])
        self.assertEqual((ctx.exception.code, ctx.exception.details["status"]),
                         (ErrorCode.NOT_READY, "running"))

    def test_saida_json_invalida_ou_truncada_e_falha(self):
        dispatcher = self.start()
        self.runner.output = self.runner.output.__class__('{"ok": tru', 3, 64, "length")
        truncated = signed_envelope(self.signer, output_format="json")
        dispatcher.submit(truncated)
        self.assertTrue(wait_for(lambda: self.finished(truncated["job_id"])))
        self.assertEqual(dispatcher.result(truncated["job_id"])["error"]["code"], ErrorCode.OUTPUT_TRUNCATED)
        self.runner.output = self.runner.output.__class__("isto nao e json", 3, 4, "stop")
        invalid = signed_envelope(self.signer, output_format="json")
        dispatcher.submit(invalid)
        self.assertTrue(wait_for(lambda: self.finished(invalid["job_id"])))
        error = dispatcher.result(invalid["job_id"])["error"]
        self.assertEqual(error["code"], ErrorCode.INVALID_OUTPUT)
        self.assertEqual(error["details"]["raw_output"], "isto nao e json")
        self.runner.output = self.runner.output.__class__("texto cortado", 3, 64, "length")
        text = signed_envelope(self.signer)
        dispatcher.submit(text)
        self.assertTrue(wait_for(lambda: self.finished(text["job_id"])))
        self.assertTrue(dispatcher.result(text["job_id"])["output"]["truncated"])

    def test_resultado_expira_e_some_da_memoria(self):
        clock = {"now": 1000.0}
        self.dispatcher, _ = make_dispatcher(
            self.root, self.runner, self.signer,
            limits=Limits(result_ttl_seconds=30, forget_after_seconds=60), autostart=False,
        )
        self.dispatcher.monotonic = lambda: clock["now"]
        self.dispatcher.start()
        raw = signed_envelope(self.signer)
        self.dispatcher.submit(raw)
        self.assertTrue(wait_for(lambda: self.finished(raw["job_id"])))
        clock["now"] += 31
        self.assertTrue(wait_for(lambda: self.dispatcher.status(raw["job_id"])["status"] == "expired",
                                 timeout=3))
        expired = self.dispatcher.result(raw["job_id"])
        self.assertEqual((expired["status"], expired["error"]["code"]), ("expired", ErrorCode.EXPIRED))
        self.assertIsNone(expired["usage"])
        clock["now"] += 61
        self.assertTrue(wait_for(lambda: raw["job_id"] not in self.dispatcher._store, timeout=3))

    def test_saude_e_capacidades_sem_shell(self):
        dispatcher = self.start()
        health = dispatcher.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["models"], {"qwen_edge": {"available": True}})
        capabilities = dispatcher.capabilities()
        self.assertEqual(capabilities["models"], {"qwen_edge": {"operations": ["generate"]}})
        self.assertFalse(capabilities["remote_shell"])
        self.assertFalse(capabilities["remote_filesystem"])

    def test_rascunhos_orfaos_sao_limpos_na_partida(self):
        orphan = self.root / "jobs" / "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        orphan.mkdir(parents=True)
        (orphan / "lixo.txt").write_text("x", encoding="utf-8")
        self.start()
        self.assertFalse(orphan.exists())

    def test_encerrar_cancela_o_job_em_andamento(self):
        dispatcher = self.start()
        self.runner.block.set()
        raw = signed_envelope(self.signer)
        dispatcher.submit(raw)
        self.assertTrue(self.runner.started.wait(5))
        started = time.monotonic()
        dispatcher.close()
        self.dispatcher = None
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
