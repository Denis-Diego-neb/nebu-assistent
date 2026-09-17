"""Captura de tela para a Nebula."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def capturar_tela() -> Path:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError(
            "O recurso de captura de tela não está instalado."
        ) from exc

    pasta = Path.home() / "Pictures" / "Capturas Nebula"
    # Em instalações em português, a pasta real pode se chamar Imagens, mas o
    # caminho Pictures continua sendo reconhecido pelo Windows.
    pasta.mkdir(parents=True, exist_ok=True)
    nome = datetime.now().strftime("Nebula_%Y-%m-%d_%H-%M-%S.png")
    caminho = pasta / nome
    imagem = ImageGrab.grab(all_screens=True)
    imagem.save(caminho, "PNG")
    return caminho
