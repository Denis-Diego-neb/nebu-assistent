"""Executa chamadas explícitas; não interpreta texto nem consulta modelos."""

from threading import RLock

from core.registry import Registry


class Dispatcher:
    def __init__(self, registry: Registry, lock=None) -> None:
        self.registry = registry
        self._lock = lock if lock is not None else RLock()

    def list_tools(self) -> list[dict]:
        return self.registry.list_tools()

    def call_tool(self, call: dict) -> dict:
        return self.execute_plan([call])[0]

    def execute_plan(self, calls: list[dict]) -> list[dict]:
        if not isinstance(calls, list) or not 1 <= len(calls) <= 4:
            raise ValueError("Um plano deve conter entre uma e quatro tools.")
        # Valida o plano inteiro antes de provocar qualquer efeito.
        prepared = [self.registry.prepare(call) for call in calls]
        results = []
        with self._lock:
            for tool, arguments in prepared:
                try:
                    result = tool.handler(arguments)
                except Exception:
                    result = {"ok": False, "message": "Falha ao executar a tool."}
                results.append({"name": tool.name, **result})
                if not result.get("ok", False) or result.get("requires_confirmation"):
                    break
        return results
