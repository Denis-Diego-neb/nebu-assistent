import io
import threading
import unittest
from unittest.mock import Mock
import wave

from modo_chuva import (
    TelaChuva, ar_ligado_no_ciclo, extrair_video_id, gerar_trovoes, sintetizar_trovao,
)


class ModoChuvaTests(unittest.TestCase):
    def test_trovoes_deterministicos_espacados_e_com_luz_antes_do_som(self):
        oito_horas = gerar_trovoes(7, 0.0, 8 * 3600)
        self.assertEqual(gerar_trovoes(7, 0.0, 3600), [t for t in oito_horas if t.instante <= 3600])
        self.assertNotEqual(gerar_trovoes(8, 0.0, 3600), gerar_trovoes(7, 0.0, 3600))
        self.assertTrue(60 <= oito_horas[0].instante <= 150)
        for anterior, seguinte in zip(oito_horas, oito_horas[1:]):
            self.assertTrue(90 <= seguinte.instante - anterior.instante <= 420)
        for trovao in oito_horas:
            self.assertTrue(0.4 <= trovao.atraso_som <= 3.2)
            self.assertTrue(0.4 <= trovao.intensidade <= 1.0)
            self.assertTrue(trovao.flashes[0][1])
            self.assertEqual(trovao.flashes[-1], (0.0, False))

    def test_ciclo_do_ar_comeca_ligado(self):
        self.assertEqual(
            [ar_ligado_no_ciclo(0, t) for t in (0, 3599, 3600, 7199, 7200)],
            [True, True, False, False, True],
        )

    def test_extrai_id_do_youtube(self):
        for texto in ("abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk&t=3",
                      "https://youtu.be/abcdefghijk?si=x", "https://www.youtube.com/shorts/abcdefghijk"):
            with self.subTest(texto=texto):
                self.assertEqual(extrair_video_id(texto), "abcdefghijk")
        for texto in ("chuva forte", "", None, "https://www.youtube.com/watch?v=abcdefghijkl"):
            with self.subTest(texto=texto):
                self.assertIsNone(extrair_video_id(texto))

    def test_trovao_sintetizado_e_wav_valido_e_repetivel(self):
        dados = sintetizar_trovao(3, 0.9)
        self.assertEqual(dados, sintetizar_trovao(3, 0.9))
        with wave.open(io.BytesIO(dados)) as arquivo:
            self.assertEqual((arquivo.getnchannels(), arquivo.getsampwidth()), (1, 2))
            self.assertAlmostEqual(arquivo.getnframes() / arquivo.getframerate(), 6.6, places=1)

    def test_tela_segura_a_maquina_acordada_ate_fechar(self):
        processo = Mock()
        chamadas: list[bool] = []
        desligou = threading.Event()

        def acordado(ativo: bool) -> None:
            chamadas.append(ativo)
            if not ativo:
                desligou.set()

        tela = TelaChuva(abrir=Mock(return_value=processo), acordado=acordado)
        tela.abrir("http://127.0.0.1:8766/hub/chuva.html?k=x")
        self.assertTrue(tela.ativa)
        tela.fechar()
        self.assertTrue(desligou.wait(2))
        processo.terminate.assert_called_once()
        self.assertEqual((chamadas[0], chamadas[-1]), (True, False))
        self.assertFalse(tela.ativa)


if __name__ == "__main__":
    unittest.main()
