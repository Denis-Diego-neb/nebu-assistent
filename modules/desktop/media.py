"""Tools de reprodução e volume chamadas sem passar pelo parser de frases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.registry import Registry, Tool


MIDIA_TOOL_NAMES = frozenset({
    "pausar_midia",
    "continuar_midia",
    "aumentar_volume",
    "diminuir_volume",
})


@dataclass(frozen=True)
class AcoesMidia:
    pausar: Callable[[], bool | None]
    continuar: Callable[[], bool | None]
    aumentar_volume: Callable[[], bool | None]
    diminuir_volume: Callable[[], bool | None]


_DESCRICOES = {
    "pausar_midia": "Envia Play/Pause ao Windows para pausar a musica ou o video atual.",
    "continuar_midia": "Envia Play/Pause ao Windows para retomar a musica ou o video atual.",
    "aumentar_volume": "Aumenta o volume do player do YouTube aberto, sem mexer no Windows.",
    "diminuir_volume": "Diminui o volume do player do YouTube aberto, sem mexer no Windows.",
}


def _validar_sem_argumentos(arguments: dict) -> dict:
    if arguments != {"argumento": ""}:
        raise ValueError("Esta tool nao recebe argumentos; use argumento como texto vazio.")
    return {"argumento": ""}


def registrar_tools_midia(
    registry: Registry,
    acoes: AcoesMidia,
    *,
    obter_ultima_mensagem: Callable[[], str],
    aguardando_resposta: Callable[[], bool],
    nomes: set[str] | frozenset[str] | None = None,
) -> None:
    """Registra os quatro controles de mídia com callbacks do host."""
    callbacks = {
        "pausar_midia": acoes.pausar,
        "continuar_midia": acoes.continuar,
        "aumentar_volume": acoes.aumentar_volume,
        "diminuir_volume": acoes.diminuir_volume,
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["argumento"],
        "properties": {"argumento": {"type": "string", "enum": [""]}},
    }

    for name, callback in callbacks.items():
        if nomes is not None and name not in nomes:
            continue

        def execute(_arguments: dict, callback=callback) -> dict:
            if aguardando_resposta():
                return {
                    "ok": False,
                    "requires_confirmation": True,
                    "message": "Responda a pergunta pendente antes de executar outra tool.",
                }
            sucesso = callback()
            return {
                "ok": sucesso is not False,
                "message": obter_ultima_mensagem(),
                "requires_confirmation": aguardando_resposta(),
            }

        registry.register(Tool(
            name=name,
            description=_DESCRICOES[name],
            input_schema=schema,
            handler=execute,
            validate=_validar_sem_argumentos,
        ))


__all__ = ["MIDIA_TOOL_NAMES", "AcoesMidia", "registrar_tools_midia"]
