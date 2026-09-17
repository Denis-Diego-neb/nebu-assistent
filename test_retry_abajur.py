import unittest

from abajur_wifi import ErroAbajur
from main import Nebula


class SaidaTeste:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ControleFalhaUmaVez:
    def __init__(self) -> None:
        self.chamadas = 0

    def iniciar_ritmo_navegador(self, _cor=None) -> None:
        self.chamadas += 1
        if self.chamadas == 1:
            raise ErroAbajur("falha simulada")


class RetryAbajurTests(unittest.TestCase):
    def test_tente_novamente_repete_ultimo_comando_falho(self) -> None:
        saida = SaidaTeste()
        controle = ControleFalhaUmaVez()
        nebula = Nebula(saida, abrir_navegador=False)
        nebula._controle_abajur = controle  # type: ignore[assignment]

        self.assertTrue(nebula.executar("ative o modo musica do abajur"))
        self.assertEqual(controle.chamadas, 1)
        self.assertIn("falha simulada", saida.mensagens[-1])

        self.assertTrue(nebula.executar("tente novamente"))
        self.assertEqual(controle.chamadas, 2)
        self.assertIn("ritmo ativado", saida.mensagens[-1])
        self.assertIsNone(nebula._ultimo_comando_abajur_falho)


if __name__ == "__main__":
    unittest.main()
