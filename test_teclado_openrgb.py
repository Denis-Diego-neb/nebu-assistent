import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from teclado_openrgb import _leds_acesos_barra, zonas_por_coluna, OpenRGBKeyboardError
from teclado_openrgb import TecladoKumaraOpenRGB


class BarraBoostKumaraTests(unittest.TestCase):
    def test_evision_uses_uniform_ambilight_instead_of_nonatomic_frames(self):
        from modules.iot.ambilight import selecionar_saidas_teclado
        keyboard = Mock(name="keyboard")
        keyboard.name = "EVision Keyboard"
        keyboard.colors = [(0, 0, 0)]
        keyboard.active_mode = 0
        keyboard.modes = [SimpleNamespace(name="Static")]
        keyboard.zones = []
        client = Mock(devices=[keyboard])
        with patch("teclado_openrgb.iniciar_servidor_openrgb"), patch.dict("sys.modules", {
            "openrgb": SimpleNamespace(OpenRGBClient=lambda **_: client),
            "openrgb.utils": SimpleNamespace(RGBColor=lambda *rgb: rgb),
        }):
            device = TecladoKumaraOpenRGB()
            output = selecionar_saidas_teclado(device)
            self.assertFalse(output.multizona)
            self.assertEqual(output.secundaria, device.enviar_rgb)
            keyboard.set_mode.assert_not_called()
            device.close()

    def test_zonas_seguem_coluna_fisica_e_ignoram_led_sem_tecla(self):
        matrix = [[4, 3, 2, 1, 0, 5], [6, None, 7, 8, 9, 10]]
        mapping = zonas_por_coluna(12, matrix)
        self.assertEqual((mapping[4],mapping[2],mapping[0]), (0,1,2))
        self.assertNotIn(11, mapping)
        six_zones = zonas_por_coluna(12, matrix, 6)
        self.assertEqual({six_zones[index] for index in six_zones}, set(range(6)))
        with self.assertRaises(OpenRGBKeyboardError):
            zonas_por_coluna(12, None)
    def setUp(self) -> None:
        self.matriz = [
            [0, 1, 2, 3],
            [4, None, 5, 6],
        ]

    def test_zero_apaga_todos_e_cem_acende_todos(self) -> None:
        self.assertEqual(_leds_acesos_barra(8, self.matriz, 0), set())
        self.assertEqual(_leds_acesos_barra(8, self.matriz, 100), set(range(8)))

    def test_cinquenta_por_cento_acende_metade_esquerda(self) -> None:
        self.assertEqual(_leds_acesos_barra(8, self.matriz, 50), {0, 1, 4})

    def test_sem_matriz_usa_ordem_linear(self) -> None:
        self.assertEqual(_leds_acesos_barra(10, None, 50), set(range(5)))


if __name__ == "__main__":
    unittest.main()
