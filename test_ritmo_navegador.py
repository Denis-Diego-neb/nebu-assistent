import math
from queue import Empty
import random
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from abajur_wifi import ControleAbajurElgin, ErroAbajur
from ritmo_navegador import (
    DetectorRitmoMusical,
    ERRO_ENCERRAMENTO,
    ERRO_INICIALIZACAO,
    ERRO_TIMEOUT_INICIALIZACAO,
    ETAPA_AUDIO,
    ETAPA_PAINEL,
    ETAPA_SHELL,
    RitmoNavegador,
    atividade_indica_musica,
    classificar_titulos_navegador,
)


class ControleFalso:
    adb = "adb-falso"
    _largura = 1080
    _altura = 2400
    _modo_ativo = "white"

    def __init__(self, eventos: list[str]) -> None:
        self.eventos = eventos

    def _preparar(self, cancelar: threading.Event | None = None) -> None:
        self.eventos.append("preparar")

    def _abrir_painel_ritmo(self, cancelar: threading.Event | None = None) -> None:
        self.eventos.append("abrir_painel")

    def _aguardar_cancelavel(
        self,
        segundos: float,
        cancelar: threading.Event | None = None,
    ) -> None:
        self.eventos.append(f"aguardar:{segundos}")

    def _toque(self, x: int, y: int) -> None:
        self.eventos.append(f"toque:{x},{y}")


class EntradaFalsa:
    def __init__(self) -> None:
        self.escritas: list[str] = []

    def write(self, texto: str) -> None:
        self.escritas.append(texto)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class ProcessoFalso:
    def __init__(self, encerrado: bool = False) -> None:
        self.stdin = EntradaFalsa()
        self.encerrado = encerrado

    def poll(self) -> int | None:
        return 1 if self.encerrado else None

    def wait(self, timeout: float) -> int:
        return 0

    def terminate(self) -> None:
        self.encerrado = True


class RitmoNavegadorTests(unittest.TestCase):
    @staticmethod
    def detector_com_pulso() -> DetectorRitmoMusical:
        detector = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
        for indice in range(60):
            fase = indice % 5
            detector.adicionar(0.75 * math.exp(-fase / 1.4) + 0.02)
        return detector

    def test_titulo_musical_tem_prioridade_sobre_janela_de_fala(self) -> None:
        self.assertIs(
            classificar_titulos_navegador([
                "WhatsApp - Brave",
                "Minha faixa - Official Audio - YouTube",
            ]),
            True,
        )

    def test_titulo_de_outra_aba_nao_veta_detector_de_ritmo(self) -> None:
        detector = self.detector_com_pulso()
        self.assertTrue(detector.parece_musica())
        self.assertTrue(atividade_indica_musica(False, detector))

    def test_titulo_positivo_antecipa_janela_de_amostras(self) -> None:
        detector = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
        self.assertFalse(detector.parece_musica())
        self.assertTrue(atividade_indica_musica(True, detector))

    def test_sem_titulo_ou_ritmo_permanece_inativo(self) -> None:
        detector = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
        for _ in range(60):
            detector.adicionar(0)
        self.assertFalse(atividade_indica_musica(None, detector))
        self.assertFalse(atividade_indica_musica(False, detector))

    def test_envelope_realista_do_brave_passa_com_correlacao_moderada(self) -> None:
        aleatorio = random.Random(123)
        brutos = [
            0.14 * math.exp(-(indice % 5) / 1.5)
            + 0.02
            + 0.75 * (aleatorio.random() - 0.5)
            for indice in range(60)
        ]
        minimo, maximo = min(brutos), max(brutos)
        detector = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
        for bruto in brutos:
            # Faixa observada na sessão Brave, preservando a correlação ~0,253.
            detector.adicionar(0.086 + 0.061 * (bruto - minimo) / (maximo - minimo))

        self.assertTrue(detector.parece_musica())

    def test_ritmo_baixo_tambem_e_detectado(self) -> None:
        detector = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
        for indice in range(60):
            fase = indice % 5
            detector.adicionar(0.018 * math.exp(-fase / 1.4) + 0.002)

        self.assertTrue(detector.parece_musica())

    def test_iniciar_aguarda_audio_e_shell_sem_sleeps_reais(self) -> None:
        eventos: list[str] = []
        controle = ControleFalso(eventos)
        ritmo = RitmoNavegador(controle)
        processo = ProcessoFalso()
        pulso_lido = threading.Event()

        class MedidorFalso:
            def __init__(self) -> None:
                eventos.append("medidor")
                self.chamadas = 0

            def pico(self) -> float:
                self.chamadas += 1
                eventos.append("pico")
                if self.chamadas > 1:
                    pulso_lido.set()
                return 0.2

        comtypes_falso = SimpleNamespace(
            CoInitialize=lambda: eventos.append("com_iniciar"),
            CoUninitialize=lambda: eventos.append("com_encerrar"),
        )

        def abrir_shell(*_args, **_kwargs) -> ProcessoFalso:
            eventos.append("shell")
            return processo

        with (
            patch.dict(sys.modules, {"comtypes": comtypes_falso}),
            patch("ritmo_navegador.MedidorNavegador", MedidorFalso),
            patch("ritmo_navegador.subprocess.Popen", side_effect=abrir_shell),
            patch("ritmo_navegador.titulo_navegador_indica_musica", return_value=True),
            patch("ritmo_navegador.time.sleep"),
        ):
            ritmo.iniciar(timeout=1)
            self.assertTrue(pulso_lido.wait(1))
            ritmo.parar()

        self.assertTrue(ritmo.pronto)
        self.assertLess(eventos.index("pico"), eventos.index("preparar"))
        self.assertLess(eventos.index("preparar"), eventos.index("abrir_painel"))
        self.assertLess(eventos.index("abrir_painel"), eventos.index("shell"))
        self.assertEqual(eventos.count("preparar"), 1)
        self.assertIn("toque:220,305", eventos)
        comandos_pulso = [
            comando for comando in processo.stdin.escritas if comando.startswith("input tap")
        ]
        self.assertTrue(comandos_pulso)
        self.assertTrue(all(comando.rstrip().endswith(" 1645") for comando in comandos_pulso))
        self.assertIn("exit\n", processo.stdin.escritas)

    def test_modo_color_padrao_pulsa_brilho_sem_tocar_no_hue(self) -> None:
        eventos: list[str] = []
        controle = ControleFalso(eventos)
        controle._modo_ativo = "color"
        ritmo = RitmoNavegador(controle)
        processo = ProcessoFalso()
        pulso_lido = threading.Event()

        class MedidorFalso:
            def __init__(self) -> None:
                self.chamadas = 0

            def pico(self) -> float:
                self.chamadas += 1
                if self.chamadas > 1:
                    pulso_lido.set()
                return 0.2

        comtypes_falso = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
        with (
            patch.dict(sys.modules, {"comtypes": comtypes_falso}),
            patch("ritmo_navegador.MedidorNavegador", MedidorFalso),
            patch("ritmo_navegador.subprocess.Popen", return_value=processo),
            patch("ritmo_navegador.titulo_navegador_indica_musica", return_value=True),
        ):
            ritmo.iniciar(timeout=1)
            self.assertTrue(pulso_lido.wait(1))
            ritmo.parar(timeout=1)

        self.assertEqual(
            [evento for evento in eventos if evento.startswith("toque:")],
            ["toque:440,305"],
        )
        comandos_pulso = [
            comando for comando in processo.stdin.escritas if comando.startswith("input tap")
        ]
        self.assertTrue(comandos_pulso)
        self.assertTrue(all(comando.rstrip().endswith(" 1540") for comando in comandos_pulso))

    def test_falha_do_medidor_e_propagada_antes_de_tocar_lampada(self) -> None:
        eventos: list[str] = []
        ritmo = RitmoNavegador(ControleFalso(eventos))

        class MedidorComFalha:
            def pico(self) -> float:
                raise OSError("detalhe interno que não deve ir ao chamador")

        comtypes_falso = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
        with (
            patch.dict(sys.modules, {"comtypes": comtypes_falso}),
            patch("ritmo_navegador.MedidorNavegador", MedidorComFalha),
            patch("ritmo_navegador.subprocess.Popen") as popen,
        ):
            with self.assertRaisesRegex(RuntimeError, f"^{ERRO_INICIALIZACAO}.*") as erro:
                ritmo.iniciar(timeout=1)

        self.assertIsInstance(erro.exception.__cause__, OSError)
        self.assertIn(ETAPA_AUDIO, str(erro.exception))
        self.assertEqual(eventos, [])
        popen.assert_not_called()
        self.assertFalse(ritmo.pronto)

    def test_shell_encerrado_na_inicializacao_e_falha_sincrona(self) -> None:
        eventos: list[str] = []
        ritmo = RitmoNavegador(ControleFalso(eventos))

        class MedidorFalso:
            def pico(self) -> float:
                eventos.append("pico")
                return 0.0

        comtypes_falso = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
        with (
            patch.dict(sys.modules, {"comtypes": comtypes_falso}),
            patch("ritmo_navegador.MedidorNavegador", MedidorFalso),
            patch("ritmo_navegador.subprocess.Popen", return_value=ProcessoFalso(encerrado=True)),
            patch("ritmo_navegador.time.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, f"^{ERRO_INICIALIZACAO}.*") as erro:
                ritmo.iniciar(timeout=1)

        self.assertEqual(eventos[0], "pico")
        self.assertIn(ETAPA_SHELL, str(erro.exception))
        self.assertFalse(ritmo.pronto)

    def test_timeout_cancela_inicializacao_sem_sleep_real(self) -> None:
        ritmo = RitmoNavegador(ControleFalso([]))
        ritmo._executar = ritmo._parar.wait  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, f"^{ERRO_TIMEOUT_INICIALIZACAO}.*"):
            ritmo.iniciar(timeout=0)
        self.assertTrue(ritmo._parar.is_set())
        self.assertFalse(ritmo.pronto)
        self.assertFalse(ritmo.ativo)

    def test_timeout_informa_etapa_sem_espera_real(self) -> None:
        class ProgressoFalso:
            def __init__(self) -> None:
                self.primeira = True

            def get_nowait(self) -> tuple[str, object]:
                raise Empty

            def get(self, timeout: float) -> tuple[str, object]:
                if self.primeira:
                    self.primeira = False
                    return "etapa", ETAPA_PAINEL
                raise Empty

            def put(self, item: tuple[str, object]) -> None:
                pass

        ritmo = RitmoNavegador(ControleFalso([]))
        ritmo._progresso = ProgressoFalso()  # type: ignore[assignment]
        ritmo._executar = ritmo._parar.wait  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError) as contexto:
            ritmo.iniciar(timeout=0)

        self.assertIn(ETAPA_PAINEL, str(contexto.exception))
        self.assertFalse(ritmo.ativo)

    def test_retry_so_comeca_depois_da_thread_do_timeout_encerrar(self) -> None:
        ritmo = RitmoNavegador(ControleFalso([]))
        tentativas = 0

        def executar() -> None:
            nonlocal tentativas
            tentativas += 1
            if tentativas == 1:
                ritmo._parar.wait()
                return
            ritmo._pronto.set()
            ritmo._progresso.put(("pronto", True))
            ritmo._parar.wait()

        ritmo._executar = executar  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            ritmo.iniciar(timeout=0)
        self.assertFalse(ritmo.ativo)

        ritmo.iniciar(timeout=1)
        self.assertTrue(ritmo.ativo)
        self.assertEqual(tentativas, 2)
        ritmo.parar(timeout=1)

    def test_parar_nao_oculta_thread_que_continua_viva(self) -> None:
        class ThreadPresa:
            def is_alive(self) -> bool:
                return True

            def join(self, timeout: float) -> None:
                pass

        ritmo = RitmoNavegador(ControleFalso([]))
        ritmo._thread = ThreadPresa()  # type: ignore[assignment]
        with self.assertRaisesRegex(RuntimeError, f"^{ERRO_ENCERRAMENTO}$"):
            ritmo.parar(timeout=0)

    def test_get_state_sem_dispositivo_recebe_mensagem_amigavel(self) -> None:
        controle = ControleAbajurElgin(adb="adb-falso")
        with (
            patch.object(
                controle,
                "_executar",
                side_effect=ErroAbajur("error: no devices/emulators found"),
            ),
            self.assertRaises(ErroAbajur) as contexto,
        ):
            controle._preparar()

        mensagem = str(contexto.exception).lower()
        self.assertIn("celular não está conectado", mensagem)
        self.assertNotIn("no devices", mensagem)

    def test_painel_rapido_do_ritmo_nao_consulta_xml(self) -> None:
        controle = ControleAbajurElgin(adb="adb-falso")
        with (
            patch.object(controle, "_abrir_inicio") as abrir_inicio,
            patch.object(controle, "_hierarquia") as hierarquia,
            patch.object(controle, "_toque") as toque,
            patch.object(controle, "_aguardar_cancelavel") as aguardar,
        ):
            controle._abrir_painel_ritmo()

        abrir_inicio.assert_called_once_with(None)
        hierarquia.assert_not_called()
        toque.assert_called_once_with(540, 500)
        aguardar.assert_called_once_with(3, None)

    def test_ritmo_adb_sem_modo_conhecido_pede_cor_ou_temperatura(self) -> None:
        controle = ControleAbajurElgin(adb="adb-falso")
        with (
            patch("abajur_wifi._validar_dependencias_ritmo"),
            self.assertRaises(ErroAbajur) as contexto,
        ):
            controle.iniciar_ritmo_navegador()

        mensagem = str(contexto.exception).lower()
        self.assertIn("cor ou temperatura", mensagem)
        self.assertIsNone(controle._ritmo_navegador)

    def test_wrapper_adb_nao_repete_preparacao_feita_pelo_handshake(self) -> None:
        class RitmoFalso:
            erro = None
            ativo = False

            def __init__(self, _controle: object, cor_fixa: object = None) -> None:
                pass

            def iniciar(self) -> None:
                self.ativo = True

            def parar(self) -> None:
                self.ativo = False

        controle = ControleAbajurElgin(adb="adb-falso")
        with (
            patch("abajur_wifi._validar_dependencias_ritmo"),
            patch.object(controle, "_preparar") as preparar,
            patch("ritmo_navegador.RitmoNavegador", RitmoFalso),
        ):
            controle.iniciar_ritmo_navegador((255, 0, 0))

        preparar.assert_not_called()

    def test_wrapper_adb_preserva_thread_se_stop_nao_confirmar(self) -> None:
        class RitmoPreso:
            erro = None

            def parar(self) -> None:
                raise RuntimeError(ERRO_ENCERRAMENTO)

        controle = ControleAbajurElgin(adb="adb-falso")
        ritmo = RitmoPreso()
        controle._ritmo_navegador = ritmo
        with self.assertRaises(ErroAbajur) as contexto:
            controle._parar_ritmo_ativo()

        self.assertIn("ainda está sendo encerrada", str(contexto.exception))
        self.assertIs(controle._ritmo_navegador, ritmo)


if __name__ == "__main__":
    unittest.main()
