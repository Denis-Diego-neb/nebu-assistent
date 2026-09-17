import random
import threading
import unittest
from unittest.mock import patch

from abajur_wifi import ControleAbajurElgin, interpretar_comandos_abajur
from abajur_tuya import _AnimacaoTochaTuya
from animacao_tocha import AnimacaoTochaADB, GeradorTocha
from conversa_local import AcaoQwen, ConversaLocal
from main import Nebula
from ritmo_navegador import calcular_nivel_pulso, INTENSIDADE_RITMO_PADRAO


class SaidaColetora:
    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def falar(self, texto: str) -> None:
        self.mensagens.append(texto)


class ControleAnimacoesFalso:
    def __init__(self) -> None:
        self.intensidade = 50
        self.tocha_ativa = False

    def definir_intensidade_ritmo(self, percentual: int) -> int:
        self.intensidade = percentual
        return percentual

    def ajustar_intensidade_ritmo(self, variacao: int) -> int:
        self.intensidade = max(1, min(100, self.intensidade + variacao))
        return self.intensidade

    def iniciar_modo_tocha(self) -> None:
        self.tocha_ativa = True

    def parar_modo_tocha(self) -> None:
        self.tocha_ativa = False


class EntradaFalsa:
    def __init__(self) -> None:
        self.escritas: list[str] = []

    def write(self, texto: str) -> None:
        self.escritas.append(texto)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class ProcessoFalso:
    def __init__(self) -> None:
        self.stdin = EntradaFalsa()
        self.encerrado = False

    def poll(self) -> int | None:
        return 0 if self.encerrado else None

    def wait(self, timeout: float) -> int:
        self.encerrado = True
        return 0

    def terminate(self) -> None:
        self.encerrado = True


class ControleADBFalso:
    adb = "adb-falso"
    _largura = 1080
    _altura = 2400

    def __init__(self) -> None:
        self.eventos: list[object] = []

    def _preparar(self, cancelar: threading.Event | None = None) -> None:
        self.eventos.append("preparar")

    def _abrir_painel_ritmo(self, cancelar: threading.Event | None = None) -> None:
        self.eventos.append("painel")

    def _aguardar_cancelavel(
        self, segundos: float, cancelar: threading.Event | None = None
    ) -> None:
        self.eventos.append(("aguardar", segundos))

    def _toque(self, x: int, y: int) -> None:
        self.eventos.append(("toque", x, y))


class AnimacoesLuzTests(unittest.TestCase):
    def test_parser_separa_intensidade_do_pulso_do_brilho_da_luz(self) -> None:
        self.assertEqual(
            [(acao.acao, acao.valor) for acao in interpretar_comandos_abajur(
                "aumente a intensidade do pulso"
            )],
            [("intensidade_ritmo_relativa", 20)],
        )
        self.assertEqual(
            [(acao.acao, acao.valor) for acao in interpretar_comandos_abajur(
                "coloque a intensidade da animacao em 90%"
            )],
            [("intensidade_ritmo", 90)],
        )
        self.assertEqual(
            [(acao.acao, acao.valor) for acao in interpretar_comandos_abajur(
                "coloque a intensidade da luz em 40%"
            )],
            [("brilho", 40)],
        )

    def test_intensidade_alta_aumenta_contraste_sem_sair_da_faixa(self) -> None:
        vale_normal = calcular_nivel_pulso(0.1, 0.5, 50)
        vale_forte = calcular_nivel_pulso(0.1, 0.5, 90)
        pico_normal = calcular_nivel_pulso(1.0, 0.5, 50)
        pico_forte = calcular_nivel_pulso(1.0, 0.5, 90)
        self.assertLess(vale_forte, vale_normal)
        self.assertGreater(pico_forte, pico_normal)
        self.assertTrue(0.01 <= vale_forte <= 1.0)
        self.assertTrue(0.01 <= pico_forte <= 1.0)

    def test_intensidade_pode_mudar_enquanto_o_controlador_existe(self) -> None:
        controle = ControleAbajurElgin(adb="adb-falso")
        self.assertEqual(controle._intensidade_ritmo, INTENSIDADE_RITMO_PADRAO)
        self.assertEqual(controle.definir_intensidade_ritmo(90), 90)
        self.assertEqual(controle.ajustar_intensidade_ritmo(-20), 70)
        self.assertEqual(controle.ajustar_intensidade_ritmo(80), 100)

    def test_qwen_valida_intensidade_e_tocha_na_allowlist(self) -> None:
        self.assertEqual(
            ConversaLocal._validar_acao({
                "acao": "abajur_musica_intensidade", "argumento": "90",
            }),
            AcaoQwen("abajur_musica_intensidade", "90"),
        )
        self.assertEqual(
            ConversaLocal._validar_acao({
                "acao": "abajur_tocha_iniciar", "argumento": "",
            }),
            AcaoQwen("abajur_tocha_iniciar"),
        )
        with self.assertRaises(RuntimeError):
            ConversaLocal._validar_acao({
                "acao": "abajur_musica_intensidade", "argumento": "101",
            })

    def test_executor_ajusta_intensidade_e_controla_tocha(self) -> None:
        saida = SaidaColetora()
        nebula = Nebula(saida, abrir_navegador=False)
        controle = ControleAnimacoesFalso()
        nebula._controle_abajur = controle  # type: ignore[assignment]

        self.assertTrue(nebula._executar_comando_abajur("aumente a intensidade do pulso"))
        self.assertEqual(controle.intensidade, 70)
        self.assertIn("70 por cento", saida.mensagens[-1])

        self.assertTrue(nebula._executar_comando_abajur("ative o modo tocha"))
        self.assertTrue(controle.tocha_ativa)
        self.assertTrue(nebula._executar_comando_abajur("pare o modo tocha"))
        self.assertFalse(controle.tocha_ativa)

    def test_gerador_tocha_fica_no_laranja_e_varia_brilho(self) -> None:
        gerador = GeradorTocha(random.Random(7))
        quadros = [gerador.proximo() for _ in range(500)]
        self.assertTrue(all(0.002 <= quadro.matiz <= 0.105 for quadro in quadros))
        self.assertTrue(all(0.72 <= quadro.saturacao <= 1.0 for quadro in quadros))
        self.assertTrue(all(0.40 <= quadro.brilho <= 1.0 for quadro in quadros))
        matizes = [quadro.matiz for quadro in quadros]
        self.assertGreater(sum(0.025 <= matiz <= 0.095 for matiz in matizes), 400)
        self.assertTrue(any(matiz < 0.04 for matiz in matizes))
        brilhos = [quadro.brilho for quadro in quadros]
        self.assertGreater(max(brilhos) - min(brilhos), 0.25)

    def test_tocha_adb_prepara_cor_e_envia_hsv_limitado(self) -> None:
        controle = ControleADBFalso()
        processo = ProcessoFalso()
        animacao = AnimacaoTochaADB(controle)
        animacao._INTERVALO = 10
        with patch("animacao_tocha.subprocess.Popen", return_value=processo):
            animacao.iniciar()
            animacao.parar()

        self.assertEqual(controle.eventos[:3], ["preparar", "painel", ("toque", 440, 305)])
        comandos = [linha for linha in processo.stdin.escritas if linha.startswith("input tap")]
        self.assertEqual(len(comandos), 3)
        self.assertEqual(animacao.quadros_enviados, 1)

    def test_tocha_tuya_envia_variacoes_hsv_pela_lan(self) -> None:
        class ControleTuyaFalso:
            def __init__(self) -> None:
                self.envios: list[tuple[float, float, float]] = []
                self.variou = threading.Event()

            def _enviar_hsv_ritmo(self, h: float, s: float, v: float) -> None:
                self.envios.append((h, s, v))
                if len(self.envios) >= 3:
                    self.variou.set()

        controle = ControleTuyaFalso()
        animacao = _AnimacaoTochaTuya(controle)  # type: ignore[arg-type]
        animacao._INTERVALO = 0.001
        animacao.iniciar()
        self.assertTrue(controle.variou.wait(1))
        animacao.parar()

        self.assertIsNone(animacao.erro)
        self.assertTrue(all(0.002 <= h <= 0.105 for h, _, _ in controle.envios))
        self.assertTrue(all(0.72 <= s <= 1.0 for _, s, _ in controle.envios))
        self.assertTrue(all(0.40 <= v <= 1.0 for _, _, v in controle.envios))


if __name__ == "__main__":
    unittest.main()
