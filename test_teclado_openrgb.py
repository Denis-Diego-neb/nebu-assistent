import unittest

from teclado_openrgb import _leds_acesos_barra, zonas_por_coluna, OpenRGBKeyboardError


class BarraBoostKumaraTests(unittest.TestCase):
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
