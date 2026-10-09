"""Peças compartilhadas do modo chuva para dormir (hub do notebook e PC).

O hub é o relógio de referência. A sessão guarda o instante zero: cada tela
posiciona o vídeo em ``(agora - início) mod duração``, e os trovões saem de uma
semente. Assim o abajur (pelo hub) e o som (notebook e celular) seguem a mesma
lista sem trocar mensagens a cada trovão.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
import os
import random
import re
import threading
from typing import Callable
import wave

CICLO_AR_S = 3600
PRIMEIRO_TROVAO_S = (60.0, 150.0)
INTERVALO_TROVOES_S = (90.0, 420.0)
PESQUISA_PADRAO = "som de chuva para dormir"

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_VIDEO_NO_LINK = re.compile(
    r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
)


def extrair_video_id(texto: object) -> str | None:
    """Aceita o ID de 11 caracteres ou um link do YouTube."""
    texto = str(texto or "").strip()
    if _VIDEO_ID.fullmatch(texto):
        return texto
    achado = _VIDEO_NO_LINK.search(texto)
    return achado.group(1) if achado else None


@dataclass(frozen=True)
class Trovao:
    instante: float
    """Início do relâmpago, em segundos desde a época."""
    flashes: tuple[tuple[float, bool], ...]
    """(segundos, acesa) para o abajur; sempre termina apagada."""
    atraso_som: float
    """O som chega depois da luz, como numa tempestade de verdade."""
    intensidade: float
    """De 0,4 (raio longe) a 1,0 (raio perto): volume, estalo e duração."""
    semente: int
    """Variação do som; o celular sintetiza o mesmo trovão a partir dela."""

    @property
    def som(self) -> float:
        return self.instante + self.atraso_som

    def para_json(self) -> dict[str, object]:
        return {
            "instante": self.instante,
            "som": round(self.som, 3),
            "intensidade": self.intensidade,
            "semente": self.semente,
        }


def gerar_trovoes(semente: int, inicio: float, ate: float) -> list[Trovao]:
    """Lista determinística de trovões entre ``inicio`` e ``ate``."""
    sorteio = random.Random(semente)
    trovoes: list[Trovao] = []
    instante = inicio + sorteio.uniform(*PRIMEIRO_TROVAO_S)
    while instante <= ate:
        atraso = sorteio.uniform(0.4, 3.2)
        # Quanto mais perto o raio, menor a espera e mais forte o trovão.
        intensidade = round(max(0.4, min(1.0, 1.15 - atraso / 3.2 * 0.75)), 3)
        flashes: list[tuple[float, bool]] = []
        for indice in range(sorteio.randint(1, 3)):
            if indice:
                flashes.append((round(sorteio.uniform(0.05, 0.14), 3), False))
            flashes.append((round(sorteio.uniform(0.06, 0.22), 3), True))
        flashes.append((0.0, False))
        trovoes.append(Trovao(
            round(instante, 3), tuple(flashes), round(atraso, 3), intensidade,
            sorteio.getrandbits(31),
        ))
        instante += sorteio.uniform(*INTERVALO_TROVOES_S)
    return trovoes


def ar_ligado_no_ciclo(inicio: float, agora: float) -> bool:
    """1 hora ligado, 1 hora desligado, começando ligado."""
    return int(max(0.0, agora - inicio) // CICLO_AR_S) % 2 == 0


def sintetizar_trovao(semente: int, intensidade: float, taxa: int = 16_000) -> bytes:
    """WAV mono de 16 bits: estalo (raio perto) e ronco grave que some aos poucos.

    Sintetizado na hora para não depender de arquivos de áudio. O celular usa a
    mesma receita, então os dois aparelhos tocam trovões parecidos.
    """
    intensidade = max(0.0, min(1.0, float(intensidade)))
    sorteio = random.Random(semente)
    duracao = 3.0 + 4.0 * intensidade
    total = int(duracao * taxa)
    rajadas = [
        (sorteio.uniform(0.0, duracao * 0.55), sorteio.uniform(0.3, 1.2), sorteio.uniform(0.4, 1.0))
        for _ in range(3 + int(4 * intensidade))
    ]
    ataque = 0.02 + (1.0 - intensidade) * 0.25
    queda = 0.9 + 1.8 * intensidade
    bloco = max(1, taxa // 100)
    amostras: list[float] = []
    # Ronco grave (ruído marrom) para o corpo e uma faixa de 90 a 450 Hz para o
    # trovão aparecer também em alto-falante pequeno de celular e notebook.
    marrom = grave = agudo = medio = 0.0
    corte_alto = 1.0 - math.exp(-2 * math.pi * 450 / taxa)
    corte_baixo = 1.0 - math.exp(-2 * math.pi * 90 / taxa)
    for comeco in range(0, total, bloco):
        # O envelope muda devagar: calculá-lo a cada 10 ms basta e é bem mais leve.
        t = comeco / taxa
        envelope = min(1.0, t / ataque) * math.exp(-t / queda)
        for inicio_rajada, largura, forca in rajadas:
            d = (t - inicio_rajada) / largura
            if 0.0 <= d < 4.0:
                envelope += 0.6 * forca * math.exp(-d) * min(1.0, d * 8.0)
        estalo = intensidade > 0.7 and t < 0.4
        for i in range(comeco, min(total, comeco + bloco)):
            branco = sorteio.uniform(-1.0, 1.0)
            marrom = (marrom + 0.02 * branco) * 0.998
            grave += (marrom - grave) * 0.05
            agudo += (branco - agudo) * corte_alto
            medio += (branco - medio) * corte_baixo
            valor = (grave * 2.5 + (agudo - medio) * 4.0) * envelope
            if estalo:
                valor += 0.3 * intensidade * branco * math.exp(-(i / taxa) / 0.08)
            amostras.append(valor)
    pico = max((abs(valor) for valor in amostras), default=0.0) or 1.0
    escala = 0.6 * (0.5 + 0.5 * intensidade) / pico * 32767
    saida = io.BytesIO()
    with wave.open(saida, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(b"".join(
            int(max(-32767, min(32767, valor * escala))).to_bytes(2, "little", signed=True)
            for valor in amostras
        ))
    return saida.getvalue()


def tocar_wav(dados: bytes) -> None:
    """Toca um WAV em memória e só volta no fim (Windows)."""
    if os.name != "nt":
        return
    import winsound

    winsound.PlaySound(dados, winsound.SND_MEMORY)


_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def manter_acordado(ativo: bool) -> None:
    """Impede (ou volta a permitir) suspensão e tela apagada nesta thread."""
    if os.name != "nt":
        return
    import ctypes

    estado = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED if ativo else 0)
    ctypes.windll.kernel32.SetThreadExecutionState(estado)


class TelaChuva:
    """Janela do vídeo em tela cheia, com a máquina e a tela sempre acesas."""

    def __init__(
        self,
        abrir: Callable[[str], object] | None = None,
        acordado: Callable[[bool], None] = manter_acordado,
    ) -> None:
        if abrir is None:
            import front_window

            abrir = front_window.abrir_midia
        self._abrir = abrir
        self._acordado = acordado
        self._lock = threading.RLock()
        self._processo: object | None = None
        self._parar_vigilia: threading.Event | None = None

    @property
    def ativa(self) -> bool:
        return self._parar_vigilia is not None

    def abrir(self, url: str) -> None:
        with self._lock:
            self.fechar()
            self._processo = self._abrir(url)
            parar = threading.Event()
            self._parar_vigilia = parar
            # SetThreadExecutionState vale por thread: uma thread dedicada segura
            # o pedido enquanto a tela estiver aberta.
            threading.Thread(target=self._vigiar, args=(parar,), daemon=True,
                             name="TelaChuvaAcordada").start()

    def _vigiar(self, parar: threading.Event) -> None:
        try:
            while not parar.is_set():
                self._acordado(True)
                parar.wait(60)
        finally:
            self._acordado(False)

    def fechar(self) -> None:
        with self._lock:
            if self._parar_vigilia is not None:
                self._parar_vigilia.set()
                self._parar_vigilia = None
            processo, self._processo = self._processo, None
        encerrar = getattr(processo, "terminate", None)
        if callable(encerrar):
            try:
                encerrar()
            except OSError:
                pass


__all__ = [
    "CICLO_AR_S",
    "PESQUISA_PADRAO",
    "TelaChuva",
    "Trovao",
    "ar_ligado_no_ciclo",
    "extrair_video_id",
    "gerar_trovoes",
    "manter_acordado",
    "sintetizar_trovao",
    "tocar_wav",
]
