"""Executor Qwen Edge contra um Ollama falso em loopback (sem modelo real)."""

import threading
import time
import unittest

from nebula_worker.models.ollama_client import GenerationRequest, OllamaRunner
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from tests.worker_fixtures import FakeOllama, free_port


def request(**changes) -> GenerationRequest:
    values = {"prompt": "so isto", "system": None, "output_format": "text", "schema": None,
              "max_output_tokens": 64}
    values.update(changes)
    return GenerationRequest(**values)


def deadline(seconds: float = 10.0) -> float:
    return time.monotonic() + seconds


class OllamaRunnerTests(unittest.TestCase):
    def test_streaming_monta_texto_e_uso(self):
        with FakeOllama() as ollama:
            runner = OllamaRunner(ollama.url, "qwen3.5:9b", options={"num_thread": 6, "temperature": 0.7})
            output = runner.generate(request(), cancel=threading.Event(), deadline=deadline())
        self.assertEqual(output.text, '{"ok": true}')
        self.assertEqual((output.input_tokens, output.output_tokens, output.stop_reason), (11, 6, "stop"))

    def test_corpo_so_com_o_prompt_isolado_e_opcoes_locais(self):
        schema = {"type": "object"}
        with FakeOllama() as ollama:
            runner = OllamaRunner(ollama.url, "qwen3.5:9b",
                                  options={"num_thread": 6, "num_gpu": 0, "temperature": 0.7})
            runner.generate(request(system="seja breve", output_format="json", schema=schema,
                                    temperature=0.0, seed=9, context_tokens=8192, think=False),
                            cancel=threading.Event(), deadline=deadline())
        body = ollama.requests[0]
        self.assertEqual(body["model"], "qwen3.5:9b")
        self.assertEqual(body["messages"], [{"role": "system", "content": "seja breve"},
                                            {"role": "user", "content": "so isto"}])
        self.assertEqual(body["format"], schema)
        self.assertIs(body["stream"], True)
        self.assertIs(body["think"], False)
        # O pedido define amostragem e limites; hardware continua decisao do notebook.
        self.assertEqual(body["options"], {"num_thread": 6, "num_gpu": 0, "num_predict": 64,
                                           "temperature": 0.0, "seed": 9, "num_ctx": 8192})

    def test_json_sem_schema_usa_formato_json(self):
        with FakeOllama() as ollama:
            OllamaRunner(ollama.url, "m").generate(request(output_format="json"),
                                                   cancel=threading.Event(), deadline=deadline())
        self.assertEqual(ollama.requests[0]["format"], "json")

    def test_cancelamento_no_meio_da_geracao_fecha_a_conexao(self):
        hold = threading.Event()
        hold.set()
        cancel = threading.Event()
        with FakeOllama(hold=hold) as ollama:
            runner = OllamaRunner(ollama.url, "m")
            threading.Timer(0.3, cancel.set).start()
            started = time.monotonic()
            with self.assertRaises(WorkerError) as ctx:
                runner.generate(request(), cancel=cancel, deadline=deadline())
            self.assertEqual(ctx.exception.code, ErrorCode.CANCELLED)
            self.assertLess(time.monotonic() - started, 3)
            # O Ollama percebe a desconexao e para de gerar.
            self.assertTrue(ollama.disconnected.wait(3))

    def test_prazo_interrompe_a_geracao(self):
        hold = threading.Event()
        hold.set()
        with FakeOllama(hold=hold) as ollama:
            with self.assertRaises(WorkerError) as ctx:
                OllamaRunner(ollama.url, "m").generate(request(), cancel=threading.Event(),
                                                       deadline=deadline(0.4))
        self.assertEqual(ctx.exception.code, ErrorCode.MODEL_TIMEOUT)

    def test_modelo_ausente_e_ollama_desligado(self):
        with FakeOllama(status=404) as ollama:
            with self.assertRaises(WorkerError) as ctx:
                OllamaRunner(ollama.url, "inexistente").generate(
                    request(), cancel=threading.Event(), deadline=deadline())
        self.assertEqual(ctx.exception.code, ErrorCode.MODEL_UNAVAILABLE)
        desligado = OllamaRunner(f"http://127.0.0.1:{free_port()}", "m", connect_timeout=1)
        with self.assertRaises(WorkerError) as ctx:
            desligado.generate(request(), cancel=threading.Event(), deadline=deadline())
        self.assertEqual(ctx.exception.code, ErrorCode.MODEL_UNAVAILABLE)
        self.assertFalse(desligado.is_available(timeout=0.5))

    def test_resposta_grande_demais_e_interrompida(self):
        with FakeOllama(pieces=["x" * 600, "y" * 600]) as ollama:
            with self.assertRaises(WorkerError) as ctx:
                OllamaRunner(ollama.url, "m", max_response_bytes=1000).generate(
                    request(), cancel=threading.Event(), deadline=deadline())
        self.assertEqual(ctx.exception.code, ErrorCode.OUTPUT_TOO_LARGE)

    def test_cancelado_antes_de_iniciar(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(WorkerError) as ctx:
            OllamaRunner("http://127.0.0.1:11434", "m").generate(request(), cancel=cancel,
                                                                 deadline=deadline())
        self.assertEqual(ctx.exception.code, ErrorCode.CANCELLED)

    def test_url_precisa_ser_http(self):
        with self.assertRaises(ValueError):
            OllamaRunner("file:///etc/passwd", "m")


if __name__ == "__main__":
    unittest.main()
