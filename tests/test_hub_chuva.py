"""Rotas do modo chuva no hub: a chave da sessão abre só a página do vídeo."""

import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from notebook_power_server import power_server
from notebook_power_server.coordenador_chuva import CoordenadorChuva


class HubChuvaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), power_server.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.chuva = CoordenadorChuva(
            caminho=Path(pasta.name) / "modo_chuva.json", tela=Mock(), avisar_pc=Mock(),
            resolver_video=Mock(return_value=None), em_segundo_plano=lambda tarefa: tarefa(),
        )
        anterior = power_server.BRAIN.chuva
        power_server.BRAIN.chuva = self.chuva
        self.addCleanup(setattr, power_server.BRAIN, "chuva", anterior)
        # Visto de outro aparelho da rede, sem o token do hub.
        fora = patch.object(power_server.Handler, "hub_autorizado", return_value=False)
        fora.start()
        self.addCleanup(fora.stop)

    def pegar(self, caminho: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(self.base + caminho, timeout=10) as resposta:
                return resposta.status, resposta.read()
        except urllib.error.HTTPError as erro:
            return erro.code, erro.read()

    def test_chave_da_sessao_abre_so_a_pagina_do_video(self) -> None:
        self.chuva.iniciar("https://youtu.be/abcdefghijk", "teste")
        chave = self.chuva._sessao["chave"]
        status, corpo = self.pegar(f"/hub/chuva.html?k={chave}")
        self.assertEqual(status, 200)
        self.assertIn(b"YT.Player", corpo)
        status, corpo = self.pegar(f"/hub/chuva/estado?k={chave}")
        self.assertEqual(status, 200)
        estado = json.loads(corpo)
        self.assertEqual((estado["ativo"], estado["video_id"]), (True, "abcdefghijk"))
        self.assertNotIn("trovoes", estado)
        for caminho in ("/hub/chuva.html", "/hub/chuva.html?k=errada", f"/hub/state?k={chave}",
                        f"/hub/hub.html?k={chave}"):
            with self.subTest(caminho=caminho):
                self.assertEqual(self.pegar(caminho)[0], 401)
        self.chuva.parar("teste")
        self.assertEqual(self.pegar(f"/hub/chuva.html?k={chave}")[0], 401)

    def test_celular_le_o_estado_pela_rota_direta_com_token(self) -> None:
        self.chuva.iniciar("abcdefghijk", "teste")
        self.assertEqual(self.pegar("/chuva")[0], 401)
        pedido = urllib.request.Request(self.base + "/chuva", headers={"X-Nebula-Power-Token": power_server.POWER_TOKEN})
        with urllib.request.urlopen(pedido, timeout=10) as resposta:
            estado = json.loads(resposta.read())
        self.assertTrue(estado["ativo"])
        self.assertIn("trovoes", estado)

    def test_acoes_do_celular_iniciam_e_param_o_modo(self) -> None:
        with patch.object(power_server.BRAIN, "_pc", side_effect=RuntimeError("PC desligado")):
            resposta = power_server.BRAIN.action(
                "chuva.iniciar", {"video": "abcdefghijk", "origem": "celular"})
            self.assertTrue(resposta["chuva"]["ativo"])
            self.assertTrue(power_server.BRAIN.status()["chuva"]["ativo"])
            resposta = power_server.BRAIN.action("chuva.parar", {"origem": "celular"})
        self.assertFalse(resposta["chuva"]["ativo"])
        self.assertEqual(resposta["chuva"]["motivo"], "celular")


if __name__ == "__main__":
    unittest.main()
