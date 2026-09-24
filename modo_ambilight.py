"""Ambilight local: transforma a cor media da janela de video em luz Tuya."""

from __future__ import annotations

import colorsys
import math
import os
import threading
import time
from collections.abc import Callable
from typing import Protocol

from PIL import Image, ImageGrab


CAPTURE_FPS = 15
LAMP_FPS = 10
SMOOTHING_SECONDS = 0.15
INITIAL_TIMEOUT = 7.0
WINDOW_RETRY_SECONDS = 0.20
KEEPALIVE_SECONDS = 1.5
MINIMUM_COLOR_CHANGE = 3
MAX_CONSECUTIVE_FAILURES = 5
INITIAL_VALID_FRAMES = 3
DEFAULT_KEYBOARD_ZONES = 12
MAX_KEYBOARD_ZONES = 23


def _keyboard_zone_count() -> int:
    try:
        configured = int(os.environ.get(
            "NEBULA_AMBILIGHT_KEYBOARD_ZONES",
            str(DEFAULT_KEYBOARD_ZONES),
        ))
    except ValueError:
        configured = DEFAULT_KEYBOARD_ZONES
    return max(1, min(MAX_KEYBOARD_ZONES, configured))


class ErroModoAmbilight(RuntimeError):
    """Falha compreensivel ao iniciar ou manter o modo Ambilight."""


class CapturadorAmbilight(Protocol):
    def capturar(self) -> Image.Image | None: ...


class CapturadorTela:
    """Tela principal inteira; captura unica compartilhada pelas saidas."""
    def capturar(self):
        return ImageGrab.grab().convert("RGB")


def calcular_media_tela(imagem):
    from PIL import ImageStat
    amostra = imagem.convert("RGB").resize((64, 36), Image.Resampling.BOX)
    return tuple(round(value) for value in ImageStat.Stat(amostra).mean)


def calcular_zonas_inferiores(imagem, quantidade: int = DEFAULT_KEYBOARD_ZONES):
    """Media de faixas horizontais na parte inferior, da esquerda para a direita."""
    if not isinstance(quantidade, int) or isinstance(quantidade, bool) or quantidade < 1:
        raise ValueError("A quantidade de zonas do Ambilight precisa ser positiva.")
    width, height = imagem.size
    if width < quantidade or height < 2:
        raise ValueError("A captura e pequena demais para a quantidade de zonas.")
    return tuple(
        calcular_media_tela(imagem.crop(
            (i * width // quantidade, 2 * height // 3,
             (i + 1) * width // quantidade, height)
        ))
        for i in range(quantidade)
    )


def calcular_cor_exterior_beamng(imagem: Image.Image) -> tuple[int, int, int]:
    """Cor do ambiente visto pelo para-brisa, sem o painel inferior."""
    width, height = imagem.size
    if width < 2 or height < 3:
        raise ValueError("A captura do BeamNG e pequena demais.")
    margem = max(0, round(width * 0.04))
    return calcular_media_tela(imagem.crop((
        margem,
        0,
        width - margem,
        max(2, round(height * 0.64)),
    )))


def calcular_cor_interior_beamng(imagem: Image.Image) -> tuple[int, int, int]:
    """Cor media do painel e da cabine na parte inferior da imagem."""
    width, height = imagem.size
    if width < 2 or height < 3:
        raise ValueError("A captura do BeamNG e pequena demais.")
    return calcular_media_tela(imagem.crop((0, 2 * height // 3, width, height)))


def _media_quadratica(valores: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    quantidade = max(1, len(valores))
    return tuple(
        round(math.sqrt(sum(pixel[canal] ** 2 for pixel in valores) / quantidade))
        for canal in range(3)
    )  # type: ignore[return-value]


def _preparar_amostra(
    imagem: Image.Image,
) -> tuple[Image.Image, list[tuple[int, int, int]]]:
    if imagem.width < 2 or imagem.height < 2:
        raise ValueError("A captura da janela e pequena demais.")
    esquerda = round(imagem.width * 0.05)
    direita = imagem.width - esquerda
    topo = round(imagem.height * 0.07)
    base = imagem.height - topo
    recorte = imagem.convert("RGB").crop((esquerda, topo, direita, base))
    redimensionada = recorte.resize((64, 36), Image.Resampling.BOX)
    pixels = list(redimensionada.get_flattened_data())
    sem_barras = [pixel for pixel in pixels if max(pixel) >= 12]
    if len(sem_barras) >= len(pixels) * 0.12:
        pixels = sem_barras
    return redimensionada, pixels


def _realcar_cor(cor: tuple[int, int, int]) -> tuple[int, int, int]:
    vermelho, verde, azul = cor
    matiz, saturacao, brilho = colorsys.rgb_to_hsv(
        vermelho / 255.0,
        verde / 255.0,
        azul / 255.0,
    )
    if saturacao >= 0.04:
        saturacao = min(1.0, saturacao * 1.35 + 0.04)
    brilho = max(0.04, min(0.72, brilho * 1.08))
    canais = colorsys.hsv_to_rgb(matiz, saturacao, brilho)
    return tuple(round(canal * 255) for canal in canais)  # type: ignore[return-value]


def calcular_paleta_ambiente(
    imagem: Image.Image,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Devolve a cor media principal e uma segunda cor dominante da cena."""
    amostra, pixels = _preparar_amostra(imagem)
    principal = _realcar_cor(_media_quadratica(pixels))
    quantizada = amostra.quantize(colors=8, method=Image.Quantize.MEDIANCUT).convert("RGB")
    frequencias = quantizada.getcolors(maxcolors=8) or []
    candidatas = sorted(frequencias, reverse=True)
    secundaria = principal
    for _quantidade, candidata in candidatas:
        if max(candidata) < 12:
            continue
        realcada = _realcar_cor(candidata)
        distancia = math.sqrt(sum((a - b) ** 2 for a, b in zip(realcada, principal)))
        saturacao = colorsys.rgb_to_hsv(*(canal / 255 for canal in realcada))[1]
        if distancia >= 45 and saturacao >= 0.12:
            secundaria = realcada
            break
    return principal, secundaria


def calcular_cor_ambiente(imagem: Image.Image) -> tuple[int, int, int]:
    """Calcula uma cor media viva sem deixar barras pretas dominarem a cena."""
    return calcular_paleta_ambiente(imagem)[0]


def captura_parece_protegida(imagem: Image.Image) -> bool:
    """Detecta o quadro quase preto tipico de uma sobreposicao de video protegida."""
    amostra = imagem.convert("RGB").resize((64, 36), Image.Resampling.BOX)
    pixels = list(amostra.get_flattened_data())
    escuros = sum(max(pixel) < 16 for pixel in pixels) / len(pixels)
    claros = sum(max(pixel) >= 80 for pixel in pixels) / len(pixels)
    return escuros >= 0.94 and claros <= 0.08


def suavizar_cor(
    anterior: tuple[float, float, float] | None,
    atual: tuple[int, int, int],
    intervalo: float,
    constante: float = SMOOTHING_SECONDS,
) -> tuple[float, float, float]:
    """Aplica uma media exponencial independente da taxa real de captura."""
    if anterior is None or constante <= 0:
        return tuple(float(canal) for canal in atual)  # type: ignore[return-value]
    alpha = 1.0 - math.exp(-max(0.0, intervalo) / constante)
    return tuple(
        origem + (destino - origem) * alpha
        for origem, destino in zip(anterior, atual)
    )  # type: ignore[return-value]


class CapturadorJanelaNetflix:
    """Captura a area cliente da janela visivel que contem Netflix no titulo."""

    def __init__(self, titulo: str | None = None) -> None:
        self.titulo = (titulo or os.environ.get("NEBULA_AMBILIGHT_WINDOW", "netflix")).casefold()
        self._hwnd: int | None = None

    def _janela_valida(self, hwnd: int) -> bool:
        try:
            import win32gui

            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return False
            titulo = win32gui.GetWindowText(hwnd).casefold()
            if self.titulo not in titulo:
                return False
            esquerda, topo, direita, base = win32gui.GetClientRect(hwnd)
            return direita - esquerda >= 320 and base - topo >= 180
        except Exception:
            return False

    def _encontrar_janela(self) -> int | None:
        try:
            import win32gui
        except ImportError as exc:
            raise ErroModoAmbilight(
                "O suporte de janelas do Windows nao esta instalado."
            ) from exc

        encontradas: list[int] = []
        win32gui.EnumWindows(
            lambda hwnd, lista: lista.append(hwnd) if self._janela_valida(hwnd) else None,
            encontradas,
        )
        if not encontradas:
            return None
        return max(
            encontradas,
            key=lambda hwnd: (
                win32gui.GetClientRect(hwnd)[2]
                * win32gui.GetClientRect(hwnd)[3]
            ),
        )

    def capturar(self) -> Image.Image | None:
        import win32gui

        hwnd = self._hwnd
        if hwnd is None or not self._janela_valida(hwnd):
            hwnd = self._encontrar_janela()
            self._hwnd = hwnd
        if hwnd is None:
            return None

        esquerda, topo = win32gui.ClientToScreen(hwnd, (0, 0))
        _x, _y, largura, altura = win32gui.GetClientRect(hwnd)
        if largura < 2 or altura < 2:
            return None
        return ImageGrab.grab(
            bbox=(esquerda, topo, esquerda + largura, topo + altura),
            all_screens=True,
        ).convert("RGB")


class ModoAmbilight:
    """Captura em 30 FPS e envia cores suavizadas a lampada em ate 10 Hz."""

    def __init__(
        self,
        saida_rgb: Callable[[int, int, int], None],
        *,
        saida_secundaria: Callable[[int, int, int], None] | None = None,
        saida_controle: Callable[[int, int, int], None] | None = None,
        saida_zonas: Callable | None = None,
        capturador: CapturadorAmbilight | None = None,
        capture_fps: float = CAPTURE_FPS,
        lamp_fps: float = LAMP_FPS,
        keyboard_zones: int | None = None,
        profile: str = "default",
    ) -> None:
        if not callable(saida_rgb):
            raise ValueError("O modo Ambilight precisa de uma saida RGB.")
        if capture_fps <= 0 or lamp_fps <= 0:
            raise ValueError("As taxas de captura e envio precisam ser positivas.")
        if profile not in {"default", "beamng"}:
            raise ValueError("Perfil de captura do Ambilight invalido.")
        if keyboard_zones is None:
            keyboard_zones = _keyboard_zone_count()
        if (
            not isinstance(keyboard_zones, int)
            or isinstance(keyboard_zones, bool)
            or not 1 <= keyboard_zones <= MAX_KEYBOARD_ZONES
        ):
            raise ValueError("Use entre 1 e 23 zonas para o teclado.")
        self._saida_rgb = saida_rgb
        self._saida_secundaria = saida_secundaria
        self._saida_controle = saida_controle
        self._saida_zonas = saida_zonas
        self._keyboard_zones = keyboard_zones
        self._profile = profile
        self._zonas_suaves = None
        self._zonas_enviadas = None
        self._erro_controle = None
        self._capturador = capturador or CapturadorTela()
        self._capture_interval = 1.0 / capture_fps
        self._lamp_interval = 1.0 / lamp_fps
        self._parar = threading.Event()
        self._pronto = threading.Event()
        self._condicao = threading.Condition()
        self._thread_captura: threading.Thread | None = None
        self._thread_lampada: threading.Thread | None = None
        self._cor_suave: tuple[float, float, float] | None = None
        self._cor_secundaria_suave: tuple[float, float, float] | None = None
        self._cor_enviada: tuple[int, int, int] | None = None
        self._cor_secundaria_enviada: tuple[int, int, int] | None = None
        self._revisao = 0
        self._janela_encontrada = False
        self._captura_protegida = False
        self._capturas = 0
        self._envios = 0
        self._falhas_consecutivas = 0
        self._erro: str | None = None
        self._erro_secundaria: str | None = None
        self._restaurar: Callable[[], None] | None = None
        self._restaurado = False
        self._enviou_primeiro_quadro = False

    @property
    def ativo(self) -> bool:
        return (
            not self._parar.is_set()
            and self._thread_captura is not None
            and self._thread_captura.is_alive()
            and self._thread_lampada is not None
            and self._thread_lampada.is_alive()
        )

    @property
    def erro(self) -> str | None:
        return self._erro

    @property
    def enviou_primeiro_quadro(self) -> bool:
        return self._enviou_primeiro_quadro

    def definir_restauracao(self, restaurar: Callable[[], None]) -> None:
        if self.ativo:
            raise ErroModoAmbilight("A restauracao deve ser definida antes de iniciar.")
        self._restaurar = restaurar

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        self._pronto.clear()
        self._restaurado = False
        self._thread_captura = threading.Thread(
            target=self._loop_captura,
            name="Nebula-Ambilight-Captura",
            daemon=True,
        )
        self._thread_lampada = threading.Thread(
            target=self._loop_lampada,
            name="Nebula-Ambilight-Tuya",
            daemon=True,
        )
        self._thread_captura.start()
        self._thread_lampada.start()
        if self._profile == "beamng":
            # O modo fica armado antes do jogo abrir. Uma espera curta ainda
            # permite propagar erros imediatos de captura, sem transformar a
            # ausencia normal da janela do BeamNG em falha de inicializacao.
            self._pronto.wait(0.25)
            if self._erro:
                erro = self._erro
                self.parar()
                raise ErroModoAmbilight(erro)
            return
        if not self._pronto.wait(INITIAL_TIMEOUT):
            self.parar()
            if self._captura_protegida:
                raise ErroModoAmbilight(
                    "A Netflix esta exibindo o video em uma camada protegida que a captura de tela nao consegue ler."
                )
            raise ErroModoAmbilight(
                "Nao consegui capturar a tela ou enviar a iluminacao aos dispositivos selecionados."
            )
        if self._erro:
            erro = self._erro
            self.parar()
            raise ErroModoAmbilight(erro)

    def parar(self) -> None:
        self._parar.set()
        with self._condicao:
            self._condicao.notify_all()
        atual = threading.current_thread()
        for thread in (self._thread_captura, self._thread_lampada):
            if thread is not None and thread is not atual:
                thread.join(timeout=4.0)
        self._restaurar_uma_vez()

    def _restaurar_uma_vez(self) -> None:
        if self._restaurado:
            return
        self._restaurado = True
        if self._restaurar is not None:
            try:
                self._restaurar()
            except Exception:
                if self._erro is None:
                    self._erro = "Falha ao restaurar a iluminacao anterior."

    def _falhar(self, mensagem: str) -> None:
        self._erro = mensagem
        self._parar.set()
        self._pronto.set()
        with self._condicao:
            self._condicao.notify_all()

    def _loop_captura(self) -> None:
        anterior = time.monotonic()
        proxima = anterior
        validos_consecutivos = 0
        try:
            while not self._parar.is_set():
                agora = time.monotonic()
                if agora < proxima and self._parar.wait(proxima - agora):
                    break
                agora = time.monotonic()
                proxima = max(proxima + self._capture_interval, agora)
                imagem = self._capturador.capturar()
                self._janela_encontrada = imagem is not None
                if imagem is None:
                    validos_consecutivos = 0
                    proxima = agora + WINDOW_RETRY_SECONDS
                    continue
                self._captura_protegida = isinstance(self._capturador, CapturadorJanelaNetflix) and captura_parece_protegida(imagem)
                if self._captura_protegida:
                    validos_consecutivos = 0
                    continue
                validos_consecutivos += 1
                if validos_consecutivos < INITIAL_VALID_FRAMES:
                    continue
                if self._profile == "beamng":
                    cor = calcular_cor_exterior_beamng(imagem)
                    secundaria = calcular_cor_interior_beamng(imagem)
                else:
                    cor = calcular_media_tela(imagem)
                    secundaria = cor
                suave = suavizar_cor(self._cor_suave, cor, agora - anterior)
                secundaria_suave = suavizar_cor(
                    self._cor_secundaria_suave, secundaria, agora - anterior
                )
                zonas = (
                    calcular_zonas_inferiores(imagem, self._keyboard_zones)
                    if self._saida_zonas is not None else None
                )
                zonas_suaves = tuple(suavizar_cor(self._zonas_suaves[i] if self._zonas_suaves else None, color, agora-anterior) for i, color in enumerate(zonas)) if zonas is not None else None
                anterior = agora
                with self._condicao:
                    self._cor_suave = suave
                    self._cor_secundaria_suave = secundaria_suave
                    self._zonas_suaves = zonas_suaves
                    self._capturas += 1
                    self._revisao += 1
                    self._condicao.notify()
        except Exception:
            self._falhar("Falha ao capturar as cores da tela.")

    def _loop_lampada(self) -> None:
        ultima_revisao = -1
        ultimo_envio = 0.0
        try:
            while not self._parar.is_set():
                with self._condicao:
                    self._condicao.wait_for(
                        lambda: self._parar.is_set() or self._revisao != ultima_revisao,
                        timeout=self._lamp_interval,
                    )
                    if self._parar.is_set():
                        break
                    cor_suave = self._cor_suave
                    cor_secundaria_suave = self._cor_secundaria_suave
                    revisao = self._revisao
                    zonas_suaves = self._zonas_suaves
                if cor_suave is None:
                    continue
                espera = self._lamp_interval - (time.monotonic() - ultimo_envio)
                if espera > 0 and self._parar.wait(espera):
                    break
                cor = tuple(max(0, min(255, round(canal))) for canal in cor_suave)
                cor_secundaria = (
                    tuple(max(0, min(255, round(canal))) for canal in cor_secundaria_suave)
                    if cor_secundaria_suave is not None else cor
                )
                mudou = self._cor_enviada is None or max(
                    abs(atual - anterior)
                    for atual, anterior in zip(cor, self._cor_enviada)
                ) >= MINIMUM_COLOR_CHANGE
                mudou_secundaria = self._cor_secundaria_enviada is None or max(
                    abs(atual - anterior)
                    for atual, anterior in zip(cor_secundaria, self._cor_secundaria_enviada)
                ) >= MINIMUM_COLOR_CHANGE
                expirou = time.monotonic() - ultimo_envio >= KEEPALIVE_SECONDS
                zonas = tuple(tuple(max(0,min(255,round(v))) for v in color) for color in zonas_suaves) if zonas_suaves else None
                mudou_zonas = zonas is not None and (self._zonas_enviadas is None or max(abs(a-b) for ca,cb in zip(zonas,self._zonas_enviadas) for a,b in zip(ca,cb)) >= MINIMUM_COLOR_CHANGE)
                ultima_revisao = revisao
                if not mudou and not mudou_secundaria and not mudou_zonas and not expirou:
                    continue
                try:
                    if mudou or expirou:
                        self._saida_rgb(*cor)
                except Exception:
                    self._falhas_consecutivas += 1
                    if self._falhas_consecutivas >= MAX_CONSECUTIVE_FAILURES:
                        self._falhar("A lampada perdeu a conexao durante o Ambilight.")
                        break
                    if self._parar.wait(0.5):
                        break
                    continue
                self._falhas_consecutivas = 0
                self._cor_enviada = cor
                if self._saida_zonas is not None and zonas is not None and (mudou_zonas or expirou):
                    try:
                        self._saida_zonas(zonas)
                        self._zonas_enviadas = zonas
                    except Exception as exc:
                        self._erro_secundaria = f"Falha ao atualizar a cor do Kumara: {exc}"
                        self._saida_zonas = None
                if self._saida_controle is not None and (mudou or expirou):
                    try:
                        self._saida_controle(*cor)
                    except Exception:
                        self._erro_controle = "Lightbar PS4 indisponivel. Confira USB e acesso compartilhado com Steam Input."
                        self._saida_controle = None
                if self._saida_secundaria is not None and (mudou_secundaria or expirou):
                    try:
                        self._saida_secundaria(*cor_secundaria)
                        self._cor_secundaria_enviada = cor_secundaria
                    except Exception:
                        self._erro_secundaria = "O teclado perdeu a conexao com o OpenRGB."
                        self._saida_secundaria = None
                self._envios += 1
                self._enviou_primeiro_quadro = True
                ultimo_envio = time.monotonic()
                self._pronto.set()
        finally:
            self._restaurar_uma_vez()

    def status(self) -> dict[str, object]:
        return {
            "ativo": self.ativo,
            "profile": self._profile,
            "janela": self._janela_encontrada,
            "captura_protegida": self._captura_protegida,
            "cor": self._cor_enviada,
            "cor_secundaria": self._cor_secundaria_enviada,
            "teclado": "conectado" if self._saida_secundaria is not None or self._saida_zonas is not None else (
                "erro" if self._erro_secundaria else "desativado"
            ),
            "capturas": self._capturas,
            "envios": self._envios,
            "erro": self._erro,
            "erro_teclado": self._erro_secundaria,
            "zonas_teclado": self._zonas_enviadas,
            "quantidade_zonas_teclado": self._keyboard_zones,
            "controle": "conectado" if self._saida_controle is not None else ("erro" if self._erro_controle else "desativado"),
            "erro_controle": self._erro_controle,
        }
