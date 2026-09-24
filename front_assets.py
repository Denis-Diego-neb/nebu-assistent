"""Acesso aos arquivos do front espacial compartilhado (``nebula_front/``).

O mesmo conjunto de HTML, CSS e JS é servido pelo painel do PC (``/espaco``),
pelo console do hub no notebook (``/hub/``) e copiado para os assets do APK.
Este módulo resolve onde a pasta está — repositório, pasta do executável ou
bundle do PyInstaller — e devolve os bytes já com o Content-Type correto.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FRONT_DIRNAME = "nebula_front"
NOME_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json; charset=utf-8",
}


def _candidatos() -> list[Path]:
    bases: list[Path] = []
    empacotado = getattr(sys, "_MEIPASS", "")
    if empacotado:
        bases.append(Path(empacotado))
    try:
        executavel = Path(sys.executable).resolve().parent
        bases.extend((executavel, executavel.parent))
    except (OSError, ValueError):
        pass
    modulo = Path(__file__).resolve().parent
    bases.extend((modulo, modulo.parent))
    vistos: list[Path] = []
    for base in bases:
        destino = base / FRONT_DIRNAME
        if destino not in vistos:
            vistos.append(destino)
    return vistos


def front_dir() -> Path | None:
    """Primeira pasta ``nebula_front`` encontrada, ou ``None`` se não houver."""
    for destino in _candidatos():
        if (destino / "index.html").is_file():
            return destino
    return None


def carregar(nome: str) -> tuple[bytes, str] | None:
    """Devolve ``(conteudo, content_type)`` de um arquivo do front.

    Aceita apenas nomes simples de arquivo: nada de subpastas, ``..`` ou
    caminhos absolutos, já que o nome chega pela URL.
    """
    if not NOME_VALIDO.fullmatch(nome or ""):
        return None
    tipo = TIPOS.get(Path(nome).suffix.lower())
    if tipo is None:
        return None
    pasta = front_dir()
    if pasta is None:
        return None
    arquivo = pasta / nome
    try:
        if not arquivo.is_file() or arquivo.resolve().parent != pasta.resolve():
            return None
        return arquivo.read_bytes(), tipo
    except OSError:
        return None


INDISPONIVEL = (
    "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
    "<title>Nebula</title></head><body style=\"font-family:system-ui;background:#07070c;"
    "color:#d9d4e6;margin:0;display:grid;place-items:center;height:100vh;text-align:center\">"
    "<div><h1 style=\"font-weight:300\">Front espacial não encontrado</h1>"
    "<p>A pasta <code>nebula_front</code> não foi empacotada com esta versão.</p></div>"
    "</body></html>"
)
