import unittest
from unittest.mock import patch, Mock

from abajur_tuya import ConfiguracaoTuya, ControleAbajurTuya
from abajur_wifi import ErroAbajur
from main import Nebula, interpretar_comando_modo_ambilight
from teclado_openrgb import OpenRGBKeyboardError


class SaidaFalsa:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ModoAmbilightFalso:
    instancias: list["ModoAmbilightFalso"] = []

    def __init__(self, saida_rgb, *, saida_secundaria=None, saida_controle=None, saida_zonas=None, capturador=None) -> None:
        self.saida_rgb = saida_rgb
        self.saida_secundaria = saida_secundaria
        self.saida_controle = saida_controle
        self.saida_zonas = saida_zonas
        self.capturador = capturador
        self.ativo = False
        self.erro = None
        self.restaurar = None
        self.paradas = 0
        self.instancias.append(self)

    def definir_restauracao(self, restaurar) -> None:
        self.restaurar = restaurar

    def iniciar(self) -> None:
        self.ativo = True

    def parar(self) -> None:
        if self.ativo and self.restaurar:
            self.restaurar()
        self.ativo = False
        self.paradas += 1

    def status(self):
        return {
            "ativo": self.ativo,
            "janela": True,
            "cor": (30, 60, 120),
            "capturas": 30,
            "envios": 10,
            "erro": self.erro,
        }


class ModoRPMHibridoFalso:
    def __init__(self, saida_abajur=None, fabrica_lightbar=None) -> None:
        self.saida_abajur = saida_abajur
        self.fabrica_lightbar = fabrica_lightbar
        self.ativo = False
        self.erro = None

    def iniciar(self) -> None:
        self.ativo = True

    def parar(self) -> None:
        self.ativo = False

    def status(self):
        return {
            "ativo": self.ativo,
            "recebendo": True,
            "telemetria_valida": True,
            "rpm": 4321,
            "percentual": 60.0,
            "faixa": "laranja",
            "fonte": "beamngdrive",
            "erro": None,
            "erro_abajur": None,
        }


class ControleAmbilightFalso(ControleAbajurTuya):
    def __init__(self) -> None:
        self.owner = None
        self.restaurados: list[int] = []
        self.liberados: list[object] = []

    def preparar_animacao_externa(self, animacao, *, preservar_perfil=False) -> int:
        if not preservar_perfil:
            raise AssertionError("O Ambilight deve preservar o perfil")
        self.owner = animacao
        return 42

    def liberar_animacao_externa(self, animacao) -> None:
        self.liberados.append(animacao)
        if self.owner is animacao:
            self.owner = None

    def enviar_rgb_animacao(self, vermelho, verde, azul) -> None:
        pass

    def restaurar_perfil_animacao(self, percentual: int) -> None:
        self.restaurados.append(percentual)

    def parar_ritmo_navegador(self) -> None:
        pass


class ControleAmbilightIndisponivel(ControleAmbilightFalso):
    def preparar_animacao_externa(self, animacao, *, preservar_perfil=False) -> int:
        raise OSError("lampada temporariamente offline")


class TecladoAmbilightFalso:
    def __init__(self) -> None:
        self.fechado = False

    def enviar_rgb(self, _red: int, _green: int, _blue: int) -> None:
        pass

    def enviar_zonas(self, colors):
        pass

    def close(self) -> None:
        self.fechado = True


class IntegracaoMainAmbilightTests(unittest.TestCase):
    def setUp(self) -> None:
        ModoAmbilightFalso.instancias.clear()
        self.saida = SaidaFalsa()
        self.nebula = Nebula(self.saida, abrir_navegador=False)
        self.nebula._alvos_modo["ambilight"].update(
            {"lamp": True, "keyboard": True}
        )

    def tearDown(self) -> None:
        self.nebula.fechar()

    def test_inicia_status_e_para_restaurando_perfil(self) -> None:
        controle = ControleAmbilightFalso()
        self.nebula._controle_abajur = controle
        config = ConfiguracaoTuya("id", "Auto", "0123456789abcdef", 3.5)
        with (
            patch("main.ModoAmbilight", ModoAmbilightFalso),
            patch(
                "main.criar_teclado_kumara",
                side_effect=OpenRGBKeyboardError("teclado fora do teste"),
            ),
            patch.object(ConfiguracaoTuya, "carregar", return_value=config),
        ):
            self.assertTrue(self.nebula.executar("ative o modo ambilight"))
            modo = ModoAmbilightFalso.instancias[-1]
            self.assertTrue(modo.ativo)
            self.assertIs(controle.owner, modo)

            self.nebula.executar("status do modo ambilight")
            self.assertIn("RGB", self.saida.mensagens[-1])
            self.nebula.executar("pare o modo ambilight")
            self.assertIsNone(controle.owner)
            self.assertEqual(controle.restaurados, [42])
            self.assertIn("restaurada", self.saida.mensagens[-1])

    def test_comandos_diretos(self) -> None:
        self.assertEqual(interpretar_comando_modo_ambilight("ative o modo ambilight"), "iniciar")
        self.assertEqual(
            interpretar_comando_modo_ambilight("faca a lampada acompanhar as cenas da netflix"),
            "iniciar",
        )
        self.assertEqual(interpretar_comando_modo_ambilight("pare o ambilight"), "parar")
        self.assertEqual(interpretar_comando_modo_ambilight("status do ambilight"), "status")
        self.assertIsNone(interpretar_comando_modo_ambilight("deixe a lampada azul"))

    def test_mantem_teclado_quando_abajur_falha_ao_preparar(self) -> None:
        controle = ControleAmbilightIndisponivel()
        teclado = TecladoAmbilightFalso()
        self.nebula._controle_abajur = controle
        config = ConfiguracaoTuya("id", "Auto", "0123456789abcdef", 3.5)
        with (
            patch("main.ModoAmbilight", ModoAmbilightFalso),
            patch("main.criar_teclado_kumara", return_value=teclado),
            patch.object(ConfiguracaoTuya, "carregar", return_value=config),
        ):
            self.assertTrue(self.nebula.executar("ative o modo ambilight"))
            modo = ModoAmbilightFalso.instancias[-1]
            self.assertIsNotNone(modo.saida_secundaria)
            self.assertIsNone(modo.saida_zonas)
            self.assertEqual(self.nebula.estado_controle()["mode"], "ambilight")
            self.assertIn("Kumara", self.saida.mensagens[-1])
            self.nebula.executar("pare o modo ambilight")
            self.assertTrue(teclado.fechado)

    def test_controle_direto_nao_mantem_estado_antigo_se_reinicio_falhar(self) -> None:
        self.nebula._modo_controle_selecionado = "ambilight"
        with (
            patch.object(self.nebula, "_obter_controle_abajur", side_effect=OSError),
            patch.object(self.nebula, "executar", return_value=False),
        ):
            with self.assertRaises(ErroAbajur):
                self.nebula.executar_controle("mode", "ambilight")
        self.assertEqual(self.nebula.estado_controle()["mode"], "manual")

    def test_beamng_ambiente_mantem_telemetria_e_ambilight_simultaneos(self) -> None:
        controle = ControleAmbilightFalso()
        teclado = TecladoAmbilightFalso()
        self.nebula._controle_abajur = controle
        config = ConfiguracaoTuya("id", "Auto", "0123456789abcdef", 3.5)
        with (
            patch("main.ModoRPM", ModoRPMHibridoFalso),
            patch("main.ModoAmbilight", ModoAmbilightFalso),
            patch("main.criar_teclado_kumara", return_value=teclado),
            patch.object(ConfiguracaoTuya, "carregar", return_value=config),
        ):
            resposta = self.nebula.executar_controle("mode", "beamng")
            estado = resposta["state"]
            self.assertEqual(estado["mode"], "beamng")
            self.assertEqual(estado["rpm"], 4321)
            self.assertTrue(self.nebula._modo_rpm.ativo)
            self.assertTrue(self.nebula._modo_ambilight.ativo)
            self.assertIs(controle.owner, self.nebula._modo_ambilight)
            self.assertEqual(self.nebula._modo_ambilight.capturador.titulo, "beamng")
            self.assertIsNone(self.nebula._modo_rpm.saida_abajur)
            self.assertIsNone(self.nebula._modo_rpm.fabrica_lightbar)

            desligado = self.nebula.executar_controle("mode", "manual")
            self.assertEqual(desligado["state"]["mode"], "manual")
            self.assertTrue(teclado.fechado)

    def test_ambilight_com_rpm_mobile_nao_disputa_luz_com_telemetria(self):
        controle = ControleAmbilightFalso()
        teclado = TecladoAmbilightFalso()
        self.nebula._controle_abajur = controle
        self.nebula._alvos_modo['ambilight_rpm'].update(lamp=True, keyboard=True, controller=True, mobile=True)
        config = ConfiguracaoTuya('id','Auto','0123456789abcdef',3.5)
        lightbar = Mock()
        with patch('main.ModoRPM',ModoRPMHibridoFalso), patch('main.ModoAmbilight',ModoAmbilightFalso), patch('main.criar_teclado_kumara',return_value=teclado), patch('main.DS4Lightbar',return_value=lightbar), patch.object(ConfiguracaoTuya,'carregar',return_value=config):
            result = self.nebula.executar_controle('mode','ambilight_rpm')
            self.assertEqual(result['state']['mode'],'ambilight_rpm')
            self.assertEqual(result['state']['rpm'],4321)
            self.assertIsNone(self.nebula._modo_rpm.saida_abajur)
            self.assertIsNone(self.nebula._modo_rpm.fabrica_lightbar)
            self.assertIsNone(self.nebula._modo_ambilight.capturador)
            self.assertEqual(self.nebula._modo_ambilight.saida_controle,lightbar.set_rgb)
            self.assertIs(controle.owner,self.nebula._modo_ambilight)
            self.nebula.executar_controle('mode','manual')
            lightbar.close.assert_called()


if __name__ == "__main__":
    unittest.main()
