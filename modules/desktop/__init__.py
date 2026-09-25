"""Ferramentas de aplicativos, notas, pesquisa e mídia no computador."""

from modules.desktop.actions import (
    DESKTOP_TOOL_NAMES,
    AcoesDesktop,
    registrar_tools_desktop,
)
from modules.desktop.media import (
    MIDIA_TOOL_NAMES,
    AcoesMidia,
    registrar_tools_midia,
)

__all__ = [
    "DESKTOP_TOOL_NAMES",
    "MIDIA_TOOL_NAMES",
    "AcoesDesktop",
    "AcoesMidia",
    "registrar_tools_desktop",
    "registrar_tools_midia",
]
