"""Front espacial compartilhado: assets, rota /espaco e console do hub."""

import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path

import front_assets


class FrontAssetsTests(unittest.TestCase):
    def test_pasta_do_front_tem_os_arquivos_do_espaco_e_do_hub(self) -> None:
        pasta = front_assets.front_dir()
        self.assertIsNotNone(pasta, "nebula_front não foi encontrada")
        for nome in (
            "index.html", "hub.html", "style.css", "atmosphere.css", "panel.css",
            "hub.css", "app.js", "nebula-app.js", "hub.js", "fullscreen.js",
            "nebula-scene.js",
        ):
            self.assertTrue((pasta / nome).is_file(), nome)

    def test_carregar_devolve_conteudo_e_tipo(self) -> None:
        recurso = front_assets.carregar("index.html")
        self.assertIsNotNone(recurso)
        corpo, tipo = recurso
        self.assertIn(b"<!doctype html>", corpo[:40].lower())
        self.assertEqual(tipo, "text/html; charset=utf-8")
        self.assertEqual(front_assets.carregar("app.js")[1],
                         "application/javascript; charset=utf-8")

    def test_carregar_recusa_travessia_e_extensoes_fora_da_lista(self) -> None:
        for nome in ("../remote_server.py", "..", "sub/dir.css", "/etc/passwd",
                     "C:\\Windows\\win.ini", "", "index.html.py", "segredo.env"):
            self.assertIsNone(front_assets.carregar(nome), nome)

    def test_front_sem_conexao_externa(self) -> None:
        """O EXE e o APK precisam funcionar sem internet: nada de CDN."""
        pasta = front_assets.front_dir()
        for arquivo in pasta.glob("*"):
            texto = arquivo.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("fonts.googleapis.com", texto, arquivo.name)
            self.assertNotIn("cdn.jsdelivr.net", texto, arquivo.name)


class MarcacaoDoFrontTests(unittest.TestCase):
    """Todo id e todo seletor usado pelo JS precisa existir no HTML.

    Um id trocado só apareceria como exceção no console do navegador, com a
    seção em branco; aqui isso vira falha de teste.
    """

    def pares(self):
        pasta = front_assets.front_dir()
        return (
            (pasta / "nebula-app.js", pasta / "index.html"),
            (pasta / "hub.js", pasta / "hub.html"),
        )

    def test_ids_pedidos_pelo_js_existem_no_html(self) -> None:
        for script, pagina in self.pares():
            html = pagina.read_text(encoding="utf-8")
            existentes = set(re.findall(r'id="([^"]+)"', html))
            pedidos = set(re.findall(r"\$\('([^']+)'\)", script.read_text(encoding="utf-8")))
            self.assertTrue(pedidos, script.name)
            self.assertEqual(pedidos - existentes, set(), script.name)

    def test_seletores_de_dados_existem_no_html(self) -> None:
        for script, pagina in self.pares():
            html = pagina.read_text(encoding="utf-8")
            codigo = script.read_text(encoding="utf-8")
            for atributo in set(re.findall(r"querySelectorAll\('\[([a-z-]+)\]'\)", codigo)):
                self.assertIn(atributo, html, f"{atributo} ausente em {pagina.name}")

    def test_scripts_e_estilos_citados_pelo_html_existem(self) -> None:
        pasta = front_assets.front_dir()
        for pagina in ("index.html", "hub.html"):
            html = (pasta / pagina).read_text(encoding="utf-8")
            for arquivo in re.findall(r'(?:src|href)="([^":/]+\.(?:js|css))"', html):
                self.assertTrue((pasta / arquivo).is_file(), f"{arquivo} de {pagina}")


class EspacoRotaTests(unittest.TestCase):
    """A rota /espaco só entrega o front a quem tem sessão ou bilhete local."""

    @classmethod
    def setUpClass(cls) -> None:
        import remote_server

        cls.remote_server = remote_server
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def abrir(self, caminho: str, com_cookies: CookieJar | None = None):
        # Um CookieJar vazio é falsy: precisa ser comparado com None.
        pote = CookieJar() if com_cookies is None else com_cookies
        abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(pote))
        return abridor.open(self.base + caminho, timeout=5)

    def test_sem_sessao_o_espaco_manda_para_o_login(self) -> None:
        resposta = self.abrir("/espaco/")
        self.assertEqual(resposta.geturl(), self.base + "/")

    def test_bilhete_local_cria_sessao_e_entrega_o_front(self) -> None:
        pote = CookieJar()
        ticket = self.remote_server.criar_ticket_espaco()
        resposta = self.abrir(f"/espaco/?ticket={ticket}", pote)
        self.assertEqual(resposta.status, 200)
        self.assertEqual(resposta.geturl(), self.base + "/espaco/")
        self.assertIn(b"nebula-app.js", resposta.read())
        self.assertIn("nebula_session", [cookie.name for cookie in pote])

        # Com a sessão no pote, os assets do front vêm normalmente.
        for nome in ("style.css", "panel.css", "nebula-app.js"):
            self.assertEqual(self.abrir("/espaco/" + nome, pote).status, 200)

    def test_bilhete_vale_uma_vez_so(self) -> None:
        ticket = self.remote_server.criar_ticket_espaco()
        self.abrir(f"/espaco/?ticket={ticket}", CookieJar())
        segunda = self.abrir(f"/espaco/?ticket={ticket}", CookieJar())
        self.assertEqual(segunda.geturl(), self.base + "/")

    def test_bilhete_expirado_nao_abre_sessao(self) -> None:
        ticket = self.remote_server.criar_ticket_espaco()
        with self.remote_server.STATE.lock:
            self.remote_server.STATE.espaco_tickets[ticket] = 0.0
        self.assertIsNone(self.remote_server.consumir_ticket_espaco(ticket))

    def test_travessia_de_caminho_nao_sai_da_pasta_do_front(self) -> None:
        pote = CookieJar()
        self.abrir(f"/espaco/?ticket={self.remote_server.criar_ticket_espaco()}", pote)
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.abrir("/espaco/../remote_server.py", pote)
        self.assertEqual(erro.exception.code, 404)


class HubConsoleTests(unittest.TestCase):
    """O console do hub serve o log ao vivo sem poluir as métricas do servidor."""

    @classmethod
    def setUpClass(cls) -> None:
        from notebook_power_server import power_server

        cls.power_server = power_server
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), power_server.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def pegar(self, caminho: str):
        return urllib.request.urlopen(self.base + caminho, timeout=5)

    def test_console_entrega_pagina_e_assets(self) -> None:
        pagina = self.pegar("/hub/")
        self.assertEqual(pagina.status, 200)
        self.assertIn(b"NEBULA HOME HUB", pagina.read())
        for nome, tipo in (("hub.css", "text/css; charset=utf-8"),
                           ("hub.js", "application/javascript; charset=utf-8")):
            asset = self.pegar("/hub/" + nome)
            self.assertEqual(asset.headers.get("Content-Type"), tipo)

    def test_estado_traz_metricas_e_versao(self) -> None:
        estado = json.loads(self.pegar("/hub/state").read())
        self.assertEqual(estado["port"], self.server.server_port)
        self.assertIn("uptime", estado)
        self.assertIn("total", estado["metrics"])

    def test_console_nao_conta_como_requisicao_do_hub(self) -> None:
        antes = self.power_server.MONITOR.snapshot()["total"]
        self.pegar("/hub/state")
        self.pegar("/hub/events?after=0")
        self.assertEqual(self.power_server.MONITOR.snapshot()["total"], antes)

    def test_travessia_no_console_nao_sai_da_pasta(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pegar("/hub/../power_server.py")
        self.assertEqual(erro.exception.code, 404)


class HistoricoDoMonitorTests(unittest.TestCase):
    def monitor(self, pasta: str):
        return self.power_server.ServerMonitor(Path(pasta) / "server.log")

    def setUp(self) -> None:
        from notebook_power_server import power_server

        self.power_server = power_server

    def test_cursor_avanca_e_nao_repete_linhas(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            monitor = self.monitor(pasta)
            monitor.record_event("primeira")
            monitor.record_event("segunda")
            inicio = monitor.history_since(0)
            self.assertEqual(len(inicio["lines"]), 2)
            self.assertEqual(inicio["cursor"], 2)
            self.assertFalse(inicio["reset"])

            self.assertEqual(monitor.history_since(inicio["cursor"])["lines"], [])
            monitor.record_event("terceira")
            depois = monitor.history_since(inicio["cursor"])
            self.assertEqual(len(depois["lines"]), 1)
            self.assertIn("terceira", depois["lines"][0])
            self.assertEqual(depois["cursor"], 3)

    def test_pedido_atrasado_pede_reinicio_da_visualizacao(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            monitor = self.monitor(pasta)
            monitor.recent.clear()
            for numero in range(monitor.recent.maxlen + 20):
                monitor.record_event(f"linha {numero}")
            atrasado = monitor.history_since(1)
            self.assertTrue(atrasado["reset"])
            self.assertEqual(len(atrasado["lines"]), monitor.recent.maxlen)

    def test_classificacao_das_linhas_segue_o_status(self) -> None:
        classificar = self.power_server._classificar_linha
        self.assertEqual(classificar("10.0.0.2  GET  /health  → 200"), "ok")
        self.assertEqual(classificar("10.0.0.2  POST /wake    → 401"), "bloqueada")
        self.assertEqual(classificar("10.0.0.2  POST /control → 500"), "falha")
        self.assertEqual(classificar("Servidor iniciado."), "nota")


if __name__ == "__main__":
    unittest.main()
