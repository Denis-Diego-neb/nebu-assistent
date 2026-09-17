"""Leitor externo do medidor de boost do Rocket League, compatível com EAC.

O módulo captura somente o canto inferior direito da janela do jogo. A imagem
é convertida para luminância antes do OCR, portanto azul/laranja, arena e modo
daltônico não participam da classificação. Nenhum processo é aberto, injetado ou
lido; a fonte é exclusivamente a imagem que o Windows já exibe na tela.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from math import cos, pi, sin
import re
import socket
import threading
import time
from typing import Iterable

from PIL import Image, ImageGrab

try:
    import win32gui
except ImportError:  # pragma: no cover - a build Windows sempre inclui pywin32.
    win32gui = None  # type: ignore[assignment]


TELEMETRY_HOST = "127.0.0.1"
TELEMETRY_PORT = 29876
VISUAL_SOURCE = "rocket_league_visual"
CAPTURE_INTERVAL = 0.12
INVALID_AFTER = 0.90

# Região ampla que contém o medidor em todas as escalas usuais de interface.
# Coordenadas relativas ao client area do Rocket League.
BOOST_REGION = (0.79, 0.70, 1.00, 1.00)

# Geometria medida no HUD 1920x1080. As coordenadas são normalizadas na hora
# da leitura, portanto o mesmo aro funciona em outras resoluções 16:9. O aro
# começa embaixo e cresce no sentido horário até o canto superior direito.
REFERENCE_SIZE = (403, 324)
RING_CENTER = (236, 155)
RING_RADIUS = (94, 119)
RING_START_DEG = 90.0
RING_END_DEG = 320.0
RING_SAMPLES = 101
RING_BRIGHTNESS = 145.0


class ErroLeitorBoostVisual(RuntimeError):
    """Falha ao preparar ou executar o reconhecimento visual."""


@dataclass(frozen=True)
class LeituraBoost:
    valor: int | None
    textos: tuple[str, ...]
    janela_encontrada: bool


def extrair_valor_boost(textos: Iterable[str]) -> int | None:
    """Extrai somente um contador isolado de 0 a 100 dos resultados do OCR."""
    candidatos: list[int] = []
    for texto in textos:
        for token in re.findall(r"[0-9ODIL|]{1,3}", texto.upper()):
            # Só corrige letras quando o token inteiro pode ser um número. Isso
            # impede que a legenda "BOOST" vire o falso valor 00.
            if not any(caractere.isdigit() for caractere in token) and token not in {"O", "D"}:
                continue
            limpo = token.replace("O", "0").replace("D", "0")
            limpo = limpo.replace("I", "1").replace("L", "1").replace("|", "1")
            encontrado = limpo
            valor = int(encontrado)
            if 0 <= valor <= 100:
                candidatos.append(valor)
    if not candidatos:
        return None
    # A região não inclui placar/relógio. Se houver resíduo, o maior grupo
    # reconhecido costuma ser o número central, e o filtro temporal ainda valida.
    return candidatos[0]


def _energia_do_aro(imagem: Image.Image, fracao: float) -> float:
    """Mede o canal mais luminoso do aro, sem depender de azul ou laranja."""
    largura, altura = imagem.size
    ref_largura, ref_altura = REFERENCE_SIZE
    centro_x, centro_y = RING_CENTER
    raio_minimo, raio_maximo = RING_RADIUS
    angulo_base = (RING_START_DEG + (RING_END_DEG - RING_START_DEG) * fracao) * pi / 180.0
    pixels = imagem.load()
    amostras: list[int] = []
    for desvio in (-2, -1, 0, 1, 2):
        angulo = angulo_base + desvio * pi / 180.0
        for raio in range(raio_minimo, raio_maximo + 1):
            x_ref = centro_x + raio * cos(angulo)
            y_ref = centro_y + raio * sin(angulo)
            x = max(0, min(largura - 1, round(x_ref * largura / ref_largura)))
            y = max(0, min(altura - 1, round(y_ref * altura / ref_altura)))
            vermelho, verde, azul = pixels[x, y]
            amostras.append(max(vermelho, verde, azul))
    amostras.sort(reverse=True)
    topo = amostras[:12]
    return sum(topo) / len(topo)


def estimar_boost_pelo_aro(imagem: Image.Image) -> int | None:
    """Estima 0..100 pela porção acesa do aro do HUD.

    O canal RGB máximo torna o cálculo invariável à matiz: HUD azul, laranja e
    modo daltônico produzem o mesmo sinal. O ponto de corte procura a melhor
    sequência "aceso e depois apagado", rejeitando brilhos isolados da arena.
    """
    if imagem.width < 160 or imagem.height < 120:
        return None
    rgb = imagem.convert("RGB")
    margens = [
        _energia_do_aro(rgb, indice / (RING_SAMPLES - 1)) - RING_BRIGHTNESS
        for indice in range(RING_SAMPLES)
    ]
    acumulado = 0.0
    melhor = 0.0
    limite = 0
    for indice, margem in enumerate(margens, start=1):
        acumulado += margem
        if acumulado > melhor:
            melhor = acumulado
            limite = indice
    return max(0, min(100, round(limite * 100 / RING_SAMPLES)))


class FiltroBoostVisual:
    """Rejeita saltos impossíveis sem atrasar consumo e pickups normais."""

    def __init__(self) -> None:
        self.valor: int | None = None
        self._pendente: int | None = None
        self._repeticoes = 0

    def reset(self) -> None:
        self.valor = None
        self._pendente = None
        self._repeticoes = 0

    def atualizar(self, candidato: int | None) -> int | None:
        if candidato is None or not 0 <= candidato <= 100:
            return None
        if self.valor is None:
            return self._confirmar(candidato, repeticoes_necessarias=2)

        delta = candidato - self.valor
        # Em 120 ms, gastar boost muda poucos pontos; damos margem para quedas de
        # quadros. Pad pequeno soma 12 e pad grande leva diretamente a 100.
        if -16 <= delta <= 15 or candidato == 100:
            self.valor = candidato
            self._pendente = None
            self._repeticoes = 0
            return candidato
        return self._confirmar(candidato, repeticoes_necessarias=2)

    def _confirmar(self, candidato: int, *, repeticoes_necessarias: int) -> int | None:
        if self._pendente is not None and abs(candidato - self._pendente) <= 1:
            self._repeticoes += 1
        else:
            self._pendente = candidato
            self._repeticoes = 1
        if self._repeticoes < repeticoes_necessarias:
            return None
        self.valor = candidato
        self._pendente = None
        self._repeticoes = 0
        return candidato


class LeitorBoostVisual:
    """Captura o HUD, reconhece o boost e publica o protocolo Nebula v2."""

    def __init__(
        self,
        host: str = TELEMETRY_HOST,
        port: int = TELEMETRY_PORT,
        intervalo: float = CAPTURE_INTERVAL,
    ) -> None:
        if host != TELEMETRY_HOST:
            raise ValueError("O leitor visual só envia telemetria para o computador local.")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Porta de telemetria inválida.")
        if intervalo < 0.08:
            raise ValueError("Intervalo de captura curto demais.")
        self.host = host
        self.port = port
        self.intervalo = intervalo
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._lock = threading.RLock()
        self._socket: socket.socket | None = None
        self._sequencia = 0
        self._erro: str | None = None
        self._ultima_leitura: LeituraBoost | None = None
        self._ultimo_valido: float | None = None
        self._filtro = FiltroBoostVisual()
        self._historico_textos: deque[tuple[str, ...]] = deque(maxlen=5)

    @property
    def ativo(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and not self._parar.is_set())

    @property
    def erro(self) -> str | None:
        with self._lock:
            return self._erro

    def iniciar(self) -> None:
        if self.ativo:
            return
        if win32gui is None:
            raise ErroLeitorBoostVisual(
                "Faltam os componentes de captura do Windows. Reinstale a Nebula 1.15.1 ou mais recente."
            )
        self._parar.clear()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._filtro.reset()
        with self._lock:
            self._erro = None
            self._ultima_leitura = None
            self._ultimo_valido = None
        self._thread = threading.Thread(
            target=self._executar_thread,
            name="Nebula-Boost-Visual",
            daemon=True,
        )
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        emissor = self._socket
        if emissor is not None:
            emissor.close()
        self._socket = None
        self._thread = None

    def status(self) -> dict[str, object]:
        with self._lock:
            leitura = self._ultima_leitura
            return {
                "ativo": self.ativo,
                "janela": bool(leitura is not None and leitura.janela_encontrada),
                "valor": leitura.valor if leitura is not None else None,
                "textos": list(leitura.textos) if leitura is not None else [],
                "erro": self._erro,
            }

    def _executar_thread(self) -> None:
        try:
            self._loop()
        except Exception as exc:
            with self._lock:
                self._erro = f"O leitor visual de boost foi interrompido: {exc}"
            self._enviar(None)
            self._parar.set()

    def _loop(self) -> None:
        ultimo_invalido_enviado = 0.0
        while not self._parar.is_set():
            inicio = time.monotonic()
            retangulo = self._retangulo_medidor()
            if retangulo is None:
                leitura = LeituraBoost(None, (), False)
            else:
                imagem = ImageGrab.grab(bbox=retangulo, all_screens=True).convert("RGB")
                candidato = estimar_boost_pelo_aro(imagem)
                valor = self._filtro.atualizar(candidato)
                leitura = LeituraBoost(valor, (), True)
            with self._lock:
                self._ultima_leitura = leitura
                self._historico_textos.append(leitura.textos)

            if leitura.valor is not None:
                self._ultimo_valido = inicio
                self._enviar(leitura.valor)
            elif self._ultimo_valido is None or inicio - self._ultimo_valido >= INVALID_AFTER:
                if inicio - ultimo_invalido_enviado >= 0.50:
                    self._enviar(None)
                    ultimo_invalido_enviado = inicio
            espera = self.intervalo - (time.monotonic() - inicio)
            if espera > 0:
                self._parar.wait(espera)

    @staticmethod
    def _janela_rocket_league() -> int | None:
        assert win32gui is not None
        candidatas: list[int] = []

        def visitar(hwnd: int, _extra: object) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            titulo = win32gui.GetWindowText(hwnd).casefold()
            if "rocket league" not in titulo:
                return True
            esquerda, topo, direita, base = win32gui.GetClientRect(hwnd)
            if direita - esquerda >= 800 and base - topo >= 450:
                candidatas.append(hwnd)
            return True

        win32gui.EnumWindows(visitar, None)
        return candidatas[0] if candidatas else None

    @classmethod
    def _retangulo_medidor(cls) -> tuple[int, int, int, int] | None:
        assert win32gui is not None
        hwnd = cls._janela_rocket_league()
        if hwnd is None:
            return None
        esquerda, topo = win32gui.ClientToScreen(hwnd, (0, 0))
        _x0, _y0, largura, altura = win32gui.GetClientRect(hwnd)
        rx0, ry0, rx1, ry1 = BOOST_REGION
        return (
            esquerda + round(largura * rx0),
            topo + round(altura * ry0),
            esquerda + round(largura * rx1),
            topo + round(altura * ry1),
        )

    def _enviar(self, valor: int | None) -> None:
        emissor = self._socket
        if emissor is None:
            return
        objeto = {
            "v": 2,
            "seq": self._sequencia,
            "source": VISUAL_SOURCE,
            "metric": "boost",
            "valid": valor is not None,
            "value": (valor or 0) / 100.0,
        }
        self._sequencia = (self._sequencia + 1) & 0xFFFFFFFF
        emissor.sendto(
            json.dumps(objeto, separators=(",", ":")).encode("utf-8"),
            (self.host, self.port),
        )


__all__ = [
    "BOOST_REGION",
    "ErroLeitorBoostVisual",
    "estimar_boost_pelo_aro",
    "extrair_valor_boost",
    "FiltroBoostVisual",
    "LeitorBoostVisual",
    "LeituraBoost",
    "VISUAL_SOURCE",
]
