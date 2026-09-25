"""Rotas /api/collaboration: a ponte entre o painel e o backend da colaboração.

O backend fica em ``services/collaboration/`` e é mantido pelo outro agente.
Aqui só se testa o lado que é meu: a autenticação na frente, o que acontece
enquanto a API do Codex não existe, e o repasse fiel de método, caminho, corpo,
status e resposta. Nenhuma regra de negócio é reimplementada deste lado.
"""

import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
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
        remote_server.esquecer_colaboracao()

    def instalar(self, api):
        """Troca a API vista pelas rotas e zera o cache do adaptador.

        Com ``api=None`` o backend real do Codex é escondido: uma entrada
        ``None`` em ``sys.modules`` faz o ``import`` levantar ImportError, que é
        exatamente o que o adaptador vê antes de a pasta existir.
        """
        sys.modules["services.collaboration.api"] = modulo_com(api) if api else None
        remote_server.esquecer_colaboracao()
        remote_server._COLABORACAO["api"] = api
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
            # Orcamento sempre no maximo: decisao do Denis, nao repasse literal.
            ("POST", "/api/collaboration/ideas", {"text": "ideia", "token_budget": remote_server.ORCAMENTO_MAXIMO}),
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

    def test_o_pacote_exclui_o_backend_e_a_cola_da_dupla(self) -> None:
        """Empacotar o backend fez o chat da Dupla responder 404 com a rota pronta.

        Tirar do hiddenimports nao bastou: a cola da Dupla importa o backend no
        topo, o PyInstaller seguiu esse import e congelou tudo de novo. So o
        excludes impede, e e ele que se confere aqui.
        """
        import ast
        from pathlib import Path

        spec = Path(remote_server.__file__).resolve().parent / "Nebula.spec"
        arvore = ast.parse(spec.read_text(encoding="utf-8"))
        excluidos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call) and getattr(no.func, "id", "") == "Analysis":
                for argumento in no.keywords:
                    if argumento.arg == "excludes":
                        excluidos = {e.value for e in argumento.value.elts}
        self.assertTrue({"services.collaboration", "colaboracao_ferramentas",
                         "memoria_dupla"} <= excluidos, excluidos)

    def test_a_raiz_do_projeto_entra_no_caminho_de_importacao(self) -> None:
        raiz = str(remote_server.raiz_colaboracao())
        caminho = [p for p in sys.path if p != raiz]
        original, sys.path[:] = list(sys.path), caminho
        # Projeto temporario: no ativo da Nebula a Dupla abriria o store real e
        # encerraria a rodada em andamento (ver RodadasOrfasTests).
        with tempfile.TemporaryDirectory() as projeto, \
                mock.patch.object(remote_server.STATE, "selected_project", projeto):
            remote_server.esquecer_colaboracao()
            try:
                remote_server.colaboracao()
                self.assertIn(raiz, sys.path)
            finally:
                sys.path[:] = original
                remote_server.esquecer_colaboracao()


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

    def dono(self, pid, criado) -> None:
        arquivo = Path(self.api.store.directory) / remote_server.ARQUIVO_DONO
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps({"pid": pid, "criado": criado}), encoding="utf-8")

    def test_rodada_de_uma_nebula_viva_nao_e_orfa(self) -> None:
        """A suite de testes abrindo a Dupla matava o CLI da Nebula (codigo 15)."""
        import psutil

        eu = psutil.Process()
        self.dono(eu.pid, eu.create_time())
        self.api.store.begin_chat(self.ideia, "rodada em andamento")
        remote_server.liberar_rodadas_orfas(self.api)
        self.assertTrue(self.api.store.snapshot().get("active_chat"))
        self.assertFalse([m for m in self.api.store.snapshot()["messages"]
                          if m["kind"] == "chat_error"])

    def test_dono_morto_libera_e_quem_limpou_vira_dono(self) -> None:
        import psutil

        eu = psutil.Process()
        # Mesmo PID com outra hora de criacao: o PID foi reaproveitado.
        self.dono(eu.pid, eu.create_time() - 3600)
        self.api.store.begin_chat(self.ideia, "presa")
        remote_server.liberar_rodadas_orfas(self.api)
        self.assertFalse(self.api.store.snapshot().get("active_chat"))
        registro = json.loads((Path(self.api.store.directory)
                               / remote_server.ARQUIVO_DONO).read_text(encoding="utf-8"))
        self.assertEqual(registro["pid"], eu.pid)
        self.assertAlmostEqual(registro["criado"], eu.create_time(), places=2)

    def test_quem_nao_serve_o_painel_nunca_limpa_rodada(self) -> None:
        """Teste, autopilot ou script abrindo a Dupla nao encerra conversa nenhuma."""
        self.api.store.begin_chat(self.ideia, "rodada da Nebula")
        with mock.patch.object(remote_server.STATE, "selected_project", self.raiz), \
                mock.patch.object(remote_server, "_SERVINDO_PAINEL", False):
            remote_server.esquecer_colaboracao()
            try:
                self.assertIsNotNone(remote_server.colaboracao())
            finally:
                remote_server.esquecer_colaboracao()
        self.assertTrue(self.api.store.snapshot().get("active_chat"))


class ConversaDoCelularTests(unittest.TestCase):
    """O chat nativo pelo 4G so pode receber o que e novo.

    O snapshot inteiro tinha 270 KB; buscado a cada 3 s daria mais de 300 MB
    por hora de chat aberto no celular.
    """

    def estado(self, eventos, ideias=(("a", "pedido"),), ativo=None):
        return {"ideas": [{"id": i, "text": t} for i, t in ideias],
                "active_chat": ativo, "messages": eventos}

    def evento(self, seq, tipo, texto, ideia="a", autor="user", **extra):
        return {"seq": seq, "idea": ideia, "kind": tipo, "actor": autor,
                "at": "2026-09-24T21:00:00+00:00", "data": {"text": texto, **extra}}

    def test_primeira_consulta_traz_a_conversa_do_pedido_atual(self) -> None:
        c = remote_server.conversa_dupla(self.estado([
            self.evento(1, "user_message", "oi"),
            self.evento(2, "chat_reply", "ola", autor="opus", model="claude-opus-5-5"),
        ]), 0, "")
        self.assertTrue(c["recomecar"])
        self.assertEqual([m["texto"] for m in c["mensagens"]], ["oi", "ola"])
        self.assertEqual(c["mensagens"][1]["modelo"], "claude-opus-5-5")

    def test_depois_do_cursor_so_vem_o_que_e_novo(self) -> None:
        estado = self.estado([self.evento(1, "user_message", "oi"),
                              self.evento(2, "chat_reply", "ola", autor="codex")])
        self.assertEqual(remote_server.conversa_dupla(estado, 2, "a")["mensagens"], [])
        self.assertEqual([m["seq"] for m in remote_server.conversa_dupla(estado, 1, "a")["mensagens"]], [2])

    def test_sem_novidade_a_resposta_e_minima(self) -> None:
        estado = self.estado([self.evento(i, "chat_reply", "x" * 5000, autor="opus") for i in range(1, 60)])
        vazio = json.dumps(remote_server.conversa_dupla(estado, 59, "a"))
        self.assertLess(len(vazio), 300)

    def test_contabilidade_e_bastidores_ficam_de_fora(self) -> None:
        c = remote_server.conversa_dupla(self.estado([
            self.evento(1, "tokens_used", "x", autor="opus"),
            self.evento(2, "note", "recado interno", autor="opus"),
            self.evento(3, "task_claimed", "x", autor="opus"),
            self.evento(4, "chat_error", "codex sem credito", autor="system"),
        ]), 0, "")
        self.assertEqual([m["tipo"] for m in c["mensagens"]], ["chat_error"])

    def test_confirmacao_formal_aparece_no_chat(self) -> None:
        c = remote_server.conversa_dupla(self.estado([
            self.evento(1, "confirmation", "assumo o backend", autor="codex")]), 0, "")
        self.assertEqual(c["mensagens"][0]["tipo"], "confirmation")

    def test_mensagens_de_outro_pedido_nao_se_misturam(self) -> None:
        c = remote_server.conversa_dupla(self.estado(
            [self.evento(1, "user_message", "antigo", ideia="velho"),
             self.evento(2, "user_message", "atual", ideia="a")],
            ideias=(("velho", "p1"), ("a", "p2"))), 0, "")
        self.assertEqual([m["texto"] for m in c["mensagens"]], ["atual"])

    def test_pedido_novo_manda_o_celular_recomecar_do_zero(self) -> None:
        estado = self.estado([self.evento(1, "user_message", "na nova", ideia="b")],
                             ideias=(("a", "p1"), ("b", "p2")))
        c = remote_server.conversa_dupla(estado, 40, "a")
        self.assertTrue(c["recomecar"])
        self.assertEqual([m["texto"] for m in c["mensagens"]], ["na nova"])

    def test_avisa_quando_as_duas_estao_respondendo(self) -> None:
        self.assertTrue(remote_server.conversa_dupla(self.estado([], ativo={"id": "x"}), 0, "a")["respondendo"])

    def test_rota_exige_autenticacao(self) -> None:
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as erro:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{servidor.server_port}/api/dupla/conversa?depois=0", timeout=5)
            self.assertEqual(erro.exception.code, 401)
        finally:
            servidor.shutdown()
            servidor.server_close()


class ChatLimpoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.antes = list(remote_server.STATE.conversation)
        remote_server.STATE.conversation[:] = []

    def tearDown(self) -> None:
        remote_server.STATE.conversation[:] = self.antes

    def test_aviso_repetido_do_sistema_entra_uma_vez(self) -> None:
        for _ in range(3):
            remote_server.add_conversation_message("Sistema", "Nebula pronta. Aguardando um nome de ativação.")
        self.assertEqual(len(remote_server.get_conversation()), 1)

    def test_mensagem_repetida_de_gente_continua_entrando(self) -> None:
        remote_server.add_conversation_message("Você", "oi")
        remote_server.add_conversation_message("Você", "oi")
        self.assertEqual(len(remote_server.get_conversation()), 2)


class TokenDaPonteTests(unittest.TestCase):
    """O Denis copia o token da ponte do Gemini pelas configuracoes do PC e do celular."""

    def test_le_do_ambiente_quando_existe(self) -> None:
        from unittest import mock
        with mock.patch.dict(remote_server.os.environ, {"NEBULA_GEMINI_BRIDGE_TOKEN": " abc123 "}):
            self.assertEqual(remote_server.token_ponte_gemini(), "abc123")

    def test_sem_ambiente_cai_no_registro_do_usuario(self) -> None:
        """Processo aberto antes do token ser gravado nao tem a variavel no ambiente."""
        from unittest import mock
        if remote_server.os.name != "nt":
            self.skipTest("registro so existe no Windows")
        import winreg
        falso = mock.MagicMock()
        falso.__enter__ = mock.Mock(return_value=falso)
        falso.__exit__ = mock.Mock(return_value=False)
        ambiente = {k: v for k, v in remote_server.os.environ.items() if k != "NEBULA_GEMINI_BRIDGE_TOKEN"}
        with mock.patch.dict(remote_server.os.environ, ambiente, clear=True),                 mock.patch.object(winreg, "OpenKey", return_value=falso),                 mock.patch.object(winreg, "QueryValueEx", return_value=("do-registro", 1)):
            self.assertEqual(remote_server.token_ponte_gemini(), "do-registro")

    def rota(self, cabecalhos):
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            pedido = urllib.request.Request(
                f"http://127.0.0.1:{servidor.server_port}/api/gemini/ponte", headers=cabecalhos)
            with urllib.request.urlopen(pedido, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None
        finally:
            servidor.shutdown()
            servidor.server_close()

    def test_rota_sem_autenticacao_nao_entrega_o_token(self) -> None:
        self.assertEqual(self.rota({})[0], 401)

    def test_rota_autenticada_entrega_para_copiar(self) -> None:
        from unittest import mock
        with mock.patch.object(remote_server, "token_ponte_gemini", return_value="tok-xyz"):
            status, corpo = self.rota({"X-Nebula-Power-Token": remote_server.POWER_TOKEN})
        self.assertEqual(status, 200)
        self.assertEqual(corpo["token"], "tok-xyz")
        self.assertTrue(corpo["definido"])


class ProjetoDaDuplaTests(unittest.TestCase):
    """A Dupla trabalha no projeto ativo da Nebula, com orcamento maximo."""

    def setUp(self) -> None:
        import tempfile
        self.antes = remote_server.STATE.selected_project
        self.a = tempfile.mkdtemp(prefix="proj-a-")
        self.b = tempfile.mkdtemp(prefix="proj-b-")
        remote_server.esquecer_colaboracao()

    def tearDown(self) -> None:
        remote_server.STATE.selected_project = self.antes
        remote_server.esquecer_colaboracao()

    def test_cada_projeto_tem_o_proprio_diario(self) -> None:
        remote_server.STATE.selected_project = self.a
        api_a = remote_server.colaboracao()
        remote_server.STATE.selected_project = self.b
        api_b = remote_server.colaboracao()
        self.assertEqual(str(api_a.store.root), str(Path(self.a).resolve()))
        self.assertEqual(str(api_b.store.root), str(Path(self.b).resolve()))

    def test_voltar_ao_projeto_reaproveita_a_mesma_instancia(self) -> None:
        """Uma rodada correndo no projeto A continua achavel ao voltar para ele."""
        remote_server.STATE.selected_project = self.a
        primeira = remote_server.colaboracao()
        remote_server.STATE.selected_project = self.b
        remote_server.colaboracao()
        remote_server.STATE.selected_project = self.a
        self.assertIs(remote_server.colaboracao(), primeira)

    def test_pedido_novo_pelo_chat_nasce_com_orcamento_maximo(self) -> None:
        remote_server.STATE.selected_project = self.a
        api = remote_server.colaboracao()
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            pedido = urllib.request.Request(
                f"http://127.0.0.1:{servidor.server_port}/api/collaboration/ideas",
                data=json.dumps({"text": "pedido", "token_budget": 60000}).encode(),
                headers={"Content-Type": "application/json", "X-Nebula-Power-Token": remote_server.POWER_TOKEN})
            urllib.request.urlopen(pedido, timeout=5).read()
        finally:
            servidor.shutdown(); servidor.server_close()
        limites = {b["limit"] for orc in api.store.snapshot()["budgets"].values() for b in orc.values()}
        self.assertEqual(limites, {remote_server.ORCAMENTO_MAXIMO})


class DescobertaDeProjetosTests(unittest.TestCase):
    def test_lista_marca_git_e_nunca_inclui_o_windows(self) -> None:
        projetos = remote_server.discover_projects()
        self.assertTrue(all("git" in p and "path" in p and "name" in p for p in projetos))
        self.assertFalse(any(p["path"].lower().startswith("c:\\windows") for p in projetos))

    def test_usados_recentemente_vem_primeiro(self) -> None:
        datas = [p["used_at"] for p in remote_server.discover_projects() if p["used_at"]]
        self.assertEqual(datas, sorted(datas, reverse=True))


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
