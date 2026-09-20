"""Liga as funções disponíveis ao executor na inicialização do host."""

from core.action_contracts import (
    ACOES_QWEN, ACOES_SEM_ARGUMENTO, LIMITES_ARGUMENTO, AcaoQwen, ContratoAcoes,
)
from core.dispatcher import Dispatcher
from core.legacy_actions import comando_canonico
from core.registry import Registry, Tool
from modules.iot.lights import pedido_da_tool


def criar_dispatcher(host, nomes=None) -> Dispatcher:
    registry = Registry()

    def validate(name, arguments):
        if set(arguments) != {"argumento"}:
            raise ValueError("Informe somente argumento, usando texto vazio quando não houver valor.")
        try:
            action = ContratoAcoes._validar_acao({"acao": name, **arguments})
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        return {"argumento": action.argumento}

    def execute(name, arguments):
        if host.aguardando_resposta:
            return {"ok": False, "requires_confirmation": True,
                    "message": "Responda à pergunta pendente antes de executar outra tool."}
        action = AcaoQwen(name, arguments["argumento"])
        if name == "encaminhar_codex":
            return host.codex.encaminhar(action.argumento)
        pedido = pedido_da_tool(action.acao, action.argumento)
        if pedido is not None:
            host._executar_pedidos_abajur([pedido], comando_canonico(action))
            return {"ok": host._ultimo_comando_abajur_falho is None,
                    "message": host._ultima_resposta}
        diretas = {
            "abrir_aplicativo": lambda: host._abrir_aplicativo_por_nome(action.argumento.lower()),
            "fechar_aplicativo": lambda: host._solicitar_fechar_aplicativo(action.argumento.lower()),
            "tocar_youtube": lambda: host.tocar_youtube(action.argumento),
            "pesquisar_youtube": lambda: host.pesquisar_youtube(action.argumento),
            "pesquisar_google": lambda: host.pesquisar_google(action.argumento),
            "criar_nota": lambda: host._escrever_no_bloco_de_notas(action.argumento),
        }
        if name in diretas:
            diretas[name]()
        else:
            # Somente frases FIXAS passam pelo adaptador, nunca argumentos do modelo.
            host._executar_local(comando_canonico(action))
        return {"ok": True, "message": host._ultima_resposta,
                "requires_confirmation": host.aguardando_resposta}

    for name in ACOES_QWEN:
        if nomes is not None and name not in nomes:
            continue
        schema = {"type": "object", "additionalProperties": False,
                  "required": ["argumento"], "properties": {"argumento": {
                      "type": "string", "maxLength": LIMITES_ARGUMENTO.get(name, 0),
                  }}}
        if name in ACOES_SEM_ARGUMENTO:
            schema["properties"]["argumento"]["enum"] = [""]
        else:
            schema["properties"]["argumento"]["minLength"] = 1
        description = name.replace("_", " ")
        if name == "encaminhar_codex":
            description = "Encaminha dúvidas e pedidos sobre programação para a conversa com Codex."
        registry.register(Tool(
            name, description, schema,
            lambda arguments, name=name: execute(name, arguments),
            lambda arguments, name=name: validate(name, arguments),
        ))
    return Dispatcher(registry, host._execution_lock)
