"""Controle do Redragon Kumara K552 pela API local do OpenRGB."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path


OPENRGB_PORT = 6742
DEVICE_HINTS = ("evision keyboard", "redragon", "k552", "kumara")


class OpenRGBKeyboardError(RuntimeError):
    """Falha segura ao iniciar ou controlar o RGB do teclado."""


def zonas_por_coluna(total, matrix, quantidade=3):
    if (
        not isinstance(quantidade, int)
        or isinstance(quantidade, bool)
        or quantidade < 1
    ):
        raise ValueError("A quantidade de zonas precisa ser positiva.")
    try:
        rows = [list(row) for row in matrix]
        width = max(map(len, rows))
    except (TypeError, ValueError):
        raise OpenRGBKeyboardError("OpenRGB nao informou a posicao fisica das teclas.")
    if quantidade > width:
        raise OpenRGBKeyboardError(
            "Ha mais zonas de cor que colunas fisicas no teclado."
        )
    mapping = {
        i: min(quantidade - 1, x * quantidade // width)
        for row in rows
        for x, i in enumerate(row)
        if type(i) is int and 0 <= i < total
    }
    if len(set(mapping.values())) != quantidade:
        raise OpenRGBKeyboardError("O mapa de teclas nao cobre todas as zonas de cor.")
    return mapping


def _leds_acesos_barra(
    total: int,
    matrix_map: object,
    percent: int,
) -> set[int]:
    """Seleciona LEDs em colunas, da esquerda para a direita, como uma barra."""
    percentual = max(0, min(100, int(percent)))
    if percentual >= 100:
        return set(range(total))
    try:
        linhas = [list(linha) for linha in matrix_map]  # type: ignore[arg-type]
        largura = max((len(linha) for linha in linhas), default=0)
    except (TypeError, ValueError):
        linhas = []
        largura = 0
    if largura:
        colunas_acesas = round(largura * percentual / 100)
        return {
            indice
            for linha in linhas
            for coluna, indice in enumerate(linha)
            if coluna < colunas_acesas
            and isinstance(indice, int)
            and not isinstance(indice, bool)
            and 0 <= indice < total
        }
    quantidade = round(total * percentual / 100)
    return set(range(quantidade))


def _openrgb_executable() -> Path | None:
    configured = os.environ.get("NEBULA_OPENRGB_PATH", "").strip()
    roots = [
        Path(configured) if configured else None,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Nebula" / "OpenRGB",
        Path(os.environ.get("ProgramFiles", "")) / "OpenRGB",
    ]
    for root in roots:
        if root is None:
            continue
        if root.is_file() and root.name.casefold() == "openrgb.exe":
            return root
        try:
            found = next(root.rglob("OpenRGB.exe"), None)
        except OSError:
            found = None
        if found is not None:
            return found
    return None


def _server_online() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", OPENRGB_PORT), timeout=0.25):
            return True
    except OSError:
        return False


def iniciar_servidor_openrgb(timeout: float = 18.0) -> None:
    if _server_online():
        return
    executable = _openrgb_executable()
    if executable is None:
        raise OpenRGBKeyboardError("OpenRGB nao esta instalado.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(executable), "--server", "--server-host", "127.0.0.1"],
        cwd=str(executable.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _server_online():
            return
        time.sleep(0.2)
    raise OpenRGBKeyboardError("O servidor local do OpenRGB nao respondeu.")


class TecladoKumaraOpenRGB:
    # O OpenRGB recebe a matriz completa pelo proprio servidor e preserva o
    # efeito multizona usado atualmente.
    ambilight_multizona_seguro = True

    """Aplica uma cor uniforme e restaura todas as teclas ao encerrar."""

    def __init__(self) -> None:
        iniciar_servidor_openrgb()
        try:
            from openrgb import OpenRGBClient
            from openrgb.utils import RGBColor
        except ImportError as exc:
            raise OpenRGBKeyboardError(
                "O cliente Python do OpenRGB nao esta instalado."
            ) from exc
        try:
            client = OpenRGBClient(name="Nebula Ambilight")
        except Exception as exc:
            raise OpenRGBKeyboardError("Nao consegui conectar ao OpenRGB.") from exc
        keyboard = next(
            (
                device for device in client.devices
                if any(hint in device.name.casefold() for hint in DEVICE_HINTS)
            ),
            None,
        )
        if keyboard is None:
            client.disconnect()
            raise OpenRGBKeyboardError("O Kumara nao foi encontrado pelo OpenRGB.")
        self._client = client
        self._keyboard = keyboard
        self._rgb_color = RGBColor
        self._original_colors = list(keyboard.colors)
        active_mode = keyboard.active_mode
        if isinstance(active_mode, int) and 0 <= active_mode < len(keyboard.modes):
            active_name = str(keyboard.modes[active_mode].name)
        else:
            active_name = str(getattr(active_mode, "name", ""))
        configured_restore = os.environ.get(
            "NEBULA_KEYBOARD_RESTORE_MODE", ""
        ).strip()
        self._restore_mode = configured_restore or (
            "Reactive" if active_name.casefold() in {"custom", "static"} else active_name
        )
        # O PID 320F:5000 usado pelo Kumara Lunar White compartilha o driver
        # generico EVision. Nesse driver o comando SetCustomMode e vazio em
        # alguns firmwares: o OpenRGB informa "Custom", mas o teclado continua
        # executando o efeito reativo interno. O modo Static envia a cor junto
        # ao comando de hardware e funciona nesses modelos.
        self._static_mode_name = next(
            (
                str(mode.name) for mode in keyboard.modes
                if str(mode.name).casefold() == "static"
            ),
            None,
        )
        self._use_static_mode = (
            "evision keyboard" in str(keyboard.name).casefold()
            and self._static_mode_name is not None
        )
        # O servidor OpenRGB nao torna atomicas as escritas do firmware EVision.
        # Use o mesmo fallback uniforme ja adotado pelo transporte USB.
        self.ambilight_multizona_seguro = not self._use_static_mode
        if not self._use_static_mode:
            try:
                keyboard.set_mode("Custom", force=True)
            except Exception as exc:
                client.disconnect()
                raise OpenRGBKeyboardError(
                    "O Kumara nao aceitou o modo Custom do OpenRGB."
                ) from exc
        self._lock = threading.RLock()
        self._closed = False
        self._last: tuple[int, int, int] | None = None
        self._base_color = (0, 80, 255)
        self._boost_custom_ready = not self._use_static_mode
        self._matrix_map = next(
            (
                getattr(zone, "matrix_map", None)
                for zone in keyboard.zones
                if getattr(zone, "matrix_map", None) is not None
            ),
            None,
        )

    @property
    def name(self) -> str:
        return str(self._keyboard.name)

    def enviar_rgb(self, red: int, green: int, blue: int) -> None:
        color = (int(red), int(green), int(blue))
        if not all(0 <= channel <= 255 for channel in color):
            raise ValueError("A cor do teclado precisa ser um RGB valido.")
        peak = max(color)
        if 0 < peak < 140:
            factor = 140 / peak
            color = tuple(min(255, round(channel * factor)) for channel in color)
        with self._lock:
            if self._closed:
                raise OpenRGBKeyboardError("O controle do teclado foi fechado.")
            if color == self._last:
                return
            if self._use_static_mode:
                self._enviar_modo_estatico(color)
            else:
                self._keyboard.set_color(self._rgb_color(*color), fast=True)
            self._last = color

    def _enviar_modo_estatico(
        self,
        color: tuple[int, int, int],
        *,
        brightness: int | None = None,
    ) -> None:
        mode = next(
            (
                candidate for candidate in self._keyboard.modes
                if str(candidate.name).casefold() == "static"
            ),
            None,
        )
        if mode is None:
            raise OpenRGBKeyboardError("O modo Static do Kumara desapareceu.")
        mode.colors = [self._rgb_color(*color)]
        maximum = getattr(mode, "brightness_max", None)
        if isinstance(maximum, int):
            mode.brightness = maximum if brightness is None else max(
                0, min(maximum, int(brightness))
            )
        self._keyboard.set_mode(mode, force=True)

    def definir_cor_base(self, color: tuple[int, int, int]) -> None:
        if len(color) != 3 or not all(isinstance(channel, int) and 0 <= channel <= 255 for channel in color):
            raise ValueError("A cor base do teclado precisa ser um RGB valido.")
        self._base_color = tuple(color)

    def enviar_zonas(self, colors):
        if not colors or any(len(c) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in c) for c in colors):
            raise ValueError("Informe uma ou mais cores RGB validas.")
        with self._lock:
            if self._closed:
                raise OpenRGBKeyboardError("O controle do teclado foi fechado.")
            total = len(self._original_colors) or len(self._keyboard.colors)
            mapping = zonas_por_coluna(total, self._matrix_map, len(colors))
            if not self._boost_custom_ready:
                self._keyboard.set_mode("Custom", force=True)
                self._boost_custom_ready = True
            self._keyboard.set_colors([self._rgb_color(*colors[mapping[i]]) if i in mapping else self._rgb_color(0, 0, 0) for i in range(total)], fast=True)
            self._last = None

    def set_boost(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        with self._lock:
            if self._closed:
                raise OpenRGBKeyboardError("O controle do teclado foi fechado.")
            total = len(self._original_colors) or len(self._keyboard.colors)
            acesas = _leds_acesos_barra(total, self._matrix_map, percent)
            ligada = self._rgb_color(*self._base_color)
            apagada = self._rgb_color(0, 0, 0)
            try:
                if not self._boost_custom_ready:
                    self._keyboard.set_mode("Custom", force=True)
                    self._boost_custom_ready = True
                self._keyboard.set_colors(
                    [ligada if indice in acesas else apagada for indice in range(total)],
                    fast=True,
                )
            except Exception as exc:
                raise OpenRGBKeyboardError(
                    "O Kumara nao aceitou a barra de boost por tecla."
                ) from exc
            self._last = None

    def restaurar(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._use_static_mode and self._restore_mode:
                self._keyboard.set_mode(self._restore_mode, force=True)
                self._boost_custom_ready = False
            elif self._original_colors:
                self._keyboard.set_colors(self._original_colors, fast=True)
            self._last = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if not self._use_static_mode and self._original_colors:
                    self._keyboard.set_colors(self._original_colors, fast=True)
                if self._restore_mode:
                    self._keyboard.set_mode(self._restore_mode, force=True)
            finally:
                self._closed = True
                try:
                    self._client.disconnect()
                except Exception:
                    pass

    def __enter__(self) -> "TecladoKumaraOpenRGB":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def criar_teclado_kumara():
    """Usa USB confirmado no 320F:5000; preserva OpenRGB em outros modelos."""
    from teclado_evision import TecladoKumaraUSB, encontrar_kumara

    info = encontrar_kumara()
    if info is None:
        return TecladoKumaraOpenRGB()
    # O driver generico pode ficar preso esperando a resposta de troca de modo
    # que este firmware nao envia. Nao deixe dois escritores na mesma colecao HID.
    import psutil

    executable = _openrgb_executable()
    expected = os.path.normcase(os.path.abspath(executable)) if executable else None
    processes = []
    for process in psutil.process_iter(['name', 'exe']):
        if str(process.info['name']).casefold() != 'openrgb.exe':
            continue
        actual = process.info.get('exe')
        if actual is None or os.path.normcase(os.path.abspath(actual)) != expected:
            raise OpenRGBKeyboardError('Feche o OpenRGB externo para a Nebula controlar o Kumara por USB.')
        processes.append(process)
    for process in processes:
        try:
            process.terminate()
            process.wait(timeout=3)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired as exc:
            raise OpenRGBKeyboardError('O OpenRGB ainda esta usando o Kumara.') from exc
    try:
        return TecladoKumaraUSB(info)
    except RuntimeError as exc:
        raise OpenRGBKeyboardError(str(exc)) from exc


__all__ = ["OpenRGBKeyboardError", "TecladoKumaraOpenRGB", "criar_teclado_kumara", "iniciar_servidor_openrgb"]
