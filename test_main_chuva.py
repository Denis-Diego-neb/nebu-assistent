import os
import unittest
from unittest.mock import Mock, patch

from main import Nebula


URL = "http://192.168.15.4:8766/hub/chuva.html?k=abcdefghijklmnopqrstuvwx"


class SaidaFalsa:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ModoChuvaNoPcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saida = SaidaFalsa()
        self.nebula = Nebula(self.saida, abrir_navegador=False)
        self.nebula._tela_chuva = Mock()
        self.teclado = Mock()
        self.modo = Mock()
        fabricas = (
            patch("main.AttackSharkX98HE", return_value=self.teclado),
            patch("main.ModoAmbilight", return_value=self.modo),
        )
        self.fabrica_teclado, self.fabrica_modo = (fabrica.start() for fabrica in fabricas)
        for fabrica in fabricas:
            self.addCleanup(fabrica.stop)

    def test_hub_abre_o_video_e_liga_o_attack_shark_na_tela(self) -> None:
        with patch.object(self.nebula, "_encerrar_modo_ambilight", wraps=self.nebula._encerrar_modo_ambilight) as ambilight:
            resposta = self.nebula.executar_controle("chuva.iniciar", {"url": URL})
        ambilight.assert_called()  # modos que seguram o abajur e o teclado são encerrados
        self.nebula._tela_chuva.abrir.assert_called_once_with(URL)
        self.assertEqual(self.fabrica_modo.call_args.kwargs["saida_secundaria"], self.teclado.enviar_rgb)
        self.modo.definir_restauracao.assert_called_once_with(self.teclado.close)
        self.modo.iniciar.assert_called_once()
        self.assertIn("Attack Shark", resposta["message"])
        self.nebula.executar_controle("chuva.parar", "")
        self.nebula._tela_chuva.fechar.assert_called_once()
        self.modo.parar.assert_called_once()

    def test_sem_attack_shark_o_video_abre_mesmo_assim(self) -> None:
        from teclado_attack_shark import AttackSharkNotFoundError

        self.fabrica_teclado.side_effect = AttackSharkNotFoundError("Nao encontrei o Attack Shark X98HE.")
        resposta = self.nebula.executar_controle("chuva.iniciar", {"url": URL})
        self.nebula._tela_chuva.abrir.assert_called_once_with(URL)
        self.assertIn("teclado de fora", resposta["message"])

    def test_so_abre_a_pagina_do_hub_da_rede_local(self) -> None:
        for url in (
            "http://8.8.8.8:8766/hub/chuva.html?k=abcdefghijklmnopqrstuvwx",
            "https://192.168.15.4:8766/hub/chuva.html?k=abcdefghijklmnopqrstuvwx",
            "http://192.168.15.4:8766/hub/hub.html?k=abcdefghijklmnopqrstuvwx",
            "http://192.168.15.4:8766/hub/chuva.html?k=curta",
            "http://192.168.15.4:8766/hub/chuva.html?k=abcdefghijklmnop&x=1",
            "javascript:alert(1)", None,
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.nebula.executar_controle("chuva.iniciar", {"url": url})
        self.nebula._tela_chuva.abrir.assert_not_called()

    def test_voz_pede_o_modo_chuva_ao_hub(self) -> None:
        with patch.object(Nebula, "_acao_no_hub", return_value={"message": "Modo chuva ativado."}) as hub:
            self.nebula.executar("ative a chuva para dormir")
            hub.assert_called_once_with("chuva.iniciar", {"origem": "pc"})
            self.nebula.executar("para o modo chuva")
            hub.assert_called_with("chuva.parar", {"origem": "pc"})
        self.assertEqual(self.saida.mensagens[0], "Modo chuva ativado.")

    @patch.dict(os.environ, {"NEBULA_QWEN_ENABLED": "1"})
    def test_qwen_ativa_nao_intercepta_o_modo_chuva(self) -> None:
        with patch.object(Nebula, "_acao_no_hub", return_value={"message": "ok"}) as hub, patch.object(
            self.nebula.conversa, "interpretar_ou_responder", side_effect=AssertionError("Qwen")
        ):
            self.nebula.executar("ative o modo chuva")
        hub.assert_called_once()

    def test_hub_fora_e_dito_em_voz(self) -> None:
        with patch.object(Nebula, "_acao_no_hub", side_effect=RuntimeError("O hub do notebook não respondeu.")):
            self.nebula.executar("ative o modo chuva")
        self.assertIn("O hub do notebook não respondeu.", self.saida.mensagens[-1])


if __name__ == "__main__":
    unittest.main()
