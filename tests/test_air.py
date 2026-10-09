import unittest
from unittest.mock import Mock, call

from modules.iot.air import (
    ControleAr,
    PedidoAr,
    descrever_estado_ar,
    executar_pedidos_ar,
    interpretar_comando_ar,
)


class InterpretarComandoArTests(unittest.TestCase):
    def test_energia(self):
        for frase, ligar in (
            ("ligue o ar", True), ("Liga o ar-condicionado!", True),
            ("ligar o ar condicionado", True), ("deixe o ar ligado", True),
            ("desligue o ar", False), ("desliga o ar", False),
            ("pode desligar o ar?", False), ("Não, desligue o ar", False),
        ):
            with self.subTest(frase=frase):
                self.assertEqual(interpretar_comando_ar(frase), [PedidoAr("power", ligar)])

    def test_temperatura_absoluta_e_por_extenso(self):
        for frase, graus in (
            ("coloque o ar em 22 graus", 22), ("deixa o ar no 23", 23),
            ("ar em vinte e dois graus", 22), ("ajuste o ar para dezoito", 18),
            ("aumente o ar para 25", 25), ("coloque o ar em 22, como está?", 22),
        ):
            with self.subTest(frase=frase):
                self.assertEqual(interpretar_comando_ar(frase), [PedidoAr("temperature", graus)])

    def test_temperatura_relativa(self):
        for frase, passo in (
            ("aumente o ar", 1), ("abaixa o ar", -1), ("deixe o ar mais frio", -1),
            ("diminua a temperatura do ar", -1), ("diminui o ar dois graus", -2),
            ("aumente a temperatura do ar em 2 graus", 2),
        ):
            with self.subTest(frase=frase):
                self.assertEqual(
                    interpretar_comando_ar(frase), [PedidoAr("temperature_delta", passo)]
                )

    def test_modo_e_ventilacao(self):
        casos = (
            ("coloque o ar no modo frio", [PedidoAr("mode", "cool")]),
            ("mude o modo do ar para quente", [PedidoAr("mode", "heat")]),
            ("deixe o ar no modo secar", [PedidoAr("mode", "dry")]),
            ("ventilação do ar forte", [PedidoAr("fan", "high")]),
            ("coloque a ventilação do ar no automático", [PedidoAr("fan", "auto")]),
            ("velocidade do ar 3", [PedidoAr("fan", "high")]),
            ("diminua a ventilação do ar", [PedidoAr("fan_delta", -1)]),
            (
                "ligue o ar no modo frio em 22 graus com ventilação forte",
                [PedidoAr("mode", "cool"), PedidoAr("fan", "high"), PedidoAr("temperature", 22)],
            ),
        )
        for frase, esperado in casos:
            with self.subTest(frase=frase):
                self.assertEqual(interpretar_comando_ar(frase), esperado)

    def test_perguntas_nao_enviam_comando(self):
        for frase in ("o ar está ligado?", "como está o ar", "qual a temperatura do ar", "o ar está em 22?"):
            with self.subTest(frase=frase):
                self.assertEqual(interpretar_comando_ar(frase), [PedidoAr("status")])

    def test_frases_que_nao_sao_para_o_ar(self):
        for frase in (
            "desligue o pc", "ligue o abajur", "ligue o ar e o abajur", "tomar um ar",
            "pesquise como ligar o ar condicionado", "anote ligar o ar amanha",
            "aprenda que ar gelado significa modo frio", "ar no modo turbo",
            # O timer existe só no hub: horário não vira temperatura nem
            # desligamento imediato.
            "desligue o ar em 30 minutos", "desligue o ar às 22", "desligue o ar 22h",
        ):
            with self.subTest(frase=frase):
                self.assertIsNone(interpretar_comando_ar(frase))


class ExecutarPedidosArTests(unittest.TestCase):
    def setUp(self):
        self.controle = Mock(spec=ControleAr)
        self.controle.estado.return_value = {
            "available": True, "power": True, "temperature": 22, "temperature_min": 17,
            "mode": "cool", "fan": "medium",
            "supported_actions": ["power", "temperature", "mode", "fan"],
        }

    def test_frase_chega_ao_driver(self):
        resultado = executar_pedidos_ar(interpretar_comando_ar("desligue o ar"), self.controle)
        self.controle.executar.assert_called_once_with("power", False)
        self.assertEqual(resultado.mensagem, "Mandei desligar o ar.")
        self.assertFalse(resultado.falhou)

    def test_relativos_partem_do_estado_e_respeitam_limites(self):
        casos = (
            (PedidoAr("temperature_delta", 2), call("temperature", 24)),
            (PedidoAr("temperature_delta", -9), call("temperature", 17)),
            (PedidoAr("fan_delta", 1), call("fan", "high")),
            (PedidoAr("fan_delta", -5), call("fan", "low")),
        )
        for pedido, chamada in casos:
            with self.subTest(pedido=pedido):
                self.controle.executar.reset_mock()
                executar_pedidos_ar([pedido], self.controle)
                self.assertEqual(self.controle.executar.call_args_list, [chamada])

    def test_varios_ajustes_em_uma_resposta(self):
        resultado = executar_pedidos_ar(
            [PedidoAr("mode", "cool"), PedidoAr("fan", "high"), PedidoAr("temperature", 22)],
            self.controle,
        )
        self.assertEqual(
            resultado.mensagem, "Mandei o ar para o modo frio, ventilação forte e 22 graus."
        )

    def test_falha_informa_o_que_ja_saiu(self):
        self.controle.executar.side_effect = [None, RuntimeError("O Smart IR nao respondeu.")]
        resultado = executar_pedidos_ar(
            [PedidoAr("mode", "cool"), PedidoAr("temperature", 22)], self.controle
        )
        self.assertTrue(resultado.falhou)
        self.assertIn("modo frio", resultado.mensagem)
        self.assertIn("O Smart IR nao respondeu.", resultado.mensagem)

    def test_falha_sem_envio_e_faixa_invalida(self):
        for erro in (RuntimeError("sem ACK"), ValueError("A temperatura deve ficar entre 16 e 30 graus.")):
            with self.subTest(erro=erro):
                self.controle.executar.side_effect = erro
                resultado = executar_pedidos_ar([PedidoAr("temperature", 35)], self.controle)
                self.assertTrue(resultado.falhou)
                self.assertEqual(resultado.mensagem, f"Não consegui controlar o ar. {erro}")

    def test_status_nao_envia_infravermelho(self):
        resultado = executar_pedidos_ar([PedidoAr("status")], self.controle)
        self.controle.executar.assert_not_called()
        self.assertEqual(
            resultado.mensagem,
            "Pelo último comando que enviei, o ar está ligado em 22 graus, "
            "no modo frio, com ventilação média.",
        )

    def test_status_informa_a_ultima_falha(self):
        self.controle.estado.return_value = {
            "available": True, "power": False, "error": "O Smart IR nao respondeu.",
        }
        self.assertEqual(
            executar_pedidos_ar([PedidoAr("status")], self.controle).mensagem,
            "Pelo último comando que enviei, o ar está desligado. "
            "O último envio falhou: O Smart IR nao respondeu.",
        )

    def test_status_sem_configuracao(self):
        self.assertEqual(
            descrever_estado_ar({"available": False, "error": "O Smart IR ainda nao foi configurado na Nebula."}),
            "O Smart IR ainda nao foi configurado na Nebula.",
        )


if __name__ == "__main__":
    unittest.main()
