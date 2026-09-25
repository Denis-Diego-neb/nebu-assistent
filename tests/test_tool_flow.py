import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

import requests

from abajur_wifi import ErroAbajur
from core.action_contracts import AcaoQwen, ResultadoQwen
from core.dispatcher import Dispatcher
from core.registry import Registry, Tool
from main import Nebula
from services.network import DeviceConnection, DeviceEndpoint
from services.tool_server import ToolServer


def make_dispatcher(handler):
    registry = Registry()

    def validate(arguments):
        if set(arguments) != {"value"} or type(arguments["value"]) is not int:
            raise ValueError("value deve ser inteiro")
        return arguments

    registry.register(Tool("example", "Exemplo", {"type": "object"}, handler, validate))
    return Dispatcher(registry)


class DispatcherTests(unittest.TestCase):
    def test_valida_plano_inteiro_antes_de_executar(self):
        handler = Mock(return_value={"ok": True})
        dispatcher = make_dispatcher(handler)
        for invalid in ({"name": "inventada", "arguments": {}},
                        {"name": "example", "arguments": {"value": "texto"}}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                dispatcher.execute_plan([{"name": "example", "arguments": {"value": 1}}, invalid])
        handler.assert_not_called()

    def test_falha_e_confirmacao_interrompem_plano(self):
        for first in ({"ok": False}, {"ok": True, "requires_confirmation": True}):
            handler = Mock(return_value=first)
            result = make_dispatcher(handler).execute_plan([
                {"name": "example", "arguments": {"value": 1}},
                {"name": "example", "arguments": {"value": 2}},
            ])
            self.assertEqual(len(result), 1)
            handler.assert_called_once_with({"value": 1})

    def test_excecao_na_tool_nao_vaza_detalhes(self):
        handler = Mock(side_effect=RuntimeError("segredo de teste"))
        result = make_dispatcher(handler).call_tool({"name": "example", "arguments": {"value": 1}})
        self.assertFalse(result["ok"])
        self.assertNotIn("segredo", str(result))


class HostFlowTests(unittest.TestCase):
    def setUp(self):
        self.saida = Mock()
        self.codex = Mock()
        self.host = Nebula(self.saida, abrir_navegador=False, ao_encaminhar_codex=self.codex)

    @patch.dict(os.environ, {"NEBULA_QWEN_ENABLED": "1"})
    def test_qwen_escolhe_ate_comando_conhecido_sem_reinterpretacao(self):
        lamp = Mock()
        self.host._controle_abajur = lamp
        with patch.object(self.host.conversa, "interpretar_ou_responder", return_value=ResultadoQwen(
            "comando", (AcaoQwen("abajur_ligar"),)
        )) as qwen, patch("main.interpretar_comandos_abajur", side_effect=AssertionError("reinterpretação")):
            self.assertTrue(self.host.executar("ligue o abajur"))
        qwen.assert_called_once_with("ligue o abajur")
        lamp.energia.assert_called_once_with(True)

    def test_argumento_de_pesquisa_nao_vira_comando_de_dispositivo(self):
        with patch.object(self.host, "pesquisar_google") as search, patch.object(
            self.host, "_executar_local", side_effect=AssertionError("não deve reinterpretar")
        ):
            result = self.host.dispatcher.call_tool({
                "name": "pesquisar_google", "arguments": {"argumento": "ligue o abajur"},
            })
        self.assertTrue(result["ok"])
        search.assert_called_once_with("ligue o abajur")

    def test_falha_abajur_impede_proxima_tool(self):
        lamp = Mock()
        lamp.energia.side_effect = ErroAbajur("falha simulada")
        self.host._controle_abajur = lamp
        result = self.host.dispatcher.execute_plan([
            {"name": "abajur_ligar", "arguments": {"argumento": ""}},
            {"name": "abajur_cor", "arguments": {"argumento": "azul"}},
        ])
        self.assertFalse(result[0]["ok"])
        lamp.cor.assert_not_called()
        self.saida.falar.assert_called_once()

    @patch.dict(os.environ, {"NEBULA_QWEN_ENABLED": "1"})
    def test_codigo_preserva_texto_e_encaminha_sem_acionar_dispositivos(self):
        text = 'Corrija Foo.py: print("Olá")'
        response = Mock()
        response.json.return_value = {"message": {"content": json.dumps({
            "tipo": "comando", "acoes": [{"acao": "encaminhar_codex", "argumento": "resumo"}],
            "resposta": "",
        })}}
        with patch("integrations.llm.qwen.requests.post", return_value=response), patch.object(
            self.host, "_executar_local", side_effect=AssertionError("executou local")
        ):
            self.host.executar(text)
        self.codex.assert_called_once_with(text)

    def test_tool_nao_chama_qwen(self):
        self.host._controle_abajur = Mock()
        with patch.object(self.host.conversa, "interpretar_ou_responder", side_effect=AssertionError("Qwen")):
            self.assertTrue(self.host.dispatcher.call_tool({
                "name": "abajur_ligar", "arguments": {"argumento": ""},
            })["ok"])

    def test_tool_ambilight_chama_executor_direto_sem_frase_legada(self):
        with patch.object(Nebula, "_iniciar_modo_ambilight", autospec=True) as iniciar:
            host = Nebula(self.saida, abrir_navegador=False)
            self.addCleanup(host.fechar)
            with patch.object(
                host, "_executar_local", side_effect=AssertionError("nao deve reinterpretar")
            ):
                result = host.dispatcher.call_tool({
                    "name": "modo_ambilight_iniciar",
                    "arguments": {"argumento": ""},
                })
        self.assertTrue(result["ok"])
        iniciar.assert_called_once_with(host)

    def test_tool_de_volume_chama_executor_direto_sem_frase_legada(self):
        with patch("main.ajustar_volume_youtube", return_value=False) as volume, patch.object(
            self.host, "_executar_local", side_effect=AssertionError("nao deve reinterpretar")
        ):
            result = self.host.dispatcher.call_tool({
                "name": "diminuir_volume", "arguments": {"argumento": ""},
            })
        volume.assert_called_once_with(aumentar=False, passos=2)
        self.assertFalse(result["ok"])

    @patch.dict(os.environ, {"NEBULA_QWEN_ENABLED": "1"})
    def test_confirmacao_pendente_nao_consulta_modelo(self):
        self.host.comando_pendente = "confirmar_desligar_pc"
        with patch.object(self.host.conversa, "interpretar_ou_responder", side_effect=AssertionError("Qwen")):
            self.host.executar("cancelar")
        self.assertIsNone(self.host.comando_pendente)


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.endpoint = DeviceEndpoint(
            "http://pc.lan:8767", "http://pc.tailnet:8767", "token-teste-com-24-caracteres"
        )
        self.client = DeviceConnection(self.endpoint, self.session)
        self.discovery = Mock(status_code=200)
        self.discovery.json.return_value = {"tools": [{"name": "example"}]}

    def test_prefere_lan(self):
        self.session.get.return_value = self.discovery
        url, _ = self.client.discover()
        self.assertEqual(url, self.endpoint.lan_url)
        self.assertEqual(self.session.get.call_count, 1)

    def test_fora_da_lan_usa_rota_remota(self):
        self.session.get.side_effect = [requests.ConnectTimeout(), self.discovery]
        url, _ = self.client.discover()
        self.assertEqual(url, self.endpoint.remote_url)
        self.assertEqual(self.session.get.call_count, 2)

    def test_timeout_de_execucao_nao_repete_o_post(self):
        self.session.get.return_value = self.discovery
        self.session.post.side_effect = requests.ReadTimeout()
        with self.assertRaisesRegex(ConnectionError, "não foi reenviado"):
            self.client.call_tool("example", {"value": 1})
        self.session.post.assert_called_once()

    def test_token_invalido_nao_causa_retry(self):
        self.session.get.return_value = Mock(status_code=401)
        with self.assertRaises(PermissionError):
            self.client.discover()
        self.session.get.assert_called_once()
        self.assertNotIn(self.endpoint.token, repr(self.endpoint))

    def test_servidor_generico_http_fim_a_fim(self):
        handler = Mock(return_value={"ok": True, "value": 42})
        token = "token-http-teste-com-24-caracteres"
        with ToolServer(("127.0.0.1", 0), make_dispatcher(handler), token) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                client = DeviceConnection(DeviceEndpoint(url, "", token))
                self.assertEqual(client.call_tool("example", {"value": 42})["value"], 42)
                handler.assert_called_once_with({"value": 42})
                with self.assertRaises(PermissionError):
                    DeviceConnection(DeviceEndpoint(url, "", "token-errado-com-24-caracteres")).discover()
                r = requests.post(url + "/api/tools/call", headers={"Authorization": "Bearer " + token},
                                  json={"name": "nao_existe", "arguments": {}}, timeout=2)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(handler.call_count, 1)
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_painel_existente_expoe_mesmo_contrato(self):
        import remote_server

        handler = Mock(return_value={"ok": True})
        dispatcher = make_dispatcher(handler)
        token = "token-painel-teste-com-24-caracteres"
        with patch.object(remote_server.STATE, "tools_provider", return_value=dispatcher), patch.object(
            remote_server.STATE, "sessions", {token}
        ), ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                client = DeviceConnection(DeviceEndpoint(url, "", token))
                self.assertTrue(client.call_tool("example", {"value": 7})["ok"])
                handler.assert_called_once_with({"value": 7})
                self.assertEqual(requests.get(url + "/api/tools", timeout=2).status_code, 401)
            finally:
                server.shutdown()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
