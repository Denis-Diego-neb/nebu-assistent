import unittest
from unittest.mock import Mock

from core.dispatcher import Dispatcher
from core.registry import Registry
from modules.iot.ambilight import (
    AMBILIGHT_TOOL_NAMES,
    AcoesAmbilight,
    registrar_tools_ambilight,
    selecionar_saidas_teclado,
)


class TecladoFalso:
    def __init__(self, multizona: bool) -> None:
        self.ambilight_multizona_seguro = multizona
        self.cores = []
        self.zonas = []

    def enviar_rgb(self, red, green, blue) -> None:
        self.cores.append((red, green, blue))

    def enviar_zonas(self, colors) -> None:
        self.zonas.append(colors)


class SaidasTecladoTests(unittest.TestCase):
    def test_driver_nao_atomico_usa_cor_uniforme(self) -> None:
        teclado = TecladoFalso(multizona=False)
        saidas = selecionar_saidas_teclado(teclado)
        self.assertIsNone(saidas.zonas)
        self.assertFalse(saidas.multizona)
        saidas.secundaria(10, 20, 30)
        self.assertEqual(teclado.cores, [(10, 20, 30)])

    def test_driver_multizona_seguro_preserva_zonas(self) -> None:
        teclado = TecladoFalso(multizona=True)
        saidas = selecionar_saidas_teclado(teclado)
        self.assertIsNone(saidas.secundaria)
        self.assertTrue(saidas.multizona)
        saidas.zonas([(10, 20, 30)])
        self.assertEqual(teclado.zonas, [[(10, 20, 30)]])


class RegistroAmbilightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = Registry()
        self.iniciar = Mock()
        self.parar = Mock()
        self.status = Mock()
        self.pending = False
        registrar_tools_ambilight(
            self.registry,
            AcoesAmbilight(self.iniciar, self.parar, self.status),
            obter_ultima_mensagem=lambda: "resposta do modo",
            aguardando_resposta=lambda: self.pending,
        )
        self.dispatcher = Dispatcher(self.registry)

    def test_registra_as_tres_tools_com_chamadas_diretas(self) -> None:
        names = {tool["name"] for tool in self.dispatcher.list_tools()}
        self.assertEqual(names, AMBILIGHT_TOOL_NAMES)
        result = self.dispatcher.call_tool({
            "name": "modo_ambilight_iniciar",
            "arguments": {"argumento": ""},
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "resposta do modo")
        self.iniciar.assert_called_once_with()
        self.parar.assert_not_called()
        self.status.assert_not_called()

    def test_rejeita_argumento_e_respeita_confirmacao_pendente(self) -> None:
        with self.assertRaises(ValueError):
            self.dispatcher.call_tool({
                "name": "modo_ambilight_status",
                "arguments": {"argumento": "agora"},
            })
        self.pending = True
        result = self.dispatcher.call_tool({
            "name": "modo_ambilight_parar",
            "arguments": {"argumento": ""},
        })
        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_confirmation"])
        self.parar.assert_not_called()

    def test_propaga_falha_do_executor_tipado(self) -> None:
        self.iniciar.return_value = False
        result = self.dispatcher.call_tool({
            "name": "modo_ambilight_iniciar",
            "arguments": {"argumento": ""},
        })
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
