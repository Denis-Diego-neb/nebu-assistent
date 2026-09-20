"""Clientes usados pelas sprints locais de arquitetura.

Importar este pacote nao inicia modelos nem envia prompts. A composicao dos
agentes pertence ao orquestrador da sprint.
"""

from core.agents.ollama_client import OllamaClient

__all__ = ["OllamaClient"]
