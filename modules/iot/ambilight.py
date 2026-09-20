"""Tools e adaptadores do Ambilight, independentes da interface da Nebula."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from core.registry import Registry, Tool


AMBILIGHT_TOOL_NAMES = frozenset({
    "modo_ambilight_iniciar",
    "modo_ambilight_parar",
    "modo_ambilight_status",
})


class TecladoAmbilight(Protocol):
    ambilight_multizona_seguro: bool

    def enviar_rgb(self, red: int, green: int, blue: int) -> None: ...

    def enviar_zonas(self, colors) -> None: ...


@dataclass(frozen=True)
class SaidasTecladoAmbilight:
    secundaria: Callable[[int, int, int], None] | None = None
    zonas: Callable | None = None
    multizona: bool = False


def selecionar_saidas_teclado(
    teclado: TecladoAmbilight | None,
) -> SaidasTecladoAmbilight:
    """Escolhe o transporte de cor sem conhecer a implementacao do host.

    Drivers que declaram atualizacao multizona segura recebem os quadros por
    zona. Os demais usam uma cor uniforme, evitando regravar o frame completo
    de LEDs em cada atualizacao do Ambilight.
    """
    if teclado is None:
        return SaidasTecladoAmbilight()
    if bool(getattr(teclado, "ambilight_multizona_seguro", False)):
        return SaidasTecladoAmbilight(zonas=teclado.enviar_zonas, multizona=True)
    return SaidasTecladoAmbilight(secundaria=teclado.enviar_rgb)


@dataclass(frozen=True)
class AcoesAmbilight:
    iniciar: Callable[[], bool | None]
    parar: Callable[[], bool | None]
    status: Callable[[], bool | None]


_DESCRICOES = {
    "modo_ambilight_iniciar": "Inicia a iluminacao que acompanha as cores da tela.",
    "modo_ambilight_parar": "Para o Ambilight e restaura a iluminacao anterior.",
    "modo_ambilight_status": "Informa o estado atual do Ambilight.",
}


def _validar_sem_argumentos(arguments: dict) -> dict:
    if arguments != {"argumento": ""}:
        raise ValueError("Esta tool nao recebe argumentos; use argumento como texto vazio.")
    return {"argumento": ""}


def registrar_tools_ambilight(
    registry: Registry,
    acoes: AcoesAmbilight,
    *,
    obter_ultima_mensagem: Callable[[], str],
    aguardando_resposta: Callable[[], bool],
    nomes: set[str] | frozenset[str] | None = None,
) -> None:
    """Registra chamadas tipadas sem converter a tool novamente em texto."""
    callbacks = {
        "modo_ambilight_iniciar": acoes.iniciar,
        "modo_ambilight_parar": acoes.parar,
        "modo_ambilight_status": acoes.status,
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
    "AMBILIGHT_TOOL_NAMES",
    "AcoesAmbilight",
    "SaidasTecladoAmbilight",
    "registrar_tools_ambilight",
    "selecionar_saidas_teclado",
]
