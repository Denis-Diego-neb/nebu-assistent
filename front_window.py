"""Abre o front espacial da Nebula em uma janela própria.

Tkinter não renderiza WebGL, então o front roda em uma janela de aplicativo do
Chromium (Chrome, Edge ou Brave) apontando para o servidor local. Nessa janela o
F11 alterna a tela cheia normalmente. Sem nenhum Chromium instalado, cai para o
navegador padrão do sistema.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

PERFIL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula" / "front-profile"

_EXECUTAVEIS = (
    "chrome.exe", "msedge.exe", "brave.exe", "chromium.exe",
    "google-chrome", "chromium-browser", "microsoft-edge",
)
_PASTAS_WINDOWS = (
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
)


def encontrar_navegador() -> str | None:
    """Caminho de um Chromium instalado, ou ``None`` se não houver."""
    for nome in _EXECUTAVEIS:
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    if os.name != "nt":
        return None
    raizes = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    for raiz in raizes:
        if not raiz:
            continue
        for relativo in _PASTAS_WINDOWS:
            caminho = Path(raiz) / relativo
            if caminho.is_file():
                return str(caminho)
    return None


def abrir(url: str, *, tela_cheia: bool = False, largura: int = 1280, altura: int = 820) -> str:
    """Abre ``url`` em janela de aplicativo. Devolve como a janela foi aberta.

    ``"app"`` quando usou um Chromium dedicado e ``"navegador"`` no fallback.
    """
    navegador = encontrar_navegador()
    if navegador:
        argumentos = [
            navegador,
            f"--app={url}",
            f"--user-data-dir={PERFIL}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        argumentos.append("--start-fullscreen" if tela_cheia else f"--window-size={largura},{altura}")
        try:
            PERFIL.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(
                argumentos,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            return "app"
        except OSError:
            pass
    webbrowser.open(url)
    return "navegador"


if __name__ == "__main__":  # Permite testar a janela sem subir a interface inteira.
    destino = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/espaco/"
    print(abrir(destino, tela_cheia="--tela-cheia" in sys.argv))
