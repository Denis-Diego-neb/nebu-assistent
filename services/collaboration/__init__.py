"""Coordenação persistente entre agentes, sem dependência da interface."""

from .store import CollaborationStore, Conflict
from .facade import snapshot, mensagem_usuario, definir_objetivo, propor, executar, pausar

__all__ = ["CollaborationStore", "Conflict", "snapshot", "mensagem_usuario",
           "definir_objetivo", "propor", "executar", "pausar"]
