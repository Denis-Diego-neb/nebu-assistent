"""Configuração compartilhada do servidor de modelo da Nebula."""

from __future__ import annotations

import os


# O modelo roda no notebook para não usar a GPU deste PC.
OLLAMA_URL_PADRAO = "http://192.168.15.86:11434"


def qwen_ativa() -> bool:
    """Indica se a Qwen pode ser iniciada ou consultada pela Nebula."""
    valor = os.environ.get("NEBULA_QWEN_ENABLED", "0").strip().casefold()
    return valor in {"1", "true", "sim", "yes", "on"}


def obter_url_ollama() -> str:
    """Retorna a raiz da API nativa do Ollama, sem barra final."""
    return os.environ.get("NEBULA_OLLAMA_URL", OLLAMA_URL_PADRAO).rstrip("/")
