import unittest

from abajur_wifi import ComandoAbajur, interpretar_comandos_abajur
from main import normalizar_texto


class ComandosRitmoTests(unittest.TestCase):
    def test_animacao_musical_sem_repetir_alvo(self) -> None:
        self.assertEqual(
            interpretar_comandos_abajur(normalizar_texto("ative a animação musical")),
            [ComandoAbajur("musica_pc")],
        )
        self.assertEqual(
            interpretar_comandos_abajur(normalizar_texto("desative a animação musical")),
            [ComandoAbajur("musica_parar")],
        )

    def test_gelada_e_ritimo_do_navegador_formam_comando_composto(self) -> None:
        self.assertEqual(
            interpretar_comandos_abajur(normalizar_texto(
                "deixe a luz do abajur um pouco mais gelada, e deixe no ritimo do navegador"
            )),
            [
                ComandoAbajur("temperatura", "fria"),
                ComandoAbajur("musica_pc"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
