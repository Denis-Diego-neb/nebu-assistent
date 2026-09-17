from __future__ import annotations

import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from abajur_tuya import ConfiguracaoTuya, ControleAbajurTuya
from abajur_wifi import ErroAbajur
from main import Nebula


CHAVE_TESTE = "0123456789abcdef"


class BulbFalso:
    """Bulb TinyTuya estritamente local, sem socket ou dispositivo real."""

    instancias: list["BulbFalso"] = []
    registro: list[object] = []
    falhar_status = False

    def __init__(self, **opcoes: object) -> None:
        self.opcoes = opcoes
        self.eventos: list[object] = []
        self.bulb_configured = True
        type(self).instancias.append(self)

    def status(self) -> dict[str, object]:
        self.eventos.append("status")
        type(self).registro.append("status")
        if type(self).falhar_status:
            raise OSError("falha de rede simulada")
        return {
            "dps": {
                "20": True,
                "21": "colour",
                "22": 800,
                "24": "007801f40320",
            }
        }

    def set_hsv(self, matiz: float, saturacao: float, valor: float) -> dict[str, object]:
        if not all(
            isinstance(canal, (int, float)) and math.isfinite(canal) and 0.0 <= canal <= 1.0
            for canal in (matiz, saturacao, valor)
        ):
            raise AssertionError("HSV fora da faixa aceita pelo Bulb fake")
        evento = ("hsv", matiz, saturacao, valor)
        self.eventos.append(evento)
        type(self).registro.append(evento)
        return {"dps": {"20": True, "21": "colour"}}


class AnimacaoFalsa:
    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.paradas = 0

    @property
    def ativo(self) -> bool:
        return True

    @property
    def erro(self) -> str | None:
        return None

    def parar(self) -> None:
        self.paradas += 1
        BulbFalso.registro.append(f"parar:{self.nome}")


class SaidaColetora:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class IntegracaoRpmTuyaTests(unittest.TestCase):
    def setUp(self) -> None:
        BulbFalso.instancias.clear()
        BulbFalso.registro.clear()
        BulbFalso.falhar_status = False
        self.tinytuya_falso = SimpleNamespace(BulbDevice=BulbFalso)
        self.configuracao = ConfiguracaoTuya(
            device_id="dispositivo-teste",
            address="192.0.2.10",
            local_key=CHAVE_TESTE,
            version=3.5,
        )

    def test_preparar_animacao_para_anterior_faz_preflight_e_assume_ownership(self) -> None:
        controle = ControleAbajurTuya(self.configuracao)
        anterior = AnimacaoFalsa("anterior")
        nova = AnimacaoFalsa("rpm")
        controle._ritmo_navegador = anterior

        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle.preparar_animacao_externa(nova)

        self.assertEqual(BulbFalso.registro, ["parar:anterior", "status"])
        self.assertEqual(anterior.paradas, 1)
        self.assertIs(controle._ritmo_navegador, nova)
        self.assertEqual(BulbFalso.instancias[0].eventos, ["status"])

    def test_preflight_falho_para_anterior_e_nao_entrega_ownership(self) -> None:
        controle = ControleAbajurTuya(self.configuracao)
        anterior = AnimacaoFalsa("anterior")
        nova = AnimacaoFalsa("rpm")
        controle._ritmo_navegador = anterior
        BulbFalso.falhar_status = True

        with (
            patch("abajur_tuya.tinytuya", self.tinytuya_falso),
            self.assertRaises(ErroAbajur),
        ):
            controle.preparar_animacao_externa(nova)

        self.assertEqual(BulbFalso.registro, ["parar:anterior", "status"])
        self.assertEqual(anterior.paradas, 1)
        self.assertIsNone(controle._ritmo_navegador)

    def test_enviar_rgb_animacao_converte_amarelo_vermelho_e_escuro_em_hsv_valido(self) -> None:
        controle = ControleAbajurTuya(self.configuracao)

        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle.enviar_rgb_animacao(255, 255, 0)
            controle.enviar_rgb_animacao(255, 0, 0)
            controle.enviar_rgb_animacao(0, 0, 0)

        envios = [evento for evento in BulbFalso.instancias[0].eventos if evento[0] == "hsv"]
        self.assertEqual(len(envios), 3)
        esperados = (
            (1.0 / 6.0, 1.0, 1.0),
            (0.0, 1.0, 1.0),
            (0.0, 0.0, 0.01),
        )
        for envio, esperado in zip(envios, esperados, strict=True):
            _, matiz, saturacao, valor = envio
            self.assertTrue(0.0 <= matiz <= 1.0)
            self.assertTrue(0.0 <= saturacao <= 1.0)
            self.assertTrue(0.0 <= valor <= 1.0)
            self.assertAlmostEqual(matiz, esperado[0], places=7)
            self.assertAlmostEqual(saturacao, esperado[1], places=7)
            self.assertAlmostEqual(valor, esperado[2], places=7)

    def test_animacao_de_brilho_preserva_cor_e_retorna_brilho_inicial(self) -> None:
        controle = ControleAbajurTuya(self.configuracao)
        owner = AnimacaoFalsa("boost")

        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            inicial = controle.preparar_animacao_externa(
                owner,
                preservar_perfil=True,
            )
            cor_perfil = controle.cor_perfil_animacao()
            controle.enviar_brilho_animacao(1)
            controle.enviar_brilho_animacao(100)

        self.assertEqual(inicial, 80)
        self.assertEqual(cor_perfil, (128, 255, 128))
        envios = [
            evento for evento in BulbFalso.instancias[0].eventos
            if isinstance(evento, tuple) and evento[0] == "hsv"
        ]
        self.assertEqual(envios, [("hsv", 1 / 3, 0.5, 0.01), ("hsv", 1 / 3, 0.5, 1.0)])

    def test_liberar_animacao_externa_aceita_somente_o_mesmo_owner(self) -> None:
        controle = ControleAbajurTuya(self.configuracao)
        owner = AnimacaoFalsa("rpm")
        intruso = AnimacaoFalsa("outro")

        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle.preparar_animacao_externa(owner)

        controle.liberar_animacao_externa(intruso)
        self.assertIs(controle._ritmo_navegador, owner)
        controle.liberar_animacao_externa(owner)
        self.assertIsNone(controle._ritmo_navegador)

    def test_nebula_sem_configuracao_orienta_aba_e_nunca_usa_elgin(self) -> None:
        saida = SaidaColetora()
        nebula = Nebula(saida, abrir_navegador=False)

        with (
            patch("main.ConfiguracaoTuya.carregar", return_value=None) as carregar,
            patch("main.ControleAbajurTuya") as construir_tuya,
            patch("abajur_wifi.ControleAbajurElgin") as construir_elgin,
        ):
            with self.assertRaises(ErroAbajur) as contexto:
                nebula._obter_controle_abajur()
            executado = nebula._executar_comando_abajur("ligue o abajur")

        self.assertTrue(executado)
        self.assertIn("aba configuração", str(contexto.exception).casefold())
        self.assertEqual(len(saida.mensagens), 1)
        self.assertIn("aba configuração", saida.mensagens[0].casefold())
        self.assertIsNone(nebula._controle_abajur)
        self.assertEqual(carregar.call_count, 2)
        construir_tuya.assert_not_called()
        construir_elgin.assert_not_called()

    def test_reconfigurar_abajur_substitui_controle_existente(self) -> None:
        nebula = Nebula(SaidaColetora(), abrir_navegador=False)
        anterior = Mock(name="controle_anterior")
        novo = Mock(name="controle_novo")
        configuracao = Mock(spec=ConfiguracaoTuya)
        nebula._controle_abajur = anterior
        nebula._ultimo_comando_abajur_falho = "ligue o abajur"

        with patch("main.ControleAbajurTuya", return_value=novo) as construir:
            nebula.reconfigurar_abajur(configuracao)
            with patch("main.ConfiguracaoTuya.carregar") as carregar:
                self.assertIs(nebula._obter_controle_abajur(), novo)
                carregar.assert_not_called()

        configuracao.validar.assert_called_once_with()
        construir.assert_called_once_with(configuracao)
        anterior.parar_ritmo_navegador.assert_called_once_with()
        self.assertIs(nebula._controle_abajur, novo)
        self.assertIsNone(nebula._ultimo_comando_abajur_falho)


if __name__ == "__main__":
    unittest.main()
