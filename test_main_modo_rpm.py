import unittest
from unittest.mock import patch

from abajur_tuya import ConfiguracaoTuya, ControleAbajurTuya
from abajur_wifi import ErroAbajur
from main import Nebula


CHAVE = "0123456789abcdef"


class SaidaFalsa:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ModoFalso:
    instancias: list["ModoFalso"] = []

    def __init__(self, saida_abajur=None, fabrica_lightbar="padrao") -> None:
        self.saida_abajur = saida_abajur
        self.fabrica_lightbar = fabrica_lightbar
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
        return {
            "ativo": self.ativo,
            "recebendo": True,
            "telemetria_valida": True,
            "rpm": 6123,
            "faixa": "laranja",
            "abajur": "conectado" if self.saida_abajur else "desativado",
            "erro": self.erro,
        }


class ControleTuyaFalso(ControleAbajurTuya):
    def __init__(self, *, falhar_preflight: bool = False) -> None:
        self.owner = None
        self.falhar_preflight = falhar_preflight
        self.rgb_enviados: list[tuple[int, int, int]] = []
        self.liberados: list[object] = []

    def preparar_animacao_externa(self, animacao) -> None:
        if self.falhar_preflight:
            raise ErroAbajur("abajur offline")
        self.owner = animacao

    def liberar_animacao_externa(self, animacao) -> None:
        self.liberados.append(animacao)
        if self.owner is animacao:
            self.owner = None

    def enviar_rgb_animacao(self, vermelho: int, verde: int, azul: int) -> None:
        self.rgb_enviados.append((vermelho, verde, azul))

    def parar_ritmo_navegador(self) -> None:
        if self.owner is not None:
            self.owner.parar()
            self.owner = None


class ModoControleIndisponivel(ModoFalso):
    def iniciar(self) -> None:
        if self.fabrica_lightbar is not None:
            from modo_rpm import ErroModoRPM

            raise ErroModoRPM("controle não encontrado")
        self.ativo = True


class IntegracaoMainModoRPMTests(unittest.TestCase):
    def setUp(self) -> None:
        ModoFalso.instancias.clear()
        self.saida = SaidaFalsa()
        self.nebula = Nebula(self.saida, abrir_navegador=False)
        self.nebula._alvos_modo['rpm'].update(lamp=True, controller=True, mobile=True)

    def tearDown(self) -> None:
        self.nebula.fechar()

    def test_inicia_status_e_para_sem_tuya(self) -> None:
        with (
            patch("main.ModoRPM", ModoFalso),
            patch.object(ConfiguracaoTuya, "carregar", return_value=None),
        ):
            self.assertTrue(self.nebula.executar("ative o modo rpm"))
            modo = ModoFalso.instancias[-1]
            self.assertTrue(modo.ativo)
            self.assertIn("abajur ficou de fora", self.saida.mensagens[-1])

            self.nebula.executar("status do modo rpm")
            self.assertIn("6123 RPM", self.saida.mensagens[-1])
            self.nebula.executar("pare o modo rpm")
            self.assertFalse(modo.ativo)
            self.assertEqual(modo.paradas, 1)
            self.assertIn("desligado", self.saida.mensagens[-1])

    def test_tuya_assume_e_libera_o_mesmo_owner(self) -> None:
        controle = ControleTuyaFalso()
        self.nebula._controle_abajur = controle
        config = ConfiguracaoTuya("id", "Auto", CHAVE, 3.5)
        with (
            patch("main.ModoRPM", ModoFalso),
            patch.object(ConfiguracaoTuya, "carregar", return_value=config),
        ):
            self.nebula.executar("sincronize as luzes com o rpm")
            modo = ModoFalso.instancias[-1]
            self.assertIs(controle.owner, modo)
            self.assertIsNotNone(modo.saida_abajur)
            self.assertIn("controle e no abajur", self.saida.mensagens[-1])
            self.nebula.executar("pare o modo rpm")
            self.assertIsNone(controle.owner)
            self.assertIn(modo, controle.liberados)

    def test_falha_do_preflight_tuya_nao_impede_controle(self) -> None:
        controle = ControleTuyaFalso(falhar_preflight=True)
        self.nebula._controle_abajur = controle
        config = ConfiguracaoTuya("id", "Auto", CHAVE, 3.5)
        with (
            patch("main.ModoRPM", ModoFalso),
            patch.object(ConfiguracaoTuya, "carregar", return_value=config),
        ):
            self.nebula.executar("ative o modo rpm")
        modo = ModoFalso.instancias[-1]
        self.assertTrue(modo.ativo)
        self.assertIsNone(modo.saida_abajur)
        self.assertIn("abajur offline", self.saida.mensagens[-1])

    def test_painel_continua_ativo_quando_controle_nao_esta_conectado(self) -> None:
        with (
            patch("main.ModoRPM", ModoControleIndisponivel),
            patch.object(ConfiguracaoTuya, "carregar", return_value=None),
        ):
            self.assertTrue(self.nebula.executar("ative o modo rpm"))
        modo = ModoFalso.instancias[-1]
        self.assertTrue(modo.ativo)
        self.assertIsNone(modo.fabrica_lightbar)
        self.assertIn("painel do celular", self.saida.mensagens[-1])
        self.assertIn("controle não encontrado", self.saida.mensagens[-1])


if __name__ == "__main__":
    unittest.main()
