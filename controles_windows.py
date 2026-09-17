"""Atalhos globais enviados pela Nebula ao Windows."""

from __future__ import annotations

import ctypes
import time

import win32con
import win32gui


def salvar_replay_nvidia() -> None:
    """Aciona Alt+F10, atalho configurado para salvar o replay da NVIDIA."""
    usuario32 = ctypes.windll.user32
    keyeventf_keyup = 0x0002
    teclas = (0x12, 0x79)  # Alt, F10
    for tecla in teclas:
        usuario32.keybd_event(tecla, 0, 0, 0)
    time.sleep(0.08)
    for tecla in reversed(teclas):
        usuario32.keybd_event(tecla, 0, keyeventf_keyup, 0)


def ajustar_volume_youtube(aumentar: bool, passos: int = 2) -> bool:
    """Ajusta apenas o player de uma janela aberta do YouTube, sem mudar o Windows."""
    janelas: list[int] = []

    def encontrar(hwnd: int, _extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        titulo = win32gui.GetWindowText(hwnd).casefold()
        if "youtube" in titulo:
            janelas.append(hwnd)

    win32gui.EnumWindows(encontrar, None)
    if not janelas:
        return False

    anterior = win32gui.GetForegroundWindow()
    alvo = janelas[0]
    try:
        win32gui.ShowWindow(alvo, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(alvo)
        time.sleep(0.15)
        tecla = win32con.VK_UP if aumentar else win32con.VK_DOWN
        for _ in range(max(1, min(passos, 10))):
            ctypes.windll.user32.keybd_event(tecla, 0, 0, 0)
            ctypes.windll.user32.keybd_event(tecla, 0, 0x0002, 0)
            time.sleep(0.04)
    except Exception:
        return False
    finally:
        if anterior and anterior != alvo:
            try:
                win32gui.SetForegroundWindow(anterior)
            except Exception:
                pass
    return True
