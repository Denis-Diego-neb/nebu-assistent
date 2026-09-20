"""Catálogo de funções: o registro não conhece dispositivos ou modelos."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], dict]
    validate: Callable[[dict], dict]


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name or tool.name in self._tools:
            raise ValueError(f"Tool vazia ou duplicada: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if not isinstance(name, str) or name not in self._tools:
            raise ValueError("Tool não registrada.")
        return self._tools[name]

    def list_tools(self) -> list[dict]:
        return [
            {"name": tool.name, "description": tool.description,
             "inputSchema": deepcopy(tool.input_schema)}
            for tool in self._tools.values()
        ]

    def prepare(self, call: dict) -> tuple[Tool, dict]:
        if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
            raise ValueError("Use name e arguments para chamar uma tool.")
        if not isinstance(call["arguments"], dict):
            raise ValueError("Os argumentos devem ser um objeto.")
        tool = self.get(call["name"])
        return tool, tool.validate(deepcopy(call["arguments"]))
