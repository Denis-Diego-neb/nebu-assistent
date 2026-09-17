from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ar_ekaza import ControleArEkaza, _bounds, _fan_codigo, _modo_codigo, _normalizar


class ArEkazaHelpersTests(unittest.TestCase):
    def test_normaliza_rotulos_reais_do_ekaza(self) -> None:
        self.assertEqual(_modo_codigo("modo: Ar Frio"), "cool")
        self.assertEqual(_modo_codigo("modo: Desumidificação"), "dry")
        self.assertEqual(_fan_codigo("Velocidade: Médio"), "medium")
        self.assertEqual(_normalizar("Fornecer ar"), "fornecer ar")

    def test_bounds(self) -> None:
        self.assertEqual(_bounds("[10,20][110,220]"), (10, 20, 110, 220))
        self.assertIsNone(_bounds("invalido"))

    def test_estado_persistido_nao_expoe_dados_do_adb(self) -> None:
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "ar.json"
            controle = ControleArEkaza(caminho, adb="adb-falso")
            controle._state.update({"power": True, "temperature": 23, "mode": "dry", "fan": "low"})
            controle._salvar()
            outro = ControleArEkaza(caminho, adb="adb-falso")
            estado = outro.estado()
            self.assertTrue(estado["power"])
            self.assertEqual(estado["temperature"], 23)
            self.assertEqual(estado["mode_label"], "Desumidificacao")
            self.assertNotIn("adb", caminho.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
