import threading
import time
import unittest

from PIL import Image

from modo_ambilight import (
    ModoAmbilight,
    calcular_cor_ambiente,
    calcular_paleta_ambiente,
    captura_parece_protegida,
    suavizar_cor,
    calcular_media_tela,
    calcular_zonas_inferiores,
)


class CapturadorFalso:
    def __init__(self, cor=(20, 80, 180)) -> None:
        self.imagem = Image.new("RGB", (320, 180), cor)
        self.capturas = 0

    def capturar(self):
        self.capturas += 1
        return self.imagem.copy()


class ModoAmbilightTests(unittest.TestCase):
    def test_grade_inferior_usa_doze_faixas_por_padrao(self):
        image = Image.new("RGB", (300, 300), "white")
        for i, color in enumerate(((255,0,0), (0,255,0), (0,0,255))):
            image.paste(color, (i*100,200,(i+1)*100,300))
        self.assertEqual(
            calcular_zonas_inferiores(image),
            ((255,0,0),) * 4 + ((0,255,0),) * 4 + ((0,0,255),) * 4,
        )
        self.assertEqual(
            calcular_zonas_inferiores(image, 3),
            ((255,0,0),(0,255,0),(0,0,255)),
        )
        mean = calcular_media_tela(image)
        self.assertTrue(all(abs(v-198) <= 2 for v in mean))

    def test_ps4_e_lampada_recebem_media_e_teclado_doze_cores(self):
        lamp, controller, keyboard = [], [], []
        capture = CapturadorFalso()
        capture.imagem = Image.new('RGB', (300,300), (30,60,90))
        capture.imagem.paste((255,0,0), (0,200,100,300))
        capture.imagem.paste((0,255,0), (100,200,200,300))
        capture.imagem.paste((0,0,255), (200,200,300,300))
        mode = ModoAmbilight(lambda *c: lamp.append(c), saida_controle=lambda *c: controller.append(c), saida_zonas=keyboard.append, capturador=capture)
        try:
            mode.iniciar()
        finally:
            mode.parar()
        self.assertEqual(lamp[0], controller[0])
        self.assertEqual(
            keyboard[0],
            ((255,0,0),) * 4 + ((0,255,0),) * 4 + ((0,0,255),) * 4,
        )
        self.assertEqual(mode.status()["quantidade_zonas_teclado"], 12)

    def test_quantidade_de_zonas_pode_ser_personalizada(self):
        image = Image.new("RGB", (240, 180), (20, 40, 60))
        self.assertEqual(len(calcular_zonas_inferiores(image, 6)), 6)
        with self.assertRaises(ValueError):
            calcular_zonas_inferiores(image, 0)

    def test_calculo_ignora_barras_pretas_e_preserva_tom_da_cena(self) -> None:
        imagem = Image.new("RGB", (400, 240), (0, 0, 0))
        imagem.paste((20, 80, 190), (0, 40, 400, 200))
        vermelho, verde, azul = calcular_cor_ambiente(imagem)
        self.assertGreater(azul, verde)
        self.assertGreater(verde, vermelho)
        self.assertGreater(azul, 120)

    def test_suavizacao_avanca_sem_saltar_diretamente_para_cor_nova(self) -> None:
        cor = suavizar_cor((0.0, 0.0, 0.0), (255, 120, 60), 0.05, 0.15)
        self.assertGreater(cor[0], 0)
        self.assertLess(cor[0], 255)
        self.assertGreater(cor[0], cor[1])

    def test_paleta_encontra_cor_secundaria_diferente(self) -> None:
        imagem = Image.new("RGB", (400, 240), (20, 60, 190))
        imagem.paste((220, 150, 20), (240, 0, 400, 240))
        principal, secundaria = calcular_paleta_ambiente(imagem)
        self.assertNotEqual(principal, secundaria)
        self.assertGreater(sum(abs(a - b) for a, b in zip(principal, secundaria)), 60)

    def test_detecta_quadro_protegido_sem_confundir_cena_colorida(self) -> None:
        protegido = Image.new("RGB", (320, 180), (0, 0, 0))
        protegido.paste((100, 100, 100), (150, 160, 170, 170))
        self.assertTrue(captura_parece_protegida(protegido))
        self.assertFalse(captura_parece_protegida(Image.new("RGB", (320, 180), (20, 40, 90))))

    def test_loop_envia_rgb_e_restaura_perfil_uma_vez(self) -> None:
        envios: list[tuple[int, int, int]] = []
        teclado: list[tuple[int, int, int]] = []
        restauracoes: list[bool] = []
        recebeu = threading.Event()

        def enviar(*cor: int) -> None:
            envios.append(cor)
            recebeu.set()

        capturador = CapturadorFalso()
        modo = ModoAmbilight(
            enviar,
            saida_secundaria=lambda *cor: teclado.append(cor),
            capturador=capturador,
            capture_fps=60,
            lamp_fps=20,
        )
        modo.definir_restauracao(lambda: restauracoes.append(True))
        modo.iniciar()
        self.assertTrue(recebeu.wait(1))
        time.sleep(0.12)
        self.assertTrue(modo.status()["janela"])
        self.assertGreater(capturador.capturas, 1)
        self.assertGreaterEqual(len(envios), 1)
        self.assertGreaterEqual(len(teclado), 1)
        self.assertEqual(modo.status()["teclado"], "conectado")

        modo.parar()
        modo.parar()
        self.assertFalse(modo.ativo)
        self.assertEqual(restauracoes, [True])


if __name__ == "__main__":
    unittest.main()
