"""Terminal do hub: sessões de comando para o usuário e para as duas IAs.

O hub vive no notebook e é ele que vai hospedar o MCP, então o terminal precisa
aguentar comando longo rodando a fio: a saída fica num buffer com cursor, e
quem acompanha só pede o que ainda não viu.
"""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from notebook_power_server import power_server


class TerminalDoHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), power_server.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def tearDown(self) -> None:
        for sessao in power_server.TERMINAIS.listar():
            if sessao["executando"]:
                power_server.TERMINAIS.encerrar(sessao["id"])
        power_server.TERMINAIS.sessoes.clear()

    # ------------------------------------------------------------- ajudantes
    def pegar(self, caminho: str):
        with urllib.request.urlopen(self.base + caminho, timeout=10) as resposta:
            return resposta.status, json.loads(resposta.read())

    def postar(self, caminho: str, corpo: dict | None = None):
        pedido = urllib.request.Request(
            self.base + caminho,
            data=json.dumps(corpo or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(pedido, timeout=10) as resposta:
                return resposta.status, json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            return erro.code, json.loads(erro.read())

    def esperar_fim(self, ident: str, limite: float = 25.0) -> dict:
        """Espera o comando terminar em vez de dormir um tempo fixo."""
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            _, estado = self.pegar(f"/hub/terminal/{ident}?after=0")
            if not estado["executando"]:
                return estado
            time.sleep(0.15)
        self.fail(f"a sessão {ident} não terminou em {limite}s")

    # ------------------------------------------------------------- execução
    def test_comando_roda_e_a_saida_chega_com_o_codigo_de_saida(self) -> None:
        status, sessao = self.postar(
            "/hub/terminal", {"command": 'python -c "print(\'oi do hub\')"'}
        )
        self.assertEqual(status, 201)
        estado = self.esperar_fim(sessao["id"])
        self.assertEqual(estado["codigo"], 0)
        self.assertIn("oi do hub", "\n".join(estado["lines"]))

    def test_codigo_de_erro_chega_em_vez_de_virar_sucesso(self) -> None:
        _, sessao = self.postar("/hub/terminal", {"command": "python -c \"raise SystemExit(3)\""})
        self.assertEqual(self.esperar_fim(sessao["id"])["codigo"], 3)

    def test_saida_de_erro_e_capturada_junto(self) -> None:
        _, sessao = self.postar(
            "/hub/terminal",
            {"command": "python -c \"import sys; sys.stderr.write('falhou feio\\n')\""},
        )
        self.assertIn("falhou feio", "\n".join(self.esperar_fim(sessao["id"])["lines"]))

    def test_cursor_entrega_so_o_que_ainda_nao_foi_visto(self) -> None:
        _, sessao = self.postar(
            "/hub/terminal",
            {"command": 'python -c "[print(i) for i in range(6)]"'},
        )
        completo = self.esperar_fim(sessao["id"])
        self.assertGreaterEqual(completo["cursor"], 7)
        _, adiante = self.pegar(f"/hub/terminal/{sessao['id']}?after={completo['cursor']}")
        self.assertEqual(adiante["lines"], [], "nada novo depois do cursor final")
        _, parcial = self.pegar(f"/hub/terminal/{sessao['id']}?after=3")
        self.assertEqual(len(parcial["lines"]), completo["cursor"] - 3)

    def test_comando_longo_pode_ser_encerrado_no_meio(self) -> None:
        _, sessao = self.postar(
            "/hub/terminal",
            {"command": 'python -c "import time; time.sleep(600)"'},
        )
        self.assertTrue(sessao["executando"])
        status, parado = self.postar(f"/hub/terminal/{sessao['id']}/stop")
        self.assertEqual(status, 200)
        self.assertFalse(parado["executando"])
        self.assertIsNotNone(parado["codigo"])

    def test_stdin_fechado_para_o_comando_nao_travar_esperando_digitacao(self) -> None:
        """Sem isto, um comando que pede confirmação seguraria a sessão para sempre."""
        _, sessao = self.postar("/hub/terminal", {"command": "python -c \"input()\""})
        self.esperar_fim(sessao["id"], limite=15)

    # ------------------------------------------------------------- listagem
    def test_sessoes_aparecem_na_lista_com_quem_pediu(self) -> None:
        self.postar("/hub/terminal", {"command": "python -c \"pass\"", "author": "opus"})
        self.postar("/hub/terminal", {"command": "python -c \"pass\"", "author": "codex"})
        _, lista = self.pegar("/hub/terminal")
        autores = {s["autor"] for s in lista["sessions"]}
        self.assertEqual(autores, {"opus", "codex"})

    # ------------------------------------------------------------- recusas
    def test_comando_vazio_e_recusado(self) -> None:
        status, erro = self.postar("/hub/terminal", {"command": "   "})
        self.assertEqual(status, 400)
        self.assertIn("comando", erro["error"].casefold())

    def test_pasta_inexistente_e_recusada_antes_de_iniciar(self) -> None:
        status, erro = self.postar(
            "/hub/terminal", {"command": "python -V", "cwd": "Z:/nao/existe/mesmo"}
        )
        self.assertEqual(status, 400)
        self.assertIn("inexistente", erro["error"].casefold())

    def test_sessao_desconhecida_responde_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as erro:
            self.pegar("/hub/terminal/naoexiste")
        self.assertEqual(erro.exception.code, 404)

    def test_limite_de_comandos_simultaneos(self) -> None:
        abertas = []
        for _ in range(power_server.Terminais.MAXIMO_VIVOS):
            status, sessao = self.postar(
                "/hub/terminal", {"command": 'python -c "import time; time.sleep(300)"'}
            )
            self.assertEqual(status, 201)
            abertas.append(sessao["id"])
        status, erro = self.postar("/hub/terminal", {"command": "python -V"})
        self.assertEqual(status, 400)
        self.assertIn("execução", erro["error"])
        self.postar(f"/hub/terminal/{abertas[0]}/stop")
        self.assertEqual(self.postar("/hub/terminal", {"command": "python -V"})[0], 201)

    def test_terminal_nao_polui_as_metricas_que_o_console_mostra(self) -> None:
        """O console consulta a saída sem parar; contar isso encheria o próprio log."""
        antes = power_server.MONITOR.snapshot()["total"]
        self.pegar("/hub/terminal")
        self.assertEqual(power_server.MONITOR.snapshot()["total"], antes)


if __name__ == "__main__":
    unittest.main()
