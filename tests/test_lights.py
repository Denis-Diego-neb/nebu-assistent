import unittest
from unittest.mock import Mock, call

from abajur_wifi import ComandoAbajur, ErroAbajur, interpretar_comandos_abajur
from modules.iot.lights import ControleAbajur, executar_pedidos_abajur


class LightsTests(unittest.TestCase):
    def setUp(self):
        self.controle = Mock(spec=ControleAbajur)
        self.obter = Mock(return_value=self.controle)

    def test_comando_falado_chega_ao_driver(self):
        resultado = executar_pedidos_abajur(
            interpretar_comandos_abajur("ligue o abajur"), self.obter
        )
        self.controle.energia.assert_called_once_with(True)
        self.assertEqual(resultado.mensagem, "Abajur ligado.")
        self.assertFalse(resultado.falhou)

    def test_acoes_e_argumentos(self):
        casos = [
            ("energia", False, call.energia(False)),
            ("cor", "azul", call.cor("azul")),
            ("temperatura", "quente", call.temperatura("quente")),
            ("brilho", 45, call.brilho(45)),
            ("brilho_relativo", -10, call.ajustar_brilho(-10)),
            ("intensidade_ritmo", 60, call.definir_intensidade_ritmo(60)),
            ("intensidade_ritmo_relativa", 10, call.ajustar_intensidade_ritmo(10)),
            ("musica_pc", None, call.iniciar_ritmo_navegador(None)),
            ("musica_pc", (1, 2, 3), call.iniciar_ritmo_navegador((1, 2, 3))),
            ("musica_parar", None, call.parar_ritmo_navegador()),
            ("tocha_iniciar", None, call.iniciar_modo_tocha()),
            ("tocha_parar", None, call.parar_modo_tocha()),
            ("salvar_cor", ("azul", "oceano"), call.salvar_cor("oceano", "azul")),
            ("salvar_cor_atual", "oceano", call.salvar_cor_atual("oceano")),
            ("usar_cor_salva", "oceano", call.usar_cor_salva("oceano")),
            ("rgb", (10, 20, 30), call.rgb(10, 20, 30)),
        ]
        for acao, valor, chamada in casos:
            with self.subTest(acao=acao, valor=valor):
                self.controle.reset_mock()
                resultado = executar_pedidos_abajur([ComandoAbajur(acao, valor)], self.obter)
                self.assertEqual(self.controle.mock_calls, [chamada])
                self.assertFalse(resultado.falhou)
                self.assertTrue(resultado.mensagem)

    def test_sem_pedidos_nao_abre_conexao(self):
        resultado = executar_pedidos_abajur([], self.obter)
        self.obter.assert_not_called()
        self.assertIsNone(resultado.mensagem)
        self.assertFalse(resultado.falhou)

    def test_falha_de_conexao(self):
        for erro in (ErroAbajur("sem chave"), OSError("sem rede")):
            with self.subTest(erro=erro):
                self.obter.side_effect = erro
                resultado = executar_pedidos_abajur([ComandoAbajur("energia", True)], self.obter)
                self.assertTrue(resultado.falhou)
                self.assertIn(str(erro), resultado.mensagem)
                self.controle.energia.assert_not_called()

    def test_falha_parcial_preserva_confirmacoes_e_interrompe_sequencia(self):
        self.controle.cor.side_effect = ErroAbajur("sem resposta")
        pedidos = [ComandoAbajur("energia", True), ComandoAbajur("cor", "azul"),
                   ComandoAbajur("brilho", 50)]
        resultado = executar_pedidos_abajur(pedidos, self.obter)
        self.assertTrue(resultado.falhou)
        self.assertEqual(self.controle.mock_calls, [call.energia(True), call.cor("azul")])
        self.assertEqual(resultado.mensagem,
                         "Consegui ajustar Abajur ligado. Não consegui concluir o controle do abajur. sem resposta")

        self.controle.cor.side_effect = None
        resultado = executar_pedidos_abajur(pedidos, self.obter)
        self.assertFalse(resultado.falhou)
        self.assertEqual(resultado.mensagem, "Ajustei Abajur ligado e cor azul e brilho em 50 por cento.")


if __name__ == "__main__":
    unittest.main()
