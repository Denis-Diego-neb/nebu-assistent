import unittest
import os
from unittest.mock import patch

from abajur_tuya import ConfiguracaoTuya, ControleAbajurTuya
from main import Nebula, interpretar_comando_modo_boost


class SaidaFalsa:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ModoBoostFalso:
    instancias: list["ModoBoostFalso"] = []

    def __init__(self, saida_abajur, fonte_esperada=None, **dispositivos) -> None:
        self.saida_abajur = saida_abajur
        self.fonte_esperada = fonte_esperada
        self.dispositivos = dispositivos
        self.retorno = None
        self.cor_controle = None
        self.ativo = False
        self.erro = None
        self.paradas = 0
        self.instancias.append(self)

    def definir_brilho_retorno(self, brilho: int) -> None:
        self.retorno = brilho

    def definir_cor_controle(self, cor: tuple[int, int, int]) -> None:
        self.cor_controle = cor

    def iniciar(self) -> None:
        self.ativo = True

    def parar(self) -> None:
        self.ativo = False
        self.paradas += 1

    def status(self) -> dict[str, object]:
        return {
            "ativo": self.ativo,
            "recebendo": True,
            "telemetria_valida": True,
            "boost": 73,
            "brilho": 73,
            "erro": self.erro,
        }


class LeitorBoostVisualFalso:
    instancias: list["LeitorBoostVisualFalso"] = []

    def __init__(self) -> None:
        self.ativo = False
        self.erro = None
        self.paradas = 0
        self.instancias.append(self)

    def iniciar(self) -> None:
        self.ativo = True

    def parar(self) -> None:
        self.ativo = False
        self.paradas += 1

    def status(self) -> dict[str, object]:
        return {"ativo": self.ativo, "janela": True, "valor": 73, "erro": self.erro}


class ControleBoostFalso(ControleAbajurTuya):
    def __init__(self) -> None:
        self.owner = None
        self.liberados: list[object] = []

    def preparar_animacao_externa(self, animacao, *, preservar_perfil=False) -> int:
        self.owner = animacao
        if not preservar_perfil:
            raise AssertionError("O modo boost deve preservar o perfil de cor")
        return 64

    def liberar_animacao_externa(self, animacao) -> None:
        self.liberados.append(animacao)
        if self.owner is animacao:
            self.owner = None

    def enviar_brilho_animacao(self, percentual: int) -> None:
        pass

    def cor_perfil_animacao(self) -> tuple[int, int, int]:
        return 255, 20, 147

    def parar_ritmo_navegador(self) -> None:
        pass


class IntegracaoMainModoBoostTests(unittest.TestCase):
    def setUp(self) -> None:
        ModoBoostFalso.instancias.clear()
        LeitorBoostVisualFalso.instancias.clear()
        self.saida = SaidaFalsa()
        self.nebula = Nebula(self.saida, abrir_navegador=False)

    def tearDown(self) -> None:
        self.nebula.fechar()

    def test_inicia_status_e_para_restaurando_brilho(self) -> None:
        controle = ControleBoostFalso()
        self.nebula._controle_abajur = controle
        self.nebula._cor_teclado_boost = (0, 80, 255)
        config = ConfiguracaoTuya("id", "Auto", "0123456789abcdef", 3.5)
        with (
            patch("main.ModoBoost", ModoBoostFalso),
            patch("main.LeitorBoostVisual", LeitorBoostVisualFalso),
            patch.object(ConfiguracaoTuya, "carregar", return_value=config),
            patch.object(self.nebula, "_alvo_ativo", return_value=True),
            patch.dict(os.environ, {"NEBULA_BOOST_SOURCE": "rocket_league_visual"}),
        ):
            self.assertTrue(self.nebula.executar("ative o modo boost"))
            modo = ModoBoostFalso.instancias[-1]
            leitor = LeitorBoostVisualFalso.instancias[-1]
            self.assertEqual(modo.retorno, 64)
            self.assertEqual(modo.cor_controle, (255, 20, 147))
            self.assertEqual(modo.dispositivos["cor_teclado"], (0, 80, 255))
            self.assertEqual(modo.fonte_esperada, "rocket_league_visual")
            self.assertTrue(leitor.ativo)
            self.assertIs(controle.owner, modo)

            self.nebula.executar("status do modo boost")
            self.assertIn("73% de boost", self.saida.mensagens[-1])
            self.nebula.executar("pare o modo boost")
            self.assertIsNone(controle.owner)
            self.assertFalse(leitor.ativo)
            self.assertIn("restaurado", self.saida.mensagens[-1])

    def test_plugin_offline_pode_ser_escolhido_sem_abrir_leitor_visual(self) -> None:
        controle = ControleBoostFalso()
        self.nebula._controle_abajur = controle
        config = ConfiguracaoTuya("id", "Auto", "0123456789abcdef", 3.5)
        with (
            patch("main.ModoBoost", ModoBoostFalso),
            patch("main.LeitorBoostVisual", LeitorBoostVisualFalso),
            patch.object(ConfiguracaoTuya, "carregar", return_value=config),
            patch.dict(os.environ, {"NEBULA_BOOST_SOURCE": "rocket_league"}),
        ):
            self.nebula.executar("ative o modo boost")
            modo = ModoBoostFalso.instancias[-1]
            self.assertEqual(modo.fonte_esperada, "rocket_league")
            self.assertEqual(LeitorBoostVisualFalso.instancias, [])
            self.assertIn("plugin offline", self.saida.mensagens[-1])

    def test_comandos_diretos(self) -> None:
        self.assertEqual(interpretar_comando_modo_boost("ative o modo boost"), "iniciar")
        self.assertEqual(
            interpretar_comando_modo_boost("faça o brilho reagir ao boost do Rocket League"),
            "iniciar",
        )
        self.assertEqual(interpretar_comando_modo_boost("pare o modo boost"), "parar")
        self.assertEqual(interpretar_comando_modo_boost("status do modo boost"), "status")


if __name__ == "__main__":
    unittest.main()
