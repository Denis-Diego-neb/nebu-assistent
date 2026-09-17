from math import cos, pi, sin
import unittest

from PIL import Image, ImageDraw

from leitor_boost_visual import (
    FiltroBoostVisual,
    estimar_boost_pelo_aro,
    extrair_valor_boost,
)


def hud_sintetico(percentual: int, cor: tuple[int, int, int]) -> Image.Image:
    imagem = Image.new("RGB", (403, 324), (35, 42, 50))
    if percentual:
        desenho = ImageDraw.Draw(imagem)
        fim = 90 + 230 * percentual / 100
        for angulo in range(90, round(fim) + 1):
            radianos = angulo * pi / 180
            for raio in range(97, 117):
                x = round(236 + raio * cos(radianos))
                y = round(155 + raio * sin(radianos))
                desenho.point((x, y), fill=cor)
    return imagem


class LeitorBoostVisualTests(unittest.TestCase):
    def test_legenda_boost_nao_vira_zero(self) -> None:
        self.assertIsNone(extrair_valor_boost(["BOOST"]))
        self.assertEqual(extrair_valor_boost(["95", "BOOST"]), 95)

    def test_aro_independe_da_cor(self) -> None:
        for cor in ((245, 126, 20), (30, 155, 245)):
            for esperado in (0, 20, 50, 75, 100):
                with self.subTest(cor=cor, esperado=esperado):
                    estimado = estimar_boost_pelo_aro(hud_sintetico(esperado, cor))
                    self.assertIsNotNone(estimado)
                    self.assertLessEqual(abs(estimado - esperado), 3)

    def test_filtro_confirma_salto_grande(self) -> None:
        filtro = FiltroBoostVisual()
        self.assertIsNone(filtro.atualizar(80))
        self.assertEqual(filtro.atualizar(80), 80)
        self.assertIsNone(filtro.atualizar(20))
        self.assertEqual(filtro.atualizar(20), 20)


if __name__ == "__main__":
    unittest.main()
