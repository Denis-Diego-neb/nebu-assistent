import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch, Mock

import remote_server
from abajur_tuya import ConfiguracaoTuya
from main import Nebula


class SaidaFalsa:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ModoRPMFalso:
    def __init__(self, saida_abajur=None) -> None:
        self.ativo = False
        self.erro = None

    def iniciar(self) -> None:
        self.ativo = True

    def parar(self) -> None:
        self.ativo = False

    def status(self) -> dict[str, object]:
        return {
            "ativo": self.ativo,
            "recebendo": True,
            "telemetria_valida": True,
            "rpm": 6789,
            "percentual": 77.5,
            "faixa": "laranja",
            "abajur": "desativado",
            "erro": None,
            "erro_abajur": None,
        }


class ControleDiretoTests(unittest.TestCase):
    def test_cor_do_teclado_boost_e_validada_e_persistida(self) -> None:
        saida = SaidaFalsa()
        with tempfile.TemporaryDirectory() as pasta, patch.dict(os.environ, {"LOCALAPPDATA": pasta}):
            nebula = Nebula(saida, abrir_navegador=False)
            resposta = nebula.executar_controle("boost.keyboard_color", "#FF1493")
            self.assertEqual(resposta["state"]["boost_keyboard_color"], "#FF1493")
            recarregada = Nebula(saida, abrir_navegador=False)
            self.assertEqual(recarregada._cor_teclado_boost, (255, 20, 147))
            with self.assertRaises(ValueError):
                recarregada.executar_controle("boost.keyboard_color", "preto")

    def test_chaves_de_dispositivo_sao_salvas_por_modo(self) -> None:
        saida = SaidaFalsa()
        with tempfile.TemporaryDirectory() as pasta, patch.dict(os.environ, {"LOCALAPPDATA": pasta}):
            nebula = Nebula(saida, abrir_navegador=False)
            resposta = nebula.executar_controle(
                "mode.target",
                {"mode": "boost", "device": "keyboard", "enabled": False},
            )
            self.assertTrue(resposta["ok"])
            self.assertFalse(nebula._alvos_modo["boost"]["keyboard"])
            recarregada = Nebula(saida, abrir_navegador=False)
            self.assertFalse(recarregada._alvos_modo["boost"]["keyboard"])

    def test_modo_mudo_nao_pausa_comandos(self) -> None:
        saida = SaidaFalsa()
        nebula = Nebula(saida, abrir_navegador=False)
        nebula.definir_modo_mudo(True)
        self.assertTrue(nebula.executar("que horas sao"))
        self.assertEqual(saida.mensagens, [])
        self.assertTrue(nebula.estado_controle()["muted"])

    def test_nebula_inicia_no_mudo(self) -> None:
        nebula = Nebula(SaidaFalsa(), abrir_navegador=False, iniciar_muda=True)
        self.assertTrue(nebula.modo_mudo)

    def test_botao_rpm_e_exclusivo_e_silencioso(self) -> None:
        saida = SaidaFalsa()
        nebula = Nebula(saida, abrir_navegador=False)
        nebula._alvos_modo['rpm'].update(lamp=True, controller=True, mobile=True)
        with (
            patch("main.ModoRPM", ModoRPMFalso),
            patch.object(ConfiguracaoTuya, "carregar", return_value=None),
        ):
            resposta = nebula.executar_controle("mode", "rpm")
            self.assertTrue(resposta["ok"])
            self.assertEqual(resposta["state"]["mode"], "rpm")
            self.assertEqual(resposta["state"]["rpm"], 6789)
            self.assertEqual(saida.mensagens, [])
            desligado = nebula.executar_controle("mode", "manual")
            self.assertEqual(desligado["state"]["mode"], "manual")

    def test_botao_de_cor_nao_tenta_converter_nome_em_brilho(self) -> None:
        saida = SaidaFalsa()
        nebula = Nebula(saida, abrir_navegador=False)
        lamp = Mock()
        with patch.object(nebula, "_obter_controle_abajur", return_value=lamp):
            resposta = nebula.executar_controle("lamp.color", "verde")
        lamp.cor.assert_called_once_with("verde")
        lamp.brilho.assert_not_called()
        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["state"]["lamp_selection"], "verde")


class ApiControleTests(unittest.TestCase):
    def test_api_expoe_estado_e_executa_botao(self) -> None:
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
        thread = threading.Thread(target=servidor.serve_forever, daemon=True)
        token = "teste-controle"
        anterior_acao = remote_server.STATE.control_callback
        anterior_estado = remote_server.STATE.control_status_callback
        recebido: list[tuple[str, object]] = []
        estado = {"ready": True, "muted": False, "mode": "manual", "rpm": None}

        def acao(nome: str, valor: object) -> dict[str, object]:
            recebido.append((nome, valor))
            estado["mode"] = str(valor)
            return {"ok": True, "message": "Aplicado", "state": dict(estado)}

        remote_server.STATE.control_callback = acao
        remote_server.STATE.control_status_callback = lambda: dict(estado)
        remote_server.STATE.sessions.add(token)
        thread.start()
        base = f"http://127.0.0.1:{servidor.server_port}"

        def chamar(caminho: str, dados: dict[str, object] | None = None):
            corpo = None if dados is None else json.dumps(dados).encode()
            pedido = urllib.request.Request(
                base + caminho,
                data=corpo,
                method="GET" if dados is None else "POST",
                headers={"X-Nebula-Token": token, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(pedido, timeout=5) as resposta:
                return json.loads(resposta.read().decode())

        try:
            self.assertEqual(chamar("/api/control")["state"]["mode"], "manual")
            resposta = chamar("/api/control", {"action": "mode", "value": "rpm"})
            self.assertEqual(resposta["state"]["mode"], "rpm")
            self.assertEqual(recebido, [("mode", "rpm")])
        finally:
            servidor.shutdown()
            servidor.server_close()
            remote_server.STATE.sessions.discard(token)
            remote_server.STATE.control_callback = anterior_acao
            remote_server.STATE.control_status_callback = anterior_estado


if __name__ == "__main__":
    unittest.main()
