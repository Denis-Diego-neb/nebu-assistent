from contextlib import redirect_stdout
from io import StringIO
import os
import unittest
from unittest.mock import patch

from conversa_local import AcaoQwen, ResultadoQwen
from main import Nebula, interpretar_comando_modo_rpm


class SaidaColetora:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


@patch.dict(os.environ, {"NEBULA_QWEN_ENABLED": "1"})
class ExecutorQwenTests(unittest.TestCase):
    def test_qwen_traduz_e_nebu_executa(self) -> None:
        nebula = Nebula(SaidaColetora(), abrir_navegador=False)
        resultado = ResultadoQwen(
            "comando", (AcaoQwen("abrir_aplicativo", "Steam"),)
        )
        with (
            patch.object(
                nebula.conversa, "interpretar_ou_responder", return_value=resultado
            ) as interpretar,
            patch.object(nebula, "_abrir_aplicativo_por_nome", return_value=True) as abrir,
        ):
            nebula.executar("inicialize aquele cliente de jogos da valve")

        interpretar.assert_called_once_with("inicialize aquele cliente de jogos da valve")
        abrir.assert_called_once_with("steam")

    def test_acao_destrutiva_traduzida_preserva_confirmacao(self) -> None:
        saida = SaidaColetora()
        nebula = Nebula(saida, abrir_navegador=False)
        resultado = ResultadoQwen("comando", (AcaoQwen("desligar_pc"),))
        with patch.object(
            nebula.conversa, "interpretar_ou_responder", return_value=resultado
        ):
            nebula.executar("apague completamente esta maquina")

        self.assertEqual(nebula.comando_pendente, "confirmar_desligar_pc")
        self.assertIn("Quer mesmo desligar", saida.mensagens[-1])

    def test_falha_da_qwen_nao_parece_falta_de_sentido(self) -> None:
        saida = SaidaColetora()
        nebula = Nebula(saida, abrir_navegador=False)
        with (
            patch.object(
                nebula.conversa,
                "interpretar_ou_responder",
                side_effect=RuntimeError("JSON truncado"),
            ),
            redirect_stdout(StringIO()),
        ):
            nebula.executar("um pedido que nao existe nas regras")

        self.assertIn("Qwen no notebook não respondeu", saida.mensagens[-1])
        self.assertNotIn("sentido operacional", saida.mensagens[-1])

    def test_cor_hexadecimal_recebe_comando_canonico_valido(self) -> None:
        self.assertEqual(
            Nebula._comando_canonico_qwen(AcaoQwen("abajur_cor", "#FF1493")),
            "deixe o abajur hexadecimal FF1493",
        )

    def test_acoes_rpm_recebem_comandos_canonicos(self) -> None:
        self.assertEqual(
            Nebula._comando_canonico_qwen(AcaoQwen("modo_rpm_iniciar")),
            "ative o modo rpm",
        )
        self.assertEqual(
            Nebula._comando_canonico_qwen(AcaoQwen("modo_rpm_parar")),
            "pare o modo rpm",
        )
        self.assertEqual(
            Nebula._comando_canonico_qwen(AcaoQwen("modo_rpm_status")),
            "status do modo rpm",
        )

    def test_acoes_boost_recebem_comandos_canonicos(self) -> None:
        self.assertEqual(
            Nebula._comando_canonico_qwen(AcaoQwen("modo_boost_iniciar")),
            "ative o modo boost",
        )
        self.assertEqual(
            Nebula._comando_canonico_qwen(AcaoQwen("modo_boost_parar")),
            "pare o modo boost",
        )
        self.assertEqual(
            Nebula._comando_canonico_qwen(AcaoQwen("modo_boost_status")),
            "status do modo boost",
        )

    def test_comandos_diretos_do_modo_rpm(self) -> None:
        self.assertEqual(interpretar_comando_modo_rpm("ative o modo RPM"), "iniciar")
        self.assertEqual(
            interpretar_comando_modo_rpm(
                "faça as luzes acompanharem o giro do carro"
            ),
            "iniciar",
        )
        self.assertEqual(interpretar_comando_modo_rpm("pare o modo rpm"), "parar")
        self.assertEqual(interpretar_comando_modo_rpm("status do modo rpm"), "status")
        self.assertIsNone(interpretar_comando_modo_rpm("abra o jogo de corrida"))


if __name__ == "__main__":
    unittest.main()
