"""Rotas /api/collaboration: a ponte entre o painel e o backend da colaboração.

O backend fica em ``services/collaboration/`` e é mantido pelo outro agente.
Aqui só se testa o lado que é meu: a autenticação na frente, o que acontece
enquanto a API do Codex não existe, e o repasse fiel de método, caminho, corpo,
status e resposta. Nenhuma regra de negócio é reimplementada deste lado.
"""

import json
import sys
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer

import remote_server


class ApiFalsa:
    """Dublê no formato de services/collaboration/README.md."""

    def __init__(self, resposta=(200, {"ideas": []}), erro=None):
        self.resposta = resposta
        self.erro = erro
        self.chamadas = []

    def handle(self, method, path, body):
        self.chamadas.append((method, path, body))
        if self.erro is not None:
            raise self.erro
        return self.resposta


def modulo_com(api):
    """Publica ``services.collaboration.api`` sem tocar na pasta do Codex."""
    modulo = types.ModuleType("services.collaboration.api")
    modulo.CollaborationAPI = lambda _raiz: api
    return modulo


class ColaboracaoRotasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.pote = CookieJar()
        self.abridor = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.pote)
        )
        ticket = remote_server.criar_ticket_espaco()
        self.abridor.open(f"{self.base}/espaco/?ticket={ticket}", timeout=5)
        self.original = sys.modules.get("services.collaboration.api")
        self.instalar(None)

    def tearDown(self) -> None:
        sys.modules.pop("services.collaboration.api", None)
        if self.original is not None:
            sys.modules["services.collaboration.api"] = self.original
        remote_server._COLABORACAO["api"] = None
        remote_server._COLABORACAO["tentado_em"] = 0.0

    def instalar(self, api):
        """Troca a API vista pelas rotas e zera o cache do adaptador.

        Com ``api=None`` o backend real do Codex é escondido: uma entrada
        ``None`` em ``sys.modules`` faz o ``import`` levantar ImportError, que é
        exatamente o que o adaptador vê antes de a pasta existir.
        """
        sys.modules["services.collaboration.api"] = modulo_com(api) if api else None
        remote_server._COLABORACAO["api"] = api
        remote_server._COLABORACAO["tentado_em"] = 0.0
        return api

    def pegar(self, caminho):
        return self.abridor.open(self.base + caminho, timeout=5)

    def postar(self, caminho, corpo):
        pedido = urllib.request.Request(
            self.base + caminho,
            data=json.dumps(corpo).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return self.abridor.open(pedido, timeout=5)

    # ------------------------------------------------------------ sem backend
    def test_sem_a_api_do_codex_a_rota_avisa_em_vez_de_quebrar(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pegar("/api/collaboration")
        self.assertEqual(erro.exception.code, 503)
        corpo = json.loads(erro.exception.read())
        self.assertTrue(corpo["aguardando_backend"])
        self.assertIn("services/collaboration", corpo["error"])

    def test_api_que_aparece_depois_e_detectada_sem_reiniciar_a_nebula(self) -> None:
        with self.assertRaises(urllib.error.HTTPError):
            self.pegar("/api/collaboration")
        self.instalar(ApiFalsa((200, {"ideas": [{"id": "a1"}]})))
        self.assertEqual(json.loads(self.pegar("/api/collaboration").read())["ideas"][0]["id"], "a1")

    # ---------------------------------------------------------------- repasse
    def test_snapshot_chega_intacto_ao_painel(self) -> None:
        estado = {
            "ideas": [{"id": "a1", "text": "painel da dupla", "status": "pending"}],
            "tasks": [{"id": "t1", "priority": 4.5, "owner": "claude"}],
            "confirmations": [{"idea_id": "a1", "agent": "astra", "text": "assumo o backend"}],
            "messages": [], "budgets": {"a1": {}}, "paused": False,
            "active_run": None, "log_path": "SESSOES.md",
        }
        self.instalar(ApiFalsa((200, estado)))
        self.assertEqual(json.loads(self.pegar("/api/collaboration").read()), estado)

    def test_metodo_caminho_e_corpo_chegam_como_vieram(self) -> None:
        api = self.instalar(ApiFalsa((202, {"ok": True})))
        self.pegar("/api/collaboration/log")
        self.postar("/api/collaboration/ideas", {"text": "ideia", "token_budget": 60000})
        self.postar("/api/collaboration/run", {"idea_id": "a1"})
        self.postar("/api/collaboration/pause", {"paused": True})
        self.postar("/api/collaboration/messages", {"idea_id": "a1", "text": "oi"})
        self.assertEqual(api.chamadas, [
            ("GET", "/api/collaboration/log", {}),
            ("POST", "/api/collaboration/ideas", {"text": "ideia", "token_budget": 60000}),
            ("POST", "/api/collaboration/run", {"idea_id": "a1"}),
            ("POST", "/api/collaboration/pause", {"paused": True}),
            ("POST", "/api/collaboration/messages", {"idea_id": "a1", "text": "oi"}),
        ])

    def test_status_do_backend_e_preservado(self) -> None:
        self.instalar(ApiFalsa((202, {"ok": True})))
        self.assertEqual(self.postar("/api/collaboration/run", {"idea_id": "a1"}).status, 202)

    def test_recusa_do_backend_chega_ao_painel_com_o_motivo(self) -> None:
        self.instalar(ApiFalsa((409, {"error": "Arquivos reservados por astra"})))
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.postar("/api/collaboration/run", {"idea_id": "a1"})
        self.assertEqual(erro.exception.code, 409)
        self.assertIn("reservados", json.loads(erro.exception.read())["error"])

    def test_excecao_do_backend_vira_502_e_nao_derruba_o_painel(self) -> None:
        self.instalar(ApiFalsa(erro=RuntimeError("banco travado")))
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pegar("/api/collaboration")
        self.assertEqual(erro.exception.code, 502)
        self.assertIn("banco travado", json.loads(erro.exception.read())["error"])

    def test_a_rota_nao_bloqueia_com_a_nebula_pausada(self) -> None:
        """Coordenar as duas precisa funcionar mesmo com a assistente pausada."""
        self.instalar(ApiFalsa((200, {"ok": True})))
        pausada = remote_server.STATE.paused
        remote_server.STATE.paused = True
        try:
            self.assertEqual(self.postar("/api/collaboration/messages", {"text": "oi"}).status, 200)
        finally:
            remote_server.STATE.paused = pausada

    # ------------------------------------------------------------- permissões
    def test_sem_sessao_nao_se_le_nem_se_escreve(self) -> None:
        api = self.instalar(ApiFalsa())
        pedidos = (
            urllib.request.Request(self.base + "/api/collaboration"),
            urllib.request.Request(
                self.base + "/api/collaboration/messages", data=b'{"text":"oi"}',
                headers={"Content-Type": "application/json"},
            ),
        )
        for pedido in pedidos:
            with self.assertRaises(urllib.error.HTTPError) as erro:
                urllib.request.urlopen(pedido, timeout=5)
            self.assertEqual(erro.exception.code, 401)
        self.assertEqual(api.chamadas, [], "o backend não pode ser chamado sem sessão")


class BackendDoDiscoTests(unittest.TestCase):
    """O backend e do outro agente: congelado no exe, ele envelhece calado."""

    def test_o_pacote_nao_leva_copia_do_backend_da_colaboracao(self) -> None:
        """Empacotar o backend fez o chat da Dupla responder 404 com a rota pronta.

        A fonte no disco e a unica versao; o exe so precisa achar a raiz.
        """
        from pathlib import Path

        spec = Path(remote_server.__file__).resolve().parent / "Nebula.spec"
        texto = spec.read_text(encoding="utf-8")
        self.assertNotIn("'services.collaboration", texto)
        self.assertNotIn('"services.collaboration', texto)

    def test_a_raiz_do_projeto_entra_no_caminho_de_importacao(self) -> None:
        raiz = str(remote_server.raiz_colaboracao())
        remote_server._COLABORACAO["api"] = None
        remote_server._COLABORACAO["tentado_em"] = 0.0
        caminho = [p for p in sys.path if p != raiz]
        original, sys.path[:] = list(sys.path), caminho
        try:
            remote_server.colaboracao()
            self.assertIn(raiz, sys.path)
        finally:
            sys.path[:] = original
            remote_server._COLABORACAO["api"] = None
            remote_server._COLABORACAO["tentado_em"] = 0.0


class RodadasOrfasTests(unittest.TestCase):
    """Trava de conversa vale por processo; a Nebula caindo deixava ela presa."""

    def setUp(self) -> None:
        import tempfile
        from services.collaboration.api import CollaborationAPI

        self.raiz = tempfile.mkdtemp(prefix="orfa-")
        self.api = CollaborationAPI(self.raiz)
        self.ideia = self.api.store.create_idea("pedido de teste")["id"]

    def test_conversa_presa_e_liberada_no_arranque_seguinte(self) -> None:
        self.api.store.begin_chat(self.ideia, "e ai?")
        self.assertTrue(self.api.store.snapshot()["active_chat"])
        with self.assertRaises(Exception):
            # Enquanto presa, nenhuma conversa nova entra.
            self.api.store.begin_chat(self.ideia, "de novo")

        remote_server.liberar_rodadas_orfas(self.api)

        self.assertFalse(self.api.store.snapshot().get("active_chat"))
        self.api.store.begin_chat(self.ideia, "agora vai")

    def test_o_usuario_ve_o_motivo_no_lugar_de_um_silencio(self) -> None:
        self.api.store.begin_chat(self.ideia, "e ai?")
        remote_server.liberar_rodadas_orfas(self.api)
        avisos = [m for m in self.api.store.snapshot()["messages"]
                  if m["kind"] == "chat_error"]
        self.assertTrue(avisos)
        self.assertIn("reiniciou", avisos[-1]["data"]["text"])

    def test_sem_nada_preso_o_arranque_nao_mexe_em_nada(self) -> None:
        antes = len(self.api.store.snapshot()["messages"])
        remote_server.liberar_rodadas_orfas(self.api)
        self.assertEqual(len(self.api.store.snapshot()["messages"]), antes)


class PortaExclusivaTests(unittest.TestCase):
    """Dois servidores na mesma porta faziam o navegador cair no serviço errado."""

    def test_segundo_servidor_na_mesma_porta_falha_em_vez_de_dividir(self) -> None:
        primeiro = remote_server.ServidorExclusivo(("127.0.0.1", 0), remote_server.Handler)
        porta = primeiro.server_port
        try:
            with self.assertRaises(OSError):
                remote_server.ServidorExclusivo(("127.0.0.1", porta), remote_server.Handler)
        finally:
            primeiro.server_close()

    def test_a_porta_volta_a_abrir_depois_que_o_processo_fecha(self) -> None:
        primeiro = remote_server.ServidorExclusivo(("127.0.0.1", 0), remote_server.Handler)
        porta = primeiro.server_port
        primeiro.server_close()
        segundo = remote_server.ServidorExclusivo(("127.0.0.1", porta), remote_server.Handler)
        segundo.server_close()

    def test_a_ponte_do_gemini_nao_usa_mais_a_porta_do_painel(self) -> None:
        from ai_sprints import gemini_bridge_server

        self.assertNotEqual(gemini_bridge_server.BRIDGE_PORT, remote_server.PORTA)


if __name__ == "__main__":
    unittest.main()
