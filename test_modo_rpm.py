import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from modo_rpm import (
    AmostraRPM,
    ClassificadorRPM,
    COR_AMARELA,
    COR_CORTE_ESCURO,
    COR_CORTE_BRILHO,
    COR_LARANJA,
    COR_NEUTRA,
    COR_VERMELHA,
    ModoRPM,
    interpretar_pacote,
)


def amostra(
    percentual: float,
    *,
    gas: float = 0.8,
    seq: int = 1,
    shifting: bool = False,
    drag: bool = False,
) -> AmostraRPM:
    minimo = 1000.0
    redline = 8000.0
    maximo = 9000.0
    limite = maximo if drag else redline
    rpm = minimo + percentual * (limite - minimo)
    return AmostraRPM(seq, True, rpm, minimo, redline, maximo, gas, 3, shifting, drag)


def pacote(sample: AmostraRPM) -> bytes:
    return json.dumps(
        {
            "v": 1,
            "seq": sample.sequencia,
            "valid": sample.valida,
            "rpm": sample.rpm,
            "min_rpm": sample.minimo,
            "redline_rpm": sample.redline,
            "max_rpm": sample.maximo,
            "gas": sample.acelerador,
            "gear": sample.marcha,
            "shifting": sample.trocando_marcha,
            "drag": sample.drag,
        }
    ).encode()


class FakeLightbar:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.event = threading.Event()
        self.is_open = True

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        self.calls.append(("rgb", red, green, blue))
        self.event.set()

    def flash(self, red: int, green: int, blue: int, *, on_ms: int, off_ms: int) -> None:
        self.calls.append(("flash", red, green, blue, on_ms, off_ms))
        self.event.set()

    def close(self) -> None:
        self.calls.append(("close",))
        self.is_open = False


def esperar(condicao, timeout: float = 1.5) -> bool:
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return False


class ParserTests(unittest.TestCase):
    def test_interpreta_schema_real_e_pacote_invalido(self) -> None:
        original = amostra(0.6, seq=42)
        recebido = interpretar_pacote(pacote(original))
        self.assertTrue(recebido.valida)
        self.assertEqual(recebido.sequencia, 42)
        self.assertAlmostEqual(recebido.acelerador, 0.8)
        with self.assertRaises(ValueError):
            interpretar_pacote(b'{"v":2}')
        with self.assertRaises(ValueError):
            interpretar_pacote(b"x" * 4097)

    def test_valid_false_nao_confia_nos_outros_campos(self) -> None:
        recebido = interpretar_pacote(b'{"v":1,"seq":7,"valid":false}')
        self.assertEqual(recebido, AmostraRPM(7, False))

    def test_interpreta_protocolo_generico_v2_com_fonte(self) -> None:
        dados = json.loads(pacote(amostra(0.6, seq=12)).decode())
        dados.update(
            {
                "v": 2,
                "metric": "rpm",
                "source": "assetto_corsa",
                "speed_kmh": 115.4,
                "turbo_bar": 1.2,
                "oil_pressure": 3.5,
                "oil_temp": 108.4,
                "fuel_percent": 62,
                "water_temp": 91,
                "engine_map": 2,
            }
        )
        recebido = interpretar_pacote(json.dumps(dados).encode())
        self.assertEqual(recebido.fonte, "assetto_corsa")
        self.assertAlmostEqual(recebido.velocidade_kmh, 115.4)
        self.assertAlmostEqual(recebido.turbo_bar, 1.2)
        self.assertAlmostEqual(recebido.pressao_oleo, 3.5)
        self.assertAlmostEqual(recebido.temperatura_oleo, 108.4)
        self.assertEqual(recebido.combustivel_percentual, 62)
        self.assertEqual(recebido.temperatura_agua, 91)
        self.assertEqual(recebido.mapa_motor, 2)
        self.assertTrue(recebido.valida)

    def test_rejeita_telemetria_opcional_fora_da_faixa(self) -> None:
        dados = json.loads(pacote(amostra(0.6)).decode())
        dados.update({"v": 2, "metric": "rpm", "speed_kmh": 1500})
        with self.assertRaises(ValueError):
            interpretar_pacote(json.dumps(dados).encode())


class ClassificadorTests(unittest.TestCase):
    def test_amarelo_claro_laranja_vermelho_independem_do_pedal(self) -> None:
        classificador = ClassificadorRPM()
        self.assertEqual(classificador.atualizar(amostra(0.3), 1).cor, COR_AMARELA)
        self.assertEqual(COR_AMARELA, (255, 225, 96))
        self.assertEqual(classificador.atualizar(amostra(0.65), 2).cor, COR_LARANJA)
        self.assertEqual(classificador.atualizar(amostra(0.90), 3).cor, COR_VERMELHA)
        estado = classificador.atualizar(amostra(0.95, gas=0.05), 4)
        self.assertEqual(estado.cor, COR_VERMELHA)

    def test_histerese_impede_troca_perto_do_limiar(self) -> None:
        classificador = ClassificadorRPM()
        self.assertEqual(classificador.atualizar(amostra(0.60), 1).faixa, "laranja")
        self.assertEqual(classificador.atualizar(amostra(0.54), 2).faixa, "laranja")
        self.assertEqual(classificador.atualizar(amostra(0.50), 3).faixa, "amarelo")
        classificador.neutralizar()
        self.assertEqual(classificador.atualizar(amostra(0.90), 4).faixa, "vermelho")
        self.assertEqual(classificador.atualizar(amostra(0.80), 5).faixa, "vermelho")
        self.assertEqual(classificador.atualizar(amostra(0.78), 6).faixa, "laranja")

    def test_corte_exige_debounce_gas_e_ausencia_de_troca(self) -> None:
        classificador = ClassificadorRPM()
        self.assertFalse(classificador.atualizar(amostra(0.99), 10.0).corte)
        self.assertFalse(classificador.atualizar(amostra(0.99), 10.07).corte)
        self.assertTrue(classificador.atualizar(amostra(0.99), 10.09).corte)
        self.assertTrue(classificador.atualizar(amostra(0.93), 10.12).corte)
        self.assertFalse(
            classificador.atualizar(amostra(0.99, shifting=True), 10.13).corte
        )
        self.assertFalse(classificador.atualizar(amostra(0.99, gas=0.4), 11).corte)

    def test_drag_usa_max_rpm_como_limite(self) -> None:
        classificador = ClassificadorRPM()
        estado = classificador.atualizar(amostra(0.99, drag=True), 1.0)
        self.assertGreaterEqual(estado.percentual, 0.98)
        self.assertFalse(estado.corte)
        self.assertTrue(classificador.atualizar(amostra(0.99, drag=True), 1.11).corte)


class ModoRPMTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lightbar = FakeLightbar()
        self.modo = ModoRPM(
            fabrica_lightbar=lambda: self.lightbar, host="127.0.0.1", port=0
        )

    def tearDown(self) -> None:
        self.modo.parar()

    def _enviar(self, sample: AmostraRPM) -> None:
        assert self.modo._socket is not None
        porta = self.modo._socket.getsockname()[1]
        emissor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            emissor.sendto(pacote(sample), ("127.0.0.1", porta))
        finally:
            emissor.close()

    def test_udp_dirige_lightbar_e_stop_restaura_neutro(self) -> None:
        self.modo.iniciar()
        self._enviar(amostra(0.65))
        self.assertTrue(
            esperar(lambda: ("rgb", *COR_LARANJA) in self.lightbar.calls)
        )
        status = self.modo.status()
        self.assertTrue(status["ativo"])
        self.assertTrue(status["recebendo"])
        self.assertEqual(status["faixa"], "laranja")

        self.modo.parar()
        self.assertIn(("rgb", *COR_NEUTRA), self.lightbar.calls)
        self.assertEqual(self.lightbar.calls[-1], ("close",))

    def test_corte_usa_flash_hardware(self) -> None:
        self.modo.iniciar()
        self._enviar(amostra(0.99, seq=1))
        time.sleep(0.12)
        self._enviar(amostra(0.99, seq=2))
        self.assertTrue(
            esperar(lambda: any(chamada[0] == "flash" for chamada in self.lightbar.calls))
        )
        flash = next(chamada for chamada in self.lightbar.calls if chamada[0] == "flash")
        self.assertEqual(flash[1:4], COR_VERMELHA)
        self.assertEqual(flash[4:], (250, 250))

    def test_controle_e_abajur_recebem_a_mesma_cor(self) -> None:
        envios: list[tuple[int, int, int]] = []
        self.modo.parar()
        self.modo = ModoRPM(
            saida_abajur=lambda vermelho, verde, azul: envios.append(
                (vermelho, verde, azul)
            ),
            fabrica_lightbar=lambda: self.lightbar,
            host="127.0.0.1",
            port=0,
        )
        self.modo.iniciar()
        self._enviar(amostra(0.30, seq=1))
        self.assertTrue(esperar(lambda: ("rgb", *COR_AMARELA) in self.lightbar.calls))
        self.assertTrue(esperar(lambda: COR_AMARELA in envios))

    def test_timeout_neutraliza_e_aceita_sequencia_reiniciada(self) -> None:
        with patch("modo_rpm.PACKET_TIMEOUT", 0.10):
            self.modo.iniciar()
            self._enviar(amostra(0.65, seq=900))
            self.assertTrue(esperar(lambda: self.modo.status()["faixa"] == "laranja"))
            self.assertTrue(esperar(lambda: self.modo.status()["faixa"] == "neutro"))
            self._enviar(amostra(0.3, seq=0))
            self.assertTrue(esperar(lambda: self.modo.status()["faixa"] == "amarelo"))

    def test_abajur_cadenciado_pisca_sem_bloquear_lightbar(self) -> None:
        envios: list[tuple[float, tuple[int, int, int]]] = []

        def enviar_lampada(red: int, green: int, blue: int) -> None:
            envios.append((time.monotonic(), (red, green, blue)))

        self.modo.parar()
        self.modo = ModoRPM(
            saida_abajur=enviar_lampada,
            fabrica_lightbar=lambda: self.lightbar,
            host="127.0.0.1",
            port=0,
        )
        self.modo.iniciar()
        self._enviar(amostra(0.99, seq=1))
        time.sleep(0.12)
        self._enviar(amostra(0.99, seq=2))
        self.assertTrue(
            esperar(
                lambda: {cor for _, cor in envios}
                >= {COR_CORTE_BRILHO, COR_CORTE_ESCURO},
                timeout=1.2,
            )
        )
        self.assertTrue(any(chamada[0] == "flash" for chamada in self.lightbar.calls))
        intervalos = [
            atual[0] - anterior[0]
            for anterior, atual in zip(envios, envios[1:])
        ]
        self.assertTrue(all(intervalo >= 0.10 for intervalo in intervalos))

    def test_abajur_falho_tenta_novamente_sem_parar_controle(self) -> None:
        tentativas = 0

        def enviar_lampada(_red: int, _green: int, _blue: int) -> None:
            nonlocal tentativas
            tentativas += 1
            if tentativas == 1:
                raise OSError("offline")

        self.modo.parar()
        self.modo = ModoRPM(
            saida_abajur=enviar_lampada,
            fabrica_lightbar=lambda: self.lightbar,
            host="127.0.0.1",
            port=0,
        )
        with patch("modo_rpm.LAMP_RETRY_INTERVAL", 0.05):
            self.modo.iniciar()
            self.assertTrue(esperar(lambda: tentativas >= 2))
        self.assertTrue(self.modo.ativo)
        self.assertIsNone(self.modo.status()["erro_abajur"])


if __name__ == "__main__":
    unittest.main()
