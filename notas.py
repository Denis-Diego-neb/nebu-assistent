"""Criação de notas locais para a Nebula."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def salvar_nota(texto: str) -> Path:
    pasta = Path.home() / "Documents" / "Notas Nebula"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / datetime.now().strftime("Nota_%Y-%m-%d_%H-%M-%S.txt")
    caminho.write_text(texto.strip() + "\n", encoding="utf-8")
    return caminho


def criar_e_abrir_nota(texto: str) -> Path:
    caminho = salvar_nota(texto)

    notepad = shutil.which("notepad.exe")
    if not notepad:
        raise RuntimeError("Bloco de Notas não encontrado no Windows.")
    subprocess.Popen([notepad, str(caminho)])
    return caminho
