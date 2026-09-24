"""Tools de desktop com argumentos validados antes de alcançar o host."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.registry import Registry, Tool


DESKTOP_TOOL_NAMES = frozenset({
    "abrir_aplicativo",
    "fechar_aplicativo",
    "tocar_youtube",
    "pesquisar_youtube",
    "pesquisar_google",
    "criar_nota",
})


@dataclass(frozen=True)
class AcoesDesktop:
    abrir_aplicativo: Callable[[str], bool | None]
    fechar_aplicativo: Callable[[str], bool | None]
    tocar_youtube: Callable[[str], bool | None]
    pesquisar_youtube: Callable[[str], bool | None]
    pesquisar_google: Callable[[str], bool | None]
    criar_nota: Callable[[str], bool | None]


_LIMITES = {
    "abrir_aplicativo": 200,
    "fechar_aplicativo": 200,
    "tocar_youtube": 500,
    "pesquisar_youtube": 500,
    "pesquisar_google": 500,
    "criar_nota": 4_000,
}

_DESCRICOES = {
    "abrir_aplicativo": "Abre um aplicativo instalado pelo nome informado.",
    "fechar_aplicativo": "Solicita confirmacao antes de fechar aplicativos pelo nome.",
    "tocar_youtube": "Procura um video e abre o primeiro resultado do YouTube.",
    "pesquisar_youtube": "Abre uma pesquisa no YouTube.",
    "pesquisar_google": "Abre uma pesquisa no Google.",
    "criar_nota": "Salva o texto informado e abre a nota no Bloco de Notas.",
}


def _validar_argumento(arguments: dict, *, limite: int) -> dict:
    if set(arguments) != {"argumento"} or not isinstance(arguments.get("argumento"), str):
        raise ValueError("Informe somente argumento como texto.")
    argumento = arguments["argumento"].strip()
    if not argumento or len(argumento) > limite:
        raise ValueError(f"O argumento deve conter entre 1 e {limite} caracteres.")
    return {"argumento": argumento}


def registrar_tools_desktop(
    registry: Registry,
    acoes: AcoesDesktop,
    *,
    obter_ultima_mensagem: Callable[[], str],
    aguardando_resposta: Callable[[], bool],
    nomes: set[str] | frozenset[str] | None = None,
) -> None:
    """Registra operacoes de desktop sem passar por interpretacao de frases."""
    callbacks = {
        "abrir_aplicativo": acoes.abrir_aplicativo,
        "fechar_aplicativo": acoes.fechar_aplicativo,
        "tocar_youtube": acoes.tocar_youtube,
        "pesquisar_youtube": acoes.pesquisar_youtube,
        "pesquisar_google": acoes.pesquisar_google,
        "criar_nota": acoes.criar_nota,
    }

    for name, callback in callbacks.items():
        if nomes is not None and name not in nomes:
            continue
        limite = _LIMITES[name]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["argumento"],
            "properties": {
                "argumento": {"type": "string", "minLength": 1, "maxLength": limite},
            },
        }

        def validate(arguments: dict, limite=limite) -> dict:
            return _validar_argumento(arguments, limite=limite)

        def execute(arguments: dict, callback=callback, name=name) -> dict:
            if aguardando_resposta():
                return {
                    "ok": False,
                    "requires_confirmation": True,
                    "message": "Responda a pergunta pendente antes de executar outra tool.",
                }
            argumento = arguments["argumento"]
            if name in {"abrir_aplicativo", "fechar_aplicativo"}:
                argumento = argumento.lower()
            sucesso = callback(argumento)
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
            validate=validate,
        ))


__all__ = ["DESKTOP_TOOL_NAMES", "AcoesDesktop", "registrar_tools_desktop"]
