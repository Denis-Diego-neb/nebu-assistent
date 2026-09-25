import unittest
from unittest.mock import Mock

from core.dispatcher import Dispatcher
from core.registry import Registry
from modules.desktop.actions import AcoesDesktop, registrar_tools_desktop
from modules.desktop.media import MIDIA_TOOL_NAMES, AcoesMidia, registrar_tools_midia
from modules.racing.modes import (
    MODOS_CORRIDA_TOOL_NAMES,
    AcoesModosCorrida,
    registrar_tools_modos_corrida,
)


class RacingToolsTests(unittest.TestCase):
    def test_registra_e_executa_os_seis_comandos_diretamente(self) -> None:
        callbacks = [Mock() for _ in range(6)]
        registry = Registry()
        registrar_tools_modos_corrida(
            registry,
            AcoesModosCorrida(*callbacks),
            obter_ultima_mensagem=lambda: "telemetria pronta",
            aguardando_resposta=lambda: False,
        )
        dispatcher = Dispatcher(registry)
        self.assertEqual(
            {item["name"] for item in dispatcher.list_tools()},
            MODOS_CORRIDA_TOOL_NAMES,
        )
        result = dispatcher.call_tool({
            "name": "modo_boost_status", "arguments": {"argumento": ""},
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "telemetria pronta")
        callbacks[-1].assert_called_once_with()

    def test_nao_executa_com_argumento_ou_confirmacao_pendente(self) -> None:
        callback = Mock()
        registry = Registry()
        registrar_tools_modos_corrida(
            registry,
            AcoesModosCorrida(*(callback for _ in range(6))),
            obter_ultima_mensagem=lambda: "",
            aguardando_resposta=lambda: True,
        )
        dispatcher = Dispatcher(registry)
        with self.assertRaises(ValueError):
            dispatcher.call_tool({
                "name": "modo_rpm_iniciar", "arguments": {"argumento": "agora"},
            })
        result = dispatcher.call_tool({
            "name": "modo_rpm_iniciar", "arguments": {"argumento": ""},
        })
        self.assertFalse(result["ok"])
        callback.assert_not_called()


class DesktopToolsTests(unittest.TestCase):
    def test_normaliza_aplicativo_e_preserva_texto_da_nota(self) -> None:
        abrir = Mock()
        nota = Mock()
        registry = Registry()
        registrar_tools_desktop(
            registry,
            AcoesDesktop(abrir, Mock(), Mock(), Mock(), Mock(), nota),
            obter_ultima_mensagem=lambda: "feito",
            aguardando_resposta=lambda: False,
        )
        dispatcher = Dispatcher(registry)
        dispatcher.call_tool({
            "name": "abrir_aplicativo", "arguments": {"argumento": "  Steam  "},
        })
        dispatcher.call_tool({
            "name": "criar_nota", "arguments": {"argumento": "  Ligar para Ana  "},
        })
        abrir.assert_called_once_with("steam")
        nota.assert_called_once_with("Ligar para Ana")

    def test_rejeita_argumento_extra_e_limite(self) -> None:
        registry = Registry()
        callbacks = AcoesDesktop(*(Mock() for _ in range(6)))
        registrar_tools_desktop(
            registry,
            callbacks,
            obter_ultima_mensagem=lambda: "",
            aguardando_resposta=lambda: False,
        )
        dispatcher = Dispatcher(registry)
        for arguments in (
            {"argumento": "", "extra": True},
            {"argumento": "x" * 501},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                dispatcher.call_tool({"name": "pesquisar_google", "arguments": arguments})


class MediaToolsTests(unittest.TestCase):
    def test_registra_e_repassa_falha_do_volume(self) -> None:
        pausar = Mock(return_value=True)
        aumentar = Mock(return_value=False)
        registry = Registry()
        registrar_tools_midia(
            registry,
            AcoesMidia(pausar, Mock(), aumentar, Mock()),
            obter_ultima_mensagem=lambda: "sem youtube",
            aguardando_resposta=lambda: False,
        )
        dispatcher = Dispatcher(registry)
        self.assertEqual(
            {item["name"] for item in dispatcher.list_tools()}, MIDIA_TOOL_NAMES,
        )
        self.assertTrue(dispatcher.call_tool({
            "name": "pausar_midia", "arguments": {"argumento": ""},
        })["ok"])
        result = dispatcher.call_tool({
            "name": "aumentar_volume", "arguments": {"argumento": ""},
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "sem youtube")
        pausar.assert_called_once_with()
        aumentar.assert_called_once_with()

    def test_nao_executa_com_argumento_ou_confirmacao_pendente(self) -> None:
        callback = Mock()
        registry = Registry()
        registrar_tools_midia(
            registry,
            AcoesMidia(*(callback for _ in range(4))),
            obter_ultima_mensagem=lambda: "",
            aguardando_resposta=lambda: True,
        )
        dispatcher = Dispatcher(registry)
        with self.assertRaises(ValueError):
            dispatcher.call_tool({
                "name": "diminuir_volume", "arguments": {"argumento": "10"},
            })
        result = dispatcher.call_tool({
            "name": "continuar_midia", "arguments": {"argumento": ""},
        })
        self.assertTrue(result["requires_confirmation"])
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
