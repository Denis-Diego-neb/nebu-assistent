import os
import unittest
from unittest.mock import Mock, patch

from main import Nebula


class SaidaFalsa:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ComandoArPorVozTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saida = SaidaFalsa()
        self.nebula = Nebula(self.saida, abrir_navegador=False)
        self.ar = Mock()
        self.ar.estado.return_value = {"temperature": 22, "temperature_min": 16, "fan": "auto"}
        self.nebula._controle_ar = self.ar

    def test_desligue_o_ar_nao_vira_desligamento_do_pc(self) -> None:
        with patch("main.subprocess.Popen") as popen:
            self.nebula.executar("desligue o ar")
        self.ar.executar.assert_called_once_with("power", False)
        self.assertIsNone(self.nebula.comando_pendente)
        self.assertEqual(self.saida.mensagens[-1], "Mandei desligar o ar.")
        popen.assert_not_called()

    def test_temperatura_falada_chega_ao_smart_ir(self) -> None:
        self.nebula.executar("coloque o ar em vinte e dois graus")
        self.ar.executar.assert_called_once_with("temperature", 22)

    @patch.dict(os.environ, {"NEBULA_QWEN_ENABLED": "1"})
    def test_qwen_ativa_nao_intercepta_o_ar(self) -> None:
        with patch.object(
            self.nebula.conversa, "interpretar_ou_responder", side_effect=AssertionError("Qwen")
        ):
            self.nebula.executar("liga o ar")
        self.ar.executar.assert_called_once_with("power", True)

    def test_falha_do_smart_ir_e_falada(self) -> None:
        self.ar.executar.side_effect = RuntimeError(
            "O Smart IR nao respondeu. Confirme se ele esta ligado no Wi-Fi."
        )
        self.nebula.executar("ligue o ar")
        self.assertIn("O Smart IR nao respondeu", self.saida.mensagens[-1])

    def test_pedido_ao_ar_cancela_confirmacao_do_pc(self) -> None:
        self.nebula.comando_pendente = "confirmar_desligar_pc"
        with patch("main.subprocess.Popen") as popen:
            self.nebula.executar("não, desligue o ar")
        popen.assert_not_called()
        self.ar.executar.assert_called_once_with("power", False)
        self.assertIsNone(self.nebula.comando_pendente)
        self.assertIn("desligamento do PC foi cancelado", self.saida.mensagens[-1])

    def test_nao_desligue_cancela_o_desligamento_do_pc(self) -> None:
        self.nebula.comando_pendente = "confirmar_desligar_pc"
        with patch("main.subprocess.Popen") as popen, patch("builtins.print"):
            self.nebula.executar("não desligue")
        popen.assert_not_called()
        self.assertIsNone(self.nebula.comando_pendente)
        self.assertIn("cancelado", self.saida.mensagens[-1])

    def test_texto_de_nota_nao_e_pedido_ao_ar(self) -> None:
        self.nebula.comando_pendente = "texto_bloco_notas"
        with patch.object(self.nebula, "_escrever_no_bloco_de_notas", return_value=True) as nota:
            self.nebula.executar("ligar o ar do quarto")
        nota.assert_called_once()
        self.ar.executar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
