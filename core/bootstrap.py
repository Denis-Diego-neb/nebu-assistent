"""Liga as funções disponíveis ao executor na inicialização do host."""

from core.action_contracts import (
    ACOES_QWEN, ACOES_SEM_ARGUMENTO, LIMITES_ARGUMENTO, AcaoQwen, ContratoAcoes,
)
from core.dispatcher import Dispatcher
from core.legacy_actions import comando_canonico
from core.registry import Registry, Tool
from modules.desktop.actions import (
    DESKTOP_TOOL_NAMES,
    AcoesDesktop,
    registrar_tools_desktop,
)
from modules.desktop.media import (
    MIDIA_TOOL_NAMES,
    AcoesMidia,
    registrar_tools_midia,
)
from modules.iot.ambilight import (
    AMBILIGHT_TOOL_NAMES,
    AcoesAmbilight,
    registrar_tools_ambilight,
)
from modules.iot.lights import pedido_da_tool
from modules.racing.modes import (
    MODOS_CORRIDA_TOOL_NAMES,
    AcoesModosCorrida,
    registrar_tools_modos_corrida,
)


def criar_dispatcher(host, nomes=None) -> Dispatcher:
    registry = Registry()

    registrar_tools_ambilight(
        registry,
        AcoesAmbilight(
            iniciar=host._iniciar_modo_ambilight,
            parar=host._parar_modo_ambilight,
            status=host._informar_status_modo_ambilight,
        ),
        obter_ultima_mensagem=lambda: host._ultima_resposta,
        aguardando_resposta=lambda: host.aguardando_resposta,
        nomes=nomes,
    )
    registrar_tools_modos_corrida(
        registry,
        AcoesModosCorrida(
            rpm_iniciar=host._iniciar_modo_rpm,
            rpm_parar=host._parar_modo_rpm,
            rpm_status=host._informar_status_modo_rpm,
            boost_iniciar=host._iniciar_modo_boost,
            boost_parar=host._parar_modo_boost,
            boost_status=host._informar_status_modo_boost,
        ),
        obter_ultima_mensagem=lambda: host._ultima_resposta,
        aguardando_resposta=lambda: host.aguardando_resposta,
        nomes=nomes,
    )
    registrar_tools_desktop(
        registry,
        AcoesDesktop(
            abrir_aplicativo=lambda argumento: host._abrir_aplicativo_por_nome(argumento),
            fechar_aplicativo=lambda argumento: host._solicitar_fechar_aplicativo(argumento),
            tocar_youtube=lambda argumento: host.tocar_youtube(argumento),
            pesquisar_youtube=lambda argumento: host.pesquisar_youtube(argumento),
            pesquisar_google=lambda argumento: host.pesquisar_google(argumento),
            criar_nota=lambda argumento: host._escrever_no_bloco_de_notas(argumento),
        ),
        obter_ultima_mensagem=lambda: host._ultima_resposta,
        aguardando_resposta=lambda: host.aguardando_resposta,
        nomes=nomes,
    )
    registrar_tools_midia(
        registry,
        AcoesMidia(
            pausar=host._pausar_midia,
            continuar=host._continuar_midia,
            aumentar_volume=lambda: host._ajustar_volume_midia(aumentar=True),
            diminuir_volume=lambda: host._ajustar_volume_midia(aumentar=False),
        ),
        obter_ultima_mensagem=lambda: host._ultima_resposta,
        aguardando_resposta=lambda: host.aguardando_resposta,
        nomes=nomes,
    )

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
        # Somente frases FIXAS passam pelo adaptador, nunca argumentos do modelo.
        host._executar_local(comando_canonico(action))
        return {"ok": True, "message": host._ultima_resposta,
                "requires_confirmation": host.aguardando_resposta}

    for name in ACOES_QWEN:
        if nomes is not None and name not in nomes:
            continue
        if name in (AMBILIGHT_TOOL_NAMES | MODOS_CORRIDA_TOOL_NAMES
                    | DESKTOP_TOOL_NAMES | MIDIA_TOOL_NAMES):
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
