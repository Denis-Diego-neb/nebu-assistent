"""Tools tipadas para iniciar, parar e consultar os modos RPM e boost."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.registry import Registry, Tool


MODOS_CORRIDA_TOOL_NAMES = frozenset({
    "modo_rpm_iniciar",
    "modo_rpm_parar",
    "modo_rpm_status",
    "modo_boost_iniciar",
    "modo_boost_parar",
    "modo_boost_status",
})


@dataclass(frozen=True)
class AcoesModosCorrida:
    rpm_iniciar: Callable[[], bool | None]
    rpm_parar: Callable[[], bool | None]
    rpm_status: Callable[[], bool | None]
    boost_iniciar: Callable[[], bool | None]
    boost_parar: Callable[[], bool | None]
    boost_status: Callable[[], bool | None]


_DESCRICOES = {
    "modo_rpm_iniciar": "Inicia o efeito de iluminacao ligado a telemetria de RPM.",
    "modo_rpm_parar": "Para o efeito de RPM e libera os dispositivos usados.",
    "modo_rpm_status": "Informa o estado e a telemetria atual do modo RPM.",
    "modo_boost_iniciar": "Inicia o efeito de iluminacao ligado ao boost do jogo.",
    "modo_boost_parar": "Para o efeito de boost e restaura a iluminacao anterior.",
    "modo_boost_status": "Informa o estado e a leitura atual do modo boost.",
}


def _validar_sem_argumentos(arguments: dict) -> dict:
    if arguments != {"argumento": ""}:
        raise ValueError("Esta tool nao recebe argumentos; use argumento como texto vazio.")
    return {"argumento": ""}


def registrar_tools_modos_corrida(
    registry: Registry,
    acoes: AcoesModosCorrida,
    *,
    obter_ultima_mensagem: Callable[[], str],
    aguardando_resposta: Callable[[], bool],
    nomes: set[str] | frozenset[str] | None = None,
) -> None:
    """Registra os seis comandos sem reconverter a chamada em linguagem natural."""
    callbacks = {
        "modo_rpm_iniciar": acoes.rpm_iniciar,
        "modo_rpm_parar": acoes.rpm_parar,
        "modo_rpm_status": acoes.rpm_status,
        "modo_boost_iniciar": acoes.boost_iniciar,
        "modo_boost_parar": acoes.boost_parar,
        "modo_boost_status": acoes.boost_status,
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


__all__ = [
    "MODOS_CORRIDA_TOOL_NAMES",
    "AcoesModosCorrida",
    "registrar_tools_modos_corrida",
]
