"""Abre o front espacial da Nebula em uma janela própria.

Tkinter não renderiza WebGL, então o front roda em uma janela de aplicativo do
Chromium (Brave primeiro, depois Chrome ou Edge) apontando para o servidor local.
Nessa janela o F11 alterna a tela cheia normalmente. Sem nenhum Chromium
instalado, cai para o navegador padrão do sistema.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

PERFIL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula" / "front-profile"

# Em ordem de preferência. O Brave vem primeiro: é o navegador do Denis, e o
# bloqueador dele tira os anúncios do YouTube durante o modo chuva.
_NAVEGADORES = (
    (("brave.exe", "brave-browser", "brave"), ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
    (("chrome.exe", "google-chrome"), ("Google", "Chrome", "Application", "chrome.exe")),
    (("msedge.exe", "microsoft-edge"), ("Microsoft", "Edge", "Application", "msedge.exe")),
    (("chromium.exe", "chromium-browser", "chromium"), ()),
)


def encontrar_navegador() -> str | None:
    """Caminho de um Chromium instalado, ou ``None`` se não houver.

    Procura cada navegador no PATH e nas pastas de instalação antes de passar
    ao próximo, para um Chrome no PATH não passar na frente do Brave.
    """
    raizes = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ] if os.name == "nt" else []
    for nomes, pastas in _NAVEGADORES:
        for nome in nomes:
            caminho = shutil.which(nome)
            if caminho:
                return caminho
        for raiz in raizes:
            if raiz and pastas:
                caminho = Path(raiz).joinpath(*pastas)
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


PERFIL_MIDIA = PERFIL.with_name("midia-profile")


def _preparar_perfil_midia() -> None:
    """Perfil novo já com som e reprodução automática liberados.

    O Brave tem bloqueio próprio de reprodução automática, que a opção
    ``--autoplay-policy`` do Chromium não desliga. Um perfil existente fica
    como o usuário deixou.
    """
    preferencias = PERFIL_MIDIA / "Default" / "Preferences"
    if preferencias.exists():
        return
    preferencias.parent.mkdir(parents=True, exist_ok=True)
    preferencias.write_text(json.dumps({
        "profile": {"default_content_setting_values": {"autoplay": 1, "sound": 1}},
    }), encoding="utf-8")


def abrir_midia(url: str) -> subprocess.Popen | None:
    """Abre ``url`` em tela cheia, sem bordas, com som sem precisar de clique.

    Usa um perfil próprio: assim a janela é um processo separado, as opções
    valem mesmo com o Espaço aberto e fechar o processo fecha só ela. Sem
    nenhum Chromium, cai no navegador padrão e devolve ``None``.
    """
    navegador = encontrar_navegador()
    if navegador:
        try:
            _preparar_perfil_midia()
            return subprocess.Popen(
                [
                    navegador,
                    f"--app={url}",
                    f"--user-data-dir={PERFIL_MIDIA}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--kiosk",
                    "--autoplay-policy=no-user-gesture-required",
                    # Fechar a janela encerra o processo; sem isto, a próxima
                    # noite começaria com o aviso de "restaurar páginas".
                    "--hide-crash-restore-bubble",
                    "--disable-session-crashed-bubble",
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
        except OSError:
            pass
    webbrowser.open(url)
    return None


if __name__ == "__main__":  # Permite testar a janela sem subir a interface inteira.
    destino = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/espaco/"
    print(abrir(destino, tela_cheia="--tela-cheia" in sys.argv))
