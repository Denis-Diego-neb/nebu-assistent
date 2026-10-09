"""Worker completo por HTTP real: guarda, catalogo MCP, cliente do PC e demo da secao 32."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import anyio
import httpx2
import uvicorn
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from core.mcp.clients.notebook_worker import (
    NotebookWorkerChat,
    NotebookWorkerClient,
    NotebookWorkerError,
    NotebookWorkerUnavailable,
)
from nebula_worker.config import parse_config
from nebula_worker.gateway.guard import GatewayGuard
from nebula_worker.observability.audit import AuditLog
from nebula_worker.protocol.envelope import build_generate_envelope
from nebula_worker.server import build_app, build_dispatcher, uvicorn_config
from tests.worker_fixtures import FakeOllama, free_port, make_signer

TOKEN = "gateway-token-" + "x" * 30
PROMPT = 'return exactly {"ok": true}'


class GuardaTests(unittest.TestCase):
    """Guarda HTTP chamado direto como app ASGI, sem rede."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.audit = AuditLog(Path(self.folder.name) / "audit.jsonl")
        self.clock = {"now": 100.0}
        self.calls = []

        async def inner(scope, receive, send):
            self.calls.append(scope["type"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        from ipaddress import ip_network

        self.guard = GatewayGuard(inner, token=TOKEN, allowed_clients=[ip_network("127.0.0.1/32")],
                                  requests_per_minute=10, audit=self.audit,
                                  clock=lambda: self.clock["now"])

    def tearDown(self):
        self.folder.cleanup()

    def call(self, headers=(), client=("127.0.0.1", 5000), kind="http"):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": kind, "headers": list(headers), "client": client, "method": "POST", "path": "/mcp"}
        anyio.run(self.guard, scope, receive, send)
        return sent[0].get("status") if sent else None, sent

    def auth(self, token=TOKEN):
        return [(b"authorization", f"Bearer {token}".encode())]

    def test_token_correto_passa(self):
        status, _ = self.call(self.auth())
        self.assertEqual((status, self.calls), (200, ["http"]))

    def test_token_ausente_errado_ou_duplicado(self):
        self.assertEqual(self.call()[0], 401)
        self.assertEqual(self.call(self.auth("y" * 44))[0], 401)
        self.assertEqual(self.call(self.auth() + self.auth())[0], 401)
        self.assertEqual(self.calls, [])

    def test_cliente_fora_da_lista(self):
        self.assertEqual(self.call(self.auth(), client=("192.168.15.99", 5000))[0], 403)
        self.assertEqual(self.call(self.auth(), client=("::ffff:127.0.0.1", 5000))[0], 200)
        self.assertEqual(self.call(self.auth(), client=None)[0], 403)

    def test_limite_de_taxa_por_cliente(self):
        statuses = [self.call(self.auth())[0] for _ in range(11)]
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10], 429)
        self.clock["now"] += 6  # 10/min: um pedido a cada 6 s volta a caber
        self.assertEqual(self.call(self.auth())[0], 200)

    def test_websocket_recusado(self):
        _, sent = self.call(self.auth(), kind="websocket")
        self.assertEqual(sent[0]["type"], "websocket.close")

    def test_negacoes_auditadas_sem_inundar(self):
        for _ in range(5):
            self.call()
        lines = (Path(self.folder.name) / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["reason"], "missing_token")


class WorkerHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.ollama = FakeOllama().__enter__()
        cls.signer = make_signer()
        cls.port = free_port()
        cls.config = parse_config({
            "bind_host": "127.0.0.1", "port": cls.port,
            "trusted_keys": {cls.signer.key_id: cls.signer.public_key_text},
            "models": {"qwen_edge": {"model": "qwen3.5:9b", "base_url": cls.ollama.url}},
            "runtime_dir": str(root / "runtime"),
        }, {"NEBULA_WORKER_TOKEN": TOKEN})
        cls.dispatcher, audit = build_dispatcher(cls.config)
        cls.server = uvicorn.Server(uvicorn_config(cls.config, build_app(cls.config, cls.dispatcher, audit)))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        limit = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < limit:
            time.sleep(0.02)
        cls.url = f"http://127.0.0.1:{cls.port}/mcp"
        cls.client = NotebookWorkerClient(cls.url, TOKEN, cls.signer, poll_interval=0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.dispatcher.close()
        cls.ollama.__exit__(None, None, None)
        cls.folder.cleanup()

    def test_catalogo_so_tem_as_seis_tools_do_goal(self):
        async def names():
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
                async with Client(streamable_http_client(self.url, http_client=http,
                                                         terminate_on_close=False)) as client:
                    return sorted(tool.name for tool in (await client.list_tools()).tools)

        self.assertEqual(anyio.run(names), [
            "worker.cancel", "worker.capabilities", "worker.health",
            "worker.result", "worker.status", "worker.submit",
        ])

    def test_demo_da_secao_32(self):
        envelope = build_generate_envelope(
            PROMPT, output_format="json", temperature=0, seed=32, max_output_tokens=64,
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        )
        result = self.client.run_sync(envelope)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"]["payload"], {"ok": True})
        self.assertEqual((result["job_id"], result["trace_id"]), (envelope["job_id"], envelope["trace_id"]))
        sent = self.ollama.requests[-1]
        self.assertEqual(sent["messages"], [{"role": "user", "content": PROMPT}])
        audit = (self.config.runtime_dir / "audit" / "worker.jsonl").read_text(encoding="utf-8")
        self.assertIn(envelope["trace_id"], audit)
        self.assertNotIn("return exactly", audit)

    def test_chat_com_a_interface_das_sprints(self):
        chat = NotebookWorkerChat(self.client, timeout=30)
        self.assertEqual(json.loads(chat.chat("revise", format_schema={"type": "object"},
                                              temperature=0.0, num_ctx=16384, num_predict=200,
                                              seed=1, num_gpu=0, num_thread=14)), {"ok": True})
        self.assertTrue(chat.is_alive())
        options = self.ollama.requests[-1]["options"]
        self.assertNotIn("num_gpu", options)
        self.assertNotIn("num_thread", options)

    def test_rejeicao_tipada_chega_ao_pc(self):
        estranho = NotebookWorkerClient(self.url, TOKEN, make_signer())
        with self.assertRaises(NotebookWorkerError) as ctx:
            estranho.run_sync(build_generate_envelope("x"))
        self.assertEqual(ctx.exception.code, "TICKET_INVALID")
        with self.assertRaises(NotebookWorkerError) as ctx:
            anyio.run(self.client.status, "01ARZ3NDEKTSV4RRFFQ69G5FAV")
        self.assertEqual(ctx.exception.code, "JOB_NOT_FOUND")

    def test_token_errado_e_worker_desligado(self):
        with self.assertRaises(NotebookWorkerUnavailable) as ctx:
            NotebookWorkerClient(self.url, "z" * 40, self.signer).health_sync()
        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")
        desligado = NotebookWorkerClient(f"http://127.0.0.1:{free_port()}/mcp", TOKEN, self.signer)
        with self.assertRaises(NotebookWorkerUnavailable) as ctx:
            desligado.health_sync()
        self.assertEqual(ctx.exception.code, "WORKER_UNREACHABLE")
        self.assertFalse(NotebookWorkerChat(desligado).is_alive())

    def test_protecoes_http_do_transporte(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        auth = {"Authorization": f"Bearer {TOKEN}"}

        async def post(**kwargs):
            async with httpx2.AsyncClient(timeout=10) as http:
                return (await http.post(self.url, **kwargs)).status_code

        self.assertEqual(anyio.run(lambda: post(json=body)), 401)
        with self.assertLogs("mcp.server.transport_security", level="WARNING"):
            self.assertEqual(anyio.run(lambda: post(json=body, headers={**auth, "Host": "evil.example"})), 421)
            self.assertEqual(anyio.run(lambda: post(json=body, headers={**auth, "Origin": "https://evil.example"})), 403)
        self.assertEqual(anyio.run(lambda: post(content=json.dumps(body).encode(),
                                                headers={**auth, "Content-Type": "text/plain"})), 400)

    def test_argumentos_fora_do_contrato(self):
        async def call():
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
                async with Client(streamable_http_client(self.url, http_client=http,
                                                         terminate_on_close=False)) as client:
                    return await client.call_tool("worker.status", {"job_id": "x", "cwd": "C:\\"})

        result = anyio.run(call)
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "INVALID_ENVELOPE")


if __name__ == "__main__":
    unittest.main()
