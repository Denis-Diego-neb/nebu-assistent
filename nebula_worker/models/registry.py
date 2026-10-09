"""Aliases logicos -> executores locais (INV-005).

O PC pede ``qwen_edge``; qual modelo do Ollama responde por esse nome e decisao
da configuracao do notebook, nunca do envelope.
"""

from __future__ import annotations

from nebula_worker.protocol.errors import ErrorCode, WorkerError


class ModelRegistry:
    def __init__(self, runners: dict) -> None:
        if not runners:
            raise ValueError("Configure ao menos um modelo habilitado.")
        self._runners = dict(runners)

    def get(self, alias: str):
        runner = self._runners.get(alias)
        if runner is None:
            raise WorkerError(ErrorCode.UNKNOWN_MODEL, "Alias de modelo nao configurado neste worker.")
        return runner

    def aliases(self) -> tuple[str, ...]:
        return tuple(sorted(self._runners))

    def operations(self) -> dict[str, list[str]]:
        return {alias: sorted(self._runners[alias].operations) for alias in self.aliases()}

    def availability(self) -> dict[str, dict[str, bool]]:
        return {alias: {"available": bool(self._runners[alias].is_available())}
                for alias in self.aliases()}
