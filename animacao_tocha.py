"""Gerador e animação de chama para o abajur Elgin controlado por ADB."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import subprocess
import threading
import time
from typing import Protocol


@dataclass(frozen=True)
class QuadroTocha:
    matiz: float
    saturacao: float
    brilho: float


class GeradorTocha:
    """Produz uma chama suave dentro de uma faixa quente e segura."""

    def __init__(self, aleatorio: random.Random | None = None) -> None:
        self._aleatorio = aleatorio or random.Random()
        self._matiz = 0.062
        self._saturacao = 0.92
        self._brilho = 0.72
        self._alvo = QuadroTocha(self._matiz, self._saturacao, self._brilho)
        self._quadros_restantes = 0

    def _novo_alvo(self) -> None:
        # A maior parte da chama fica no laranja. Brasas vermelhas aparecem
        # brevemente e clarões mais claros continuam laranja, sem amarelar.
        sorteio = self._aleatorio.random()
        if sorteio < 0.10:  # brasa: um toque curto de vermelho
            matiz = self._aleatorio.uniform(0.002, 0.025)
            saturacao = self._aleatorio.uniform(0.94, 1.0)
            brilho = self._aleatorio.uniform(0.40, 0.68)
        elif sorteio < 0.23:  # clarão: laranja claro, não amarelo
            matiz = self._aleatorio.uniform(0.075, 0.105)
            saturacao = self._aleatorio.uniform(0.72, 0.86)
            brilho = self._aleatorio.uniform(0.88, 1.0)
        else:
            matiz = self._aleatorio.triangular(0.028, 0.085, 0.060)
            saturacao = self._aleatorio.uniform(0.82, 0.99)
            brilho = self._aleatorio.triangular(0.42, 0.90, 0.68)
        self._alvo = QuadroTocha(matiz, saturacao, brilho)
        self._quadros_restantes = self._aleatorio.randint(2, 5)

    def proximo(self) -> QuadroTocha:
        if self._quadros_restantes <= 0:
            self._novo_alvo()
        self._quadros_restantes -= 1
        self._matiz += (self._alvo.matiz - self._matiz) * 0.42
        self._saturacao += (self._alvo.saturacao - self._saturacao) * 0.35
        self._brilho += (self._alvo.brilho - self._brilho) * 0.58
        return QuadroTocha(self._matiz, self._saturacao, self._brilho)


class ControladorTochaADB(Protocol):
    adb: str
    _largura: int
    _altura: int

    def _preparar(self, cancelar: threading.Event | None = None) -> None: ...
    def _abrir_painel_ritmo(self, cancelar: threading.Event | None = None) -> None: ...
    def _aguardar_cancelavel(
        self, segundos: float, cancelar: threading.Event | None = None
    ) -> None: ...
    def _toque(self, x: int, y: int) -> None: ...


class AnimacaoTochaADB:
    _INTERVALO = 0.28
    _TIMEOUT_INICIO = 60.0
    _TIMEOUT_ENCERRAMENTO = 25.0

    def __init__(self, controle: ControladorTochaADB) -> None:
        self.controle = controle
        self._parar = threading.Event()
        self._pronto = threading.Event()
        self._thread: threading.Thread | None = None
        self.erro: str | None = None
        self.quadros_enviados = 0

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._thread = threading.Thread(
            target=self._executar,
            name="Nebu-Tocha-ADB",
            daemon=True,
        )
        self._thread.start()
        if not self._pronto.wait(self._TIMEOUT_INICIO):
            self._parar.set()
            if self._thread:
                self._thread.join(self._TIMEOUT_ENCERRAMENTO)
            raise RuntimeError("O modo tocha demorou demais para abrir o painel da lâmpada.")
        if self.erro:
            raise RuntimeError(self.erro)
        if not self.ativo:
            raise RuntimeError("O modo tocha foi encerrado durante a inicialização.")

    def parar(self) -> None:
        self._parar.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(self._TIMEOUT_ENCERRAMENTO)
        if self.ativo:
            raise RuntimeError("A animação de tocha ainda está sendo encerrada.")

    def _coordenadas(self, quadro: QuadroTocha) -> tuple[tuple[int, int], ...]:
        angulo = quadro.matiz * 2 * math.pi
        pontos = (
            (round(540 + 300 * math.cos(angulo)), round(1000 - 300 * math.sin(angulo))),
            (round(200 + 680 * quadro.brilho), 1540),
            (round(200 + 680 * quadro.saturacao), 1735),
        )
        return tuple(
            (
                round(x * self.controle._largura / 1080),
                round(y * self.controle._altura / 2400),
            )
            for x, y in pontos
        )

    def _enviar(self, shell: subprocess.Popen[str], quadro: QuadroTocha) -> None:
        if shell.stdin is None or shell.poll() is not None:
            raise RuntimeError("O canal ADB do modo tocha foi encerrado.")
        for x, y in self._coordenadas(quadro):
            shell.stdin.write(f"input tap {x} {y}\n")
        shell.stdin.flush()
        self.quadros_enviados += 1

    def _executar(self) -> None:
        shell: subprocess.Popen[str] | None = None
        try:
            self.controle._preparar(cancelar=self._parar)
            if self._parar.is_set():
                return
            self.controle._abrir_painel_ritmo(cancelar=self._parar)
            if self._parar.is_set():
                return
            self.controle._toque(440, 305)
            self.controle._aguardar_cancelavel(0.5, self._parar)
            if self._parar.is_set():
                return
            shell = subprocess.Popen(
                [self.controle.adb, "shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            gerador = GeradorTocha()
            self._enviar(shell, gerador.proximo())
            self._pronto.set()
            while not self._parar.wait(self._INTERVALO):
                self._enviar(shell, gerador.proximo())
        except Exception:
            self.erro = "Não consegui manter a animação de tocha no celular."
            self._pronto.set()
        finally:
            if shell is not None:
                try:
                    if shell.stdin:
                        shell.stdin.write("exit\n")
                        shell.stdin.close()
                    shell.wait(timeout=2)
                except Exception:
                    shell.terminate()
            if not self._pronto.is_set():
                self.erro = self.erro or "A inicialização do modo tocha foi cancelada."
                self._pronto.set()
