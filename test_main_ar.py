import io
import json
import os
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError

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


@patch.dict(os.environ, {"NEBULA_POWER_TOKEN": "token-de-teste-com-24-caracteres"})
class TimerDoArPeloHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saida = SaidaFalsa()
        self.nebula = Nebula(self.saida, abrir_navegador=False)
        self.nebula._controle_ar = Mock()

    def test_timer_falado_vai_ao_hub_com_token(self) -> None:
        resposta = MagicMock()
        resposta.__enter__.return_value.read.return_value = b'{"ok": true}'
        with patch("main.urlopen", return_value=resposta) as urlopen:
            self.nebula.executar("desliga o ar em 10 minutos")
        pedido = urlopen.call_args.args[0]
        self.assertTrue(pedido.full_url.endswith("/control"))
        self.assertEqual(json.loads(pedido.data), {"action": "air.timer", "value": 10})
        self.assertEqual(pedido.get_header("X-nebula-power-token"), "token-de-teste-com-24-caracteres")
        self.nebula._controle_ar.executar.assert_not_called()
        self.assertIn("desliga o ar em 10 minutos", self.saida.mensagens[-1])

    def test_tenta_o_proximo_endereco_e_fala_a_recusa_do_hub(self) -> None:
        recusa = HTTPError("http://hub/control", 400, "Bad Request", {},
                           io.BytesIO('{"error": "Escolha de 1 minuto a 24 horas; zero cancela."}'.encode()))
        with patch("main.urlopen", side_effect=[URLError("offline"), recusa]) as urlopen:
            self.nebula.executar("desliga o ar em 10 minutos")
        self.assertEqual(urlopen.call_count, 2)
        self.assertIn("Escolha de 1 minuto a 24 horas", self.saida.mensagens[-1])

    def test_sem_token_nao_chama_o_hub(self) -> None:
        with patch.dict(os.environ, {"NEBULA_POWER_TOKEN": ""}), patch("main.urlopen") as urlopen:
            self.nebula.executar("desliga o ar em 10 minutos")
        urlopen.assert_not_called()
        self.assertIn("NEBULA_POWER_TOKEN", self.saida.mensagens[-1])


if __name__ == "__main__":
    unittest.main()
