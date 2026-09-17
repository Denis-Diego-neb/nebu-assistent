import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from modo_rpm import AmostraBoost, COR_BOOST, COR_NEUTRA, ModoBoost, interpretar_pacote_boost


class HardwareFalso:
    def __init__(self) -> None:
        self.calls = []
        self.is_open = True

    def set_rgb(self, *cor) -> None:
        self.calls.append(("rgb", *cor))

    def set_boost(self, brilho: int) -> None:
        self.calls.append(("boost", brilho))

    def definir_cor_base(self, cor) -> None:
        self.calls.append(("cor_base", *cor))

    def restaurar(self) -> None:
        self.calls.append(("restaurar",))

    def close(self) -> None:
        self.calls.append(("close",))
        self.is_open = False


def pacote(boost: float, *, seq: int = 1, valid: bool = True) -> bytes:
    return json.dumps(
        {
            "v": 2,
            "seq": seq,
            "source": "rocket_league",
            "metric": "boost",
            "valid": valid,
            "value": boost,
        }
    ).encode()


def esperar(condicao, timeout: float = 1.5) -> bool:
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return False


class ParserBoostTests(unittest.TestCase):
    def test_interpreta_boost_e_rejeita_metrica_ou_faixa_errada(self) -> None:
        self.assertEqual(
            interpretar_pacote_boost(pacote(0.75, seq=42)),
            AmostraBoost(42, True, 0.75, "rocket_league"),
        )
        with self.assertRaises(ValueError):
            interpretar_pacote_boost(pacote(1.01))
        with self.assertRaises(ValueError):
            interpretar_pacote_boost(
                b'{"v":2,"seq":1,"source":"simhub","metric":"rpm","valid":false}'
            )

    def test_mapeamento_garante_extremos_de_um_e_cem(self) -> None:
        self.assertEqual(ModoBoost.brilho_do_boost(0), 1)
        self.assertEqual(ModoBoost.brilho_do_boost(0.5), 50)
        self.assertEqual(ModoBoost.brilho_do_boost(1), 100)
        self.assertEqual(ModoBoost.cor_do_boost(1), (0, 1, 3))
        self.assertEqual(ModoBoost.cor_do_boost(100), COR_BOOST)
        self.assertEqual(ModoBoost.cor_do_boost(50, (255, 20, 147)), (128, 10, 74))


class ModoBoostTests(unittest.TestCase):
    def test_burst_udp_usa_ultimo_valor_valido_sem_reproduzir_fila_antiga(self):
        pending = [
            (pacote(0.5, seq=2), ('127.0.0.1', 10)),
            (b'invalido', ('127.0.0.1', 10)),
            (pacote(1, seq=3), ('127.0.0.1', 10)),
            (pacote(0, seq=999), ('192.168.1.9', 10)),
            (pacote(0.1, seq=1), ('127.0.0.1', 10)),
        ]
        from unittest.mock import Mock
        receptor = Mock()
        receptor.recvfrom.side_effect = lambda _: pending.pop(0)
        with patch('modo_rpm.select.select', side_effect=lambda *_: ([receptor] if pending else [], [], [])):
            sample = self.modo._amostra_boost_recente(receptor, pacote(0, seq=1), ('127.0.0.1', 10))
        self.assertEqual(sample.boost, 1)
        self.assertEqual(sample.sequencia, 3)

    def setUp(self) -> None:
        self.envios: list[int] = []
        self.evento = threading.Event()

        def enviar(brilho: int) -> None:
            self.envios.append(brilho)
            self.evento.set()

        self.lightbar = HardwareFalso()
        self.teclado = HardwareFalso()
        self.modo = ModoBoost(
            enviar,
            host="127.0.0.1",
            port=0,
            brilho_retorno=37,
            fabrica_lightbar=lambda: self.lightbar,
            fabrica_teclado=lambda: self.teclado,
            cor_teclado=(255, 20, 147),
        )

    def tearDown(self) -> None:
        self.modo.parar()

    def _enviar(self, dados: bytes) -> None:
        assert self.modo._socket is not None
        porta = self.modo._socket.getsockname()[1]
        emissor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            emissor.sendto(dados, ("127.0.0.1", porta))
        finally:
            emissor.close()

    def test_udp_controla_brilho_e_parar_restaura_valor_anterior(self) -> None:
        self.modo.iniciar()
        self._enviar(pacote(0, seq=1))
        self.assertTrue(esperar(lambda: 1 in self.envios))
        self._enviar(pacote(1, seq=2))
        self.assertTrue(esperar(lambda: 100 in self.envios))
        status = self.modo.status()
        self.assertEqual(status["boost"], 100)
        self.assertTrue(status["recebendo"])
        self.assertIn(("rgb", *COR_BOOST), self.lightbar.calls)
        self.assertIn(("boost", 100), self.teclado.calls)
        self.assertIn(("cor_base", 255, 20, 147), self.teclado.calls)

        self.modo.parar()
        self.assertEqual(self.envios[-1], 37)
        self.assertIn(("rgb", *COR_NEUTRA), self.lightbar.calls)
        self.assertIn(("close",), self.teclado.calls)

    def test_timeout_restaura_brilho_e_aceita_sequencia_reiniciada(self) -> None:
        with (
            patch("modo_rpm.PACKET_TIMEOUT", 0.10),
            patch("modo_rpm.LAMP_INTERVAL", 0.02),
        ):
            self.modo.iniciar()
            self._enviar(pacote(0.25, seq=900))
            self.assertTrue(esperar(lambda: 26 in self.envios))
            self.assertTrue(esperar(lambda: self.envios[-1] == 37))
            self._enviar(pacote(0, seq=0))
            self.assertTrue(esperar(lambda: self.envios[-1] == 1))

    def test_pode_limitar_a_fonte_visual(self) -> None:
        self.modo.parar()
        self.modo = ModoBoost(
            self.envios.append,
            host="127.0.0.1",
            port=0,
            fonte_esperada="rocket_league_visual",
            fabrica_lightbar=None,
            fabrica_teclado=None,
        )
        self.modo.iniciar()
        self._enviar(pacote(0.5, seq=1))
        time.sleep(0.08)
        self.assertEqual(self.envios, [])
        visual = json.loads(pacote(0.5, seq=2))
        visual["source"] = "rocket_league_visual"
        self._enviar(json.dumps(visual).encode())
        self.assertTrue(esperar(lambda: 50 in self.envios))


if __name__ == "__main__":
    unittest.main()
