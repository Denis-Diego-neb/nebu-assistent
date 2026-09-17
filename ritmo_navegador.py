"""Anima o abajur usando somente o medidor da sessão de áudio do navegador."""

from __future__ import annotations

from collections import deque
from array import array
import math
from queue import Empty, Queue
import statistics
import subprocess
import threading
import time
from typing import Protocol


NAVEGADORES = {"brave.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe"}
TIMEOUT_INICIALIZACAO = 60.0
TIMEOUT_ENCERRAMENTO = 25.0
INTENSIDADE_RITMO_PADRAO = 75
LIMIAR_PICO_RITMO = 0.003
FAIXA_MINIMA_RITMO = 0.008
ERRO_INICIALIZACAO = (
    "Não foi possível preparar o áudio do navegador e a conexão com a lâmpada."
)
ERRO_TIMEOUT_INICIALIZACAO = (
    "O modo música demorou demais para preparar o áudio e a conexão com a lâmpada."
)
ERRO_ENCERRAMENTO = (
    "A tarefa anterior do modo música ainda está sendo encerrada. Tente novamente em instantes."
)
ETAPA_AUDIO = "preparação do áudio"
ETAPA_ADB = "conexão ADB com o celular"
ETAPA_PAINEL = "abertura do painel da lâmpada"
ETAPA_SHELL = "canal ADB da animação"
_TIMEOUTS_ETAPAS = {
    ETAPA_AUDIO: 8.0,
    ETAPA_ADB: 25.0,
    ETAPA_PAINEL: 45.0,
    ETAPA_SHELL: 8.0,
}
TITULOS_MUSICA = (
    "youtube music", "spotify", "soundcloud", "deezer", "bandcamp",
    "official audio", "official video", "official music", "lyrics", "lyric video",
    "visualizer", "remix", "feat.", " ft.", " - topic - youtube",
)
TITULOS_FALA = (
    "tutorial", "aula ", "como fazer", "como usar", "explicacao", "explicação",
    "podcast", "review", "analise", "análise", "documentario", "documentário",
    "whatsapp", "discord", "google meet", "microsoft teams", "zoom", "messenger",
    "chamada", "videoconferencia", "videoconferência",
)


class ControladorRGB(Protocol):
    adb: str
    _largura: int
    _altura: int
    _modo_ativo: str | None
    _intensidade_ritmo: int

    def _preparar(self, cancelar: threading.Event | None = None) -> None: ...
    def _abrir_painel_ritmo(self, cancelar: threading.Event | None = None) -> None: ...
    def _aguardar_cancelavel(
        self, segundos: float, cancelar: threading.Event | None = None
    ) -> None: ...
    def _toque(self, x: int, y: int) -> None: ...


def calcular_nivel_pulso(
    normalizado: float,
    nivel_atual: float,
    intensidade: int,
) -> float:
    """Calcula o envelope visual; 50 preserva o comportamento original."""
    normalizado = max(0.0, min(float(normalizado), 1.0))
    nivel_atual = max(0.0, min(float(nivel_atual), 1.0))
    intensidade = max(1, min(int(intensidade), 100))
    if intensidade >= 50:
        escala = (intensidade - 50) / 50
        piso = 0.10 - 0.08 * escala
        expoente = 1.0 + 0.8 * escala
        ataque = 0.42 + 0.28 * escala
        queda = 0.18 + 0.22 * escala
    else:
        escala = (50 - intensidade) / 49
        piso = 0.10 + 0.40 * escala
        expoente = 1.0 - 0.30 * escala
        ataque = 0.42 - 0.17 * escala
        queda = 0.18 - 0.08 * escala
    alvo = piso + (1.0 - piso) * (normalizado ** expoente)
    fator = ataque if alvo > nivel_atual else queda
    return max(0.01, min(1.0, nivel_atual + (alvo - nivel_atual) * fator))


class DetectorRitmoMusical:
    """Classificador leve e conservador de envelope rítmico."""

    def __init__(self, amostras_por_segundo: int = 10, segundos: int = 6) -> None:
        self.frequencia = amostras_por_segundo
        self.amostras: deque[float] = deque(maxlen=amostras_por_segundo * segundos)

    def adicionar(self, pico: float) -> None:
        self.amostras.append(max(0.0, min(float(pico), 1.0)))

    def parece_musica(self) -> bool:
        valores = list(self.amostras)
        if len(valores) < self.amostras.maxlen:
            return False
        media = statistics.fmean(valores)
        if media < 0.006:
            return False
        ativos = sum(valor > 0.004 for valor in valores) / len(valores)
        if ativos < 0.48:
            return False

        centralizados = [valor - media for valor in valores]
        energia = sum(valor * valor for valor in centralizados)
        if energia < 1e-5:
            return False

        # Procura repetição entre 250 ms e 1,2 s, faixa típica de subdivisões
        # e batidas musicais. Fala comum tende a não manter um período estável.
        melhor_correlacao = -1.0
        lag_minimo = max(2, round(self.frequencia * 0.25))
        lag_maximo = min(len(valores) // 3, round(self.frequencia * 1.2))
        for atraso in range(lag_minimo, lag_maximo + 1):
            esquerda = centralizados[:-atraso]
            direita = centralizados[atraso:]
            numerador = sum(a * b for a, b in zip(esquerda, direita))
            denominador = math.sqrt(
                sum(a * a for a in esquerda) * sum(b * b for b in direita)
            )
            if denominador > 1e-9:
                melhor_correlacao = max(melhor_correlacao, numerador / denominador)
        # Sessões reais do Brave podem produzir um envelope musical claro um
        # pouco abaixo de 0,30 por causa da normalização do mixer do Windows.
        # 0,22 ainda exige janela completa, energia e ocupação mínimas acima.
        return melhor_correlacao >= 0.22


class MedidorNavegador:
    """Lê picos apenas das sessões de áudio pertencentes a navegadores."""

    def __init__(self) -> None:
        self._medidores: list[object] = []
        self._ultima_atualizacao = 0.0

    def _atualizar(self) -> None:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

        medidores: list[object] = []
        for sessao in AudioUtilities.GetAllSessions():
            try:
                processo = sessao.Process
                nome = processo.name().casefold() if processo else ""
                if nome in NAVEGADORES:
                    medidores.append(sessao._ctl.QueryInterface(IAudioMeterInformation))
            except Exception:
                continue
        self._medidores = medidores
        self._ultima_atualizacao = time.monotonic()

    def pico(self) -> float:
        agora = time.monotonic()
        if agora - self._ultima_atualizacao >= 1.0 or not self._medidores:
            self._atualizar()
        picos: list[float] = []
        for medidor in self._medidores:
            try:
                picos.append(float(medidor.GetPeakValue()))  # type: ignore[attr-defined]
            except Exception:
                self._ultima_atualizacao = 0.0
        return max(picos, default=0.0)


class MedidorGravesLoopback:
    """Mede a faixa de bumbo/baixo na saída do Windows sem depender de NumPy."""

    _CORTE_INFERIOR = 45.0
    _CORTE_SUPERIOR = 160.0

    def __init__(self, quadros_por_segundo: int = 10) -> None:
        import pyaudiowpatch as pyaudio

        self._audio = pyaudio.PyAudio()
        self._stream = None
        self._baixo_rapido = 0.0
        self._baixo_lento = 0.0
        try:
            dispositivo = self._audio.get_default_wasapi_loopback()
            self._taxa = int(dispositivo["defaultSampleRate"])
            self._canais = max(1, min(int(dispositivo["maxInputChannels"]), 2))
            self._amostras_por_quadro = max(
                256, round(self._taxa / max(1, quadros_por_segundo))
            )
            self._alfa_rapido = 1.0 - math.exp(
                -2.0 * math.pi * self._CORTE_SUPERIOR / self._taxa
            )
            self._alfa_lento = 1.0 - math.exp(
                -2.0 * math.pi * self._CORTE_INFERIOR / self._taxa
            )
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self._canais,
                rate=self._taxa,
                input=True,
                input_device_index=dispositivo["index"],
                frames_per_buffer=self._amostras_por_quadro,
            )
        except Exception:
            self.fechar()
            raise

    def pico(self) -> float:
        if self._stream is None:
            return 0.0
        bruto = self._stream.read(
            self._amostras_por_quadro,
            exception_on_overflow=False,
        )
        amostras = array("h")
        amostras.frombytes(bruto)
        if not amostras:
            return 0.0

        soma_quadrados = 0.0
        quantidade = 0
        canais = self._canais
        for indice in range(0, len(amostras) - canais + 1, canais):
            mono = sum(amostras[indice:indice + canais]) / canais
            self._baixo_rapido += self._alfa_rapido * (mono - self._baixo_rapido)
            self._baixo_lento += self._alfa_lento * (mono - self._baixo_lento)
            graves = self._baixo_rapido - self._baixo_lento
            soma_quadrados += graves * graves
            quantidade += 1
        rms = math.sqrt(soma_quadrados / max(1, quantidade)) / 32768.0
        return max(0.0, min(1.0, rms))

    def fechar(self) -> None:
        stream = getattr(self, "_stream", None)
        self._stream = None
        if stream is not None:
            try:
                stream.stop_stream()
            finally:
                stream.close()
        audio = getattr(self, "_audio", None)
        self._audio = None
        if audio is not None:
            audio.terminate()


def classificar_titulos_navegador(titulos: list[str]) -> bool | None:
    """Usa títulos somente como indício, priorizando evidência musical clara."""
    normalizados = [titulo.strip().casefold() for titulo in titulos if titulo.strip()]
    if any(indicio in titulo for titulo in normalizados for indicio in TITULOS_MUSICA):
        return True
    if any(indicio in titulo for titulo in normalizados for indicio in TITULOS_FALA):
        return False
    return None


def titulo_navegador_indica_musica() -> bool | None:
    """Retorna True/False para títulos claros e None quando inconclusivo."""
    try:
        import psutil
        import win32gui
        import win32process
    except ImportError:
        return None

    titulos: list[str] = []

    def visitar(hwnd: int, _extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        titulo = win32gui.GetWindowText(hwnd).strip().casefold()
        if not titulo:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if psutil.Process(pid).name().casefold() in NAVEGADORES:
                titulos.append(titulo)
        except Exception:
            return

    win32gui.EnumWindows(visitar, None)
    return classificar_titulos_navegador(titulos)


def atividade_indica_musica(
    indicacao_titulo: bool | None,
    detector: DetectorRitmoMusical,
) -> bool:
    """Combina o atalho por título com a evidência real do medidor de áudio.

    Um título negativo não pode vetar o detector: a janela visível pode ser de
    outra aba, enquanto a música continua tocando em segundo plano.
    """
    return indicacao_titulo is True or detector.parece_musica()


class RitmoNavegador:
    """Mantém a animação RGB em uma thread até receber ``parar``."""

    def __init__(
        self,
        controle: ControladorRGB,
        cor_fixa: tuple[int, int, int] | None = None,
    ) -> None:
        self.controle = controle
        self.cor_fixa = cor_fixa
        self._parar = threading.Event()
        self._pronto = threading.Event()
        self._trava_inicio = threading.Lock()
        self._progresso: Queue[tuple[str, object]] = Queue()
        self._thread: threading.Thread | None = None
        self._erro_inicializacao: Exception | None = None
        self.erro: str | None = None
        self.quadros_enviados = 0

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def pronto(self) -> bool:
        return self._pronto.is_set()

    def _limpar_progresso(self) -> None:
        while True:
            try:
                self._progresso.get_nowait()
            except Empty:
                return

    def _publicar_etapa(self, etapa: str) -> None:
        self._progresso.put(("etapa", etapa))

    def _aguardar_encerramento(self, timeout: float = TIMEOUT_ENCERRAMENTO) -> bool:
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        return not self.ativo

    def iniciar(self, timeout: float = TIMEOUT_INICIALIZACAO) -> None:
        if timeout < 0:
            raise ValueError("O timeout de inicialização não pode ser negativo.")
        with self._trava_inicio:
            if self.ativo and self.pronto:
                return
            if not self.ativo:
                self._parar.clear()
                self._pronto.clear()
                self._limpar_progresso()
                self._erro_inicializacao = None
                self.erro = None
                self._thread = threading.Thread(
                    target=self._executar,
                    name="Nebu-Ritmo-Navegador",
                    daemon=True,
                )
                self._thread.start()

            etapa = ETAPA_AUDIO
            while True:
                limite_etapa = min(timeout, _TIMEOUTS_ETAPAS[etapa])
                try:
                    tipo, detalhe = self._progresso.get(timeout=limite_etapa)
                except Empty:
                    self._parar.set()
                    encerrou = self._aguardar_encerramento()
                    mensagem = f"{ERRO_TIMEOUT_INICIALIZACAO} Etapa: {etapa}."
                    if not encerrou:
                        mensagem = f"{mensagem} {ERRO_ENCERRAMENTO}"
                    raise RuntimeError(mensagem)
                if tipo == "etapa":
                    etapa = str(detalhe)
                    continue
                if tipo == "erro":
                    causa = detalhe if isinstance(detalhe, Exception) else None
                    raise RuntimeError(
                        f"{ERRO_INICIALIZACAO} Etapa: {etapa}."
                    ) from causa
                if tipo == "pronto":
                    if not self.ativo:
                        raise RuntimeError(
                            f"{ERRO_INICIALIZACAO} Etapa: {etapa}."
                        )
                    return

    def parar(self, timeout: float = TIMEOUT_ENCERRAMENTO) -> None:
        self._parar.set()
        if not self._aguardar_encerramento(timeout):
            raise RuntimeError(ERRO_ENCERRAMENTO)

    def _executar(self) -> None:
        shell: subprocess.Popen[str] | None = None
        try:
            self._publicar_etapa(ETAPA_AUDIO)
            import comtypes

            comtypes.CoInitialize()
            # Falhas de import/COM/pycaw precisam chegar ao chamador antes de
            # qualquer alteração visível na lâmpada.
            medidor = MedidorNavegador()
            pico_inicial = medidor.pico()
            if self._parar.is_set():
                return
            modo_pulso = "color" if self.cor_fixa is not None else self.controle._modo_ativo
            if modo_pulso not in {"white", "color"}:
                raise RuntimeError(
                    "Escolha primeiro uma cor ou temperatura para o abajur."
                )
            self._publicar_etapa(ETAPA_ADB)
            self.controle._preparar(cancelar=self._parar)
            if self._parar.is_set():
                return
            self._publicar_etapa(ETAPA_PAINEL)
            self.controle._abrir_painel_ritmo(cancelar=self._parar)
            if self._parar.is_set():
                return
            brilho_base = 1.0
            if self.cor_fixa is not None:
                import colorsys

                self.controle._toque(440, 305)
                self.controle._aguardar_cancelavel(0.5, self._parar)
                if self._parar.is_set():
                    return
                vermelho, verde, azul = self.cor_fixa
                matiz_fixa, saturacao_fixa, brilho_base = colorsys.rgb_to_hsv(
                    vermelho / 255, verde / 255, azul / 255
                )
                angulo_fixo = matiz_fixa * 2 * math.pi
                self.controle._toque(
                    round(540 + 300 * math.cos(angulo_fixo)),
                    round(1000 - 300 * math.sin(angulo_fixo)),
                )
                self.controle._toque(round(200 + 680 * saturacao_fixa), 1735)
            elif modo_pulso == "white":
                self.controle._toque(220, 305)
                self.controle._aguardar_cancelavel(0.5, self._parar)
                if self._parar.is_set():
                    return
            else:
                self.controle._toque(440, 305)
                self.controle._aguardar_cancelavel(0.5, self._parar)
                if self._parar.is_set():
                    return
            y_brilho = 1645 if modo_pulso == "white" else 1540
            self._publicar_etapa(ETAPA_SHELL)
            shell = subprocess.Popen(
                [self.controle.adb, "shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if shell.stdin is None or shell.poll() is not None:
                raise RuntimeError("O shell ADB não permaneceu disponível.")
            detector = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
            detector.adicionar(pico_inicial)
            proximo_quadro = time.monotonic()
            ultima_leitura_titulo = 0.0
            indicacao_titulo: bool | None = None
            nivel_suave = 0.5
            estava_musica = False
            self._pronto.set()
            self._progresso.put(("pronto", True))
            while not self._parar.is_set():
                agora = time.monotonic()
                pico = medidor.pico()
                detector.adicionar(pico)
                if agora - ultima_leitura_titulo >= 2.0:
                    indicacao_titulo = titulo_navegador_indica_musica()
                    ultima_leitura_titulo = agora
                musica = atividade_indica_musica(indicacao_titulo, detector)
                if musica and pico > LIMIAR_PICO_RITMO and shell.stdin:
                    janela = list(detector.amostras)
                    minimo = min(janela, default=0.0)
                    maximo = max(janela, default=1.0)
                    normalizado = (pico - minimo) / max(
                        FAIXA_MINIMA_RITMO, maximo - minimo
                    )
                    nivel_suave = calcular_nivel_pulso(
                        normalizado,
                        nivel_suave,
                        getattr(
                            self.controle,
                            "_intensidade_ritmo",
                            INTENSIDADE_RITMO_PADRAO,
                        ),
                    )
                    percentual = max(2, round(brilho_base * nivel_suave * 100))
                    x = round(200 + 680 * percentual / 100)
                    y = y_brilho
                    real_x = round(x * self.controle._largura / 1080)
                    real_y = round(y * self.controle._altura / 2400)
                    shell.stdin.write(f"input tap {real_x} {real_y}\n")
                    shell.stdin.flush()
                    self.quadros_enviados += 1
                    estava_musica = True
                elif estava_musica and shell.stdin:
                    percentual = max(2, round(brilho_base * 100))
                    x = round(200 + 680 * percentual / 100)
                    real_x = round(x * self.controle._largura / 1080)
                    real_y = round(y_brilho * self.controle._altura / 2400)
                    shell.stdin.write(f"input tap {real_x} {real_y}\n")
                    shell.stdin.flush()
                    estava_musica = False
                proximo_quadro += 0.1
                self._parar.wait(max(0.01, proximo_quadro - time.monotonic()))
            if shell.stdin:
                percentual = max(2, round(brilho_base * 100))
                x = round(200 + 680 * percentual / 100)
                real_x = round(x * self.controle._largura / 1080)
                real_y = round(y_brilho * self.controle._altura / 2400)
                shell.stdin.write(f"input tap {real_x} {real_y}\n")
                shell.stdin.flush()
        except Exception as exc:
            self.erro = str(exc)
            if not self._pronto.is_set():
                self._erro_inicializacao = exc
        finally:
            if shell is not None:
                try:
                    if shell.stdin:
                        shell.stdin.write("exit\n")
                        shell.stdin.close()
                    shell.wait(timeout=2)
                except Exception:
                    shell.terminate()
            try:
                import comtypes

                comtypes.CoUninitialize()
            except Exception:
                pass
            if not self._pronto.is_set():
                causa = self._erro_inicializacao or RuntimeError(
                    "A inicialização do modo música foi cancelada."
                )
                self._progresso.put(("erro", causa))
