import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from abajur_tuya import ConfiguracaoTuya
from main import Nebula
from teclado_attack_shark import AttackSharkNotFoundError
from teclado_openrgb import OpenRGBKeyboardError
from test_main_modo_ambilight import ControleAmbilightFalso, ModoAmbilightFalso, SaidaFalsa
from test_teclados_rgb import TecladoFalso


class ModosNosDoisTecladosTests(unittest.TestCase):
    """Os modos da Nebula no Kumara e no Attack Shark, com teclados falsos."""

    def setUp(self) -> None:
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        ambiente = patch.dict(os.environ, {"LOCALAPPDATA": pasta.name})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        ModoAmbilightFalso.instancias.clear()
        self.kumara = TecladoFalso(zonas=True)
        self.shark = TecladoFalso("Attack Shark")
        self.fabrica_kumara = Mock(return_value=self.kumara)
        self.fabrica_shark = Mock(return_value=self.shark)
        for alvo, fabrica in (("main.criar_teclado_kumara", self.fabrica_kumara),
                              ("main.AttackSharkX98HE", self.fabrica_shark)):
            patcher = patch(alvo, fabrica)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.saida = SaidaFalsa()
        self.nebula = Nebula(self.saida, abrir_navegador=False)
        self.addCleanup(self.nebula.fechar)

    def selecionar(self, modo: str) -> dict:
        return self.nebula.executar_controle("device.mode", {"device": "keyboard", "mode": modo})

    def test_efeito_do_firmware_vai_aos_dois_e_fica_ate_trocar_o_modo(self) -> None:
        self.selecionar("onda")
        self.assertNotIn("keyboard", self.nebula._device_errors)
        for teclado in (self.kumara, self.shark):
            self.assertEqual(teclado.chamadas, [("efeito_nativo", "onda", (0, 80, 255))])
            self.assertFalse(teclado.fechado)
        self.selecionar("manual")
        self.assertTrue(self.kumara.fechado and self.shark.fechado)

    def test_cor_fixa_e_efeito_so_com_o_attack_shark(self) -> None:
        self.fabrica_kumara.side_effect = OpenRGBKeyboardError("O Kumara nao esta conectado.")
        self.selecionar("static")
        self.assertEqual(self.shark.chamadas, [("enviar_rgb", 0, 80, 255)])
        self.assertNotIn("keyboard", self.nebula._device_errors)
        self.selecionar("respirar")
        self.assertTrue(self.shark.fechado)  # o efeito anterior soltou o teclado antes
        self.assertEqual(self.fabrica_shark.call_count, 2)
        self.fabrica_kumara.assert_called_with(iniciar_openrgb=False)

    def test_sem_nenhum_teclado_o_erro_aparece_no_dispositivo(self) -> None:
        self.fabrica_kumara.side_effect = OpenRGBKeyboardError("O Kumara nao esta conectado.")
        self.fabrica_shark.side_effect = AttackSharkNotFoundError("Nao encontrei o Attack Shark X98HE.")
        self.selecionar("onda")
        self.assertIn("Attack Shark", self.nebula._device_errors["keyboard"])

    def test_afterfire_no_manual_pisca_os_dois(self) -> None:
        with patch("exhaust_flash.ExhaustFlash") as flash:
            self.nebula.executar_controle("device.flash", {"device": "keyboard", "enabled": True})
        grupo = flash.call_args.args[0]
        self.assertEqual(grupo.nomes, ("Kumara", "Attack Shark"))
        flash.return_value.enviar_rgb.assert_called_once_with(0, 0, 0)

    def test_boost_recebe_os_dois_teclados(self) -> None:
        grupo = self.nebula._teclado_independente()
        grupo.definir_cor_base((255, 20, 147))
        grupo.set_boost(40)
        for teclado in (self.kumara, self.shark):
            self.assertEqual(teclado.chamadas, [("definir_cor_base", (255, 20, 147)), ("set_boost", 40)])
        grupo.close()

    def test_ambilight_nos_dois_teclados(self) -> None:
        controle = ControleAmbilightFalso()
        self.nebula._controle_abajur = controle
        self.nebula._alvos_modo["ambilight"].update({"lamp": True, "keyboard": True})
        config = ConfiguracaoTuya("id", "Auto", "0123456789abcdef", 3.5)
        with patch("main.ModoAmbilight", ModoAmbilightFalso), patch.object(ConfiguracaoTuya, "carregar", return_value=config):
            self.assertTrue(self.nebula.executar("ative o modo ambilight"))
            modo = ModoAmbilightFalso.instancias[-1]
            modo.saida_zonas([(0, 0, 90), (30, 60, 0), (0, 30, 0)])
            self.assertIn("Kumara e Attack Shark acompanham", self.saida.mensagens[-1])
            self.nebula.executar("pare o modo ambilight")
        self.assertEqual(self.kumara.chamadas, [("enviar_zonas", ((0, 0, 90), (30, 60, 0), (0, 30, 0)))])
        self.assertEqual(self.shark.chamadas, [("enviar_rgb", 10, 30, 30)])
        self.assertTrue(self.kumara.fechado and self.shark.fechado)

    def test_ambilight_so_no_attack_shark_sem_abajur(self) -> None:
        self.fabrica_kumara.side_effect = OpenRGBKeyboardError("O Kumara nao esta conectado.")
        self.nebula._alvos_modo["ambilight"].update({"lamp": False, "keyboard": True})
        with patch("main.ModoAmbilight", ModoAmbilightFalso):
            self.assertTrue(self.nebula.executar("ative o modo ambilight"))
        modo = ModoAmbilightFalso.instancias[-1]
        self.assertIsNone(modo.saida_zonas)
        modo.saida_secundaria(200, 40, 0)
        self.assertEqual(self.shark.chamadas, [("enviar_rgb", 200, 40, 0)])
        self.assertIn("Ambilight ativado no Attack Shark", self.saida.mensagens[-1])

    def test_novo_modo_no_teclado_encerra_o_ambilight_do_modo_chuva(self) -> None:
        chuva = Mock()
        self.nebula._teclado_chuva = chuva
        self.nebula._teclado_independente().close()
        chuva.parar.assert_called_once()
        self.assertIsNone(self.nebula._teclado_chuva)


if __name__ == "__main__":
    unittest.main()
