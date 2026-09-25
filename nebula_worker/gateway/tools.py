"""As seis tools MCP do notebook (secao 10 do GOAL) e nada alem delas.

Nao existe ``shell``, ``python``, leitura de arquivo ou IoT: o catalogo e fixo
aqui e um teste falha se alguem acrescentar outra tool sem revisar o GOAL.
"""

from __future__ import annotations

import json
from functools import partial

import anyio
import mcp_types as types
from mcp.server import Server

from nebula_worker import WORKER_VERSION
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ids import ULID_RE
from nebula_worker.worker.dispatcher import Dispatcher

_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
_JOB_ID = {
    "type": "object",
    "properties": {"job_id": {"type": "string", "pattern": ULID_RE.pattern}},
    "required": ["job_id"],
    "additionalProperties": False,
}
TOOLS: dict[str, tuple[str, dict]] = {
    "worker.health": ("Saude do worker e disponibilidade dos modelos locais.", _EMPTY),
    "worker.capabilities": ("Versoes de protocolo, modelos, operacoes e limites aceitos.", _EMPTY),
    "worker.submit": (
        "Enfileira um JobEnvelope assinado pelo PC. Devolve JobAccepted ou a rejeicao tipada.",
        {
            "type": "object",
            "properties": {"envelope": {"type": "object"}},
            "required": ["envelope"],
            "additionalProperties": False,
        },
    ),
    "worker.status": ("Estado atual de um job.", _JOB_ID),
    "worker.result": ("JobResult tipado de um job terminado.", _JOB_ID),
    "worker.cancel": ("Cancela um job enfileirado ou em execucao.", _JOB_ID),
}


def _arguments(name: str, arguments: dict) -> dict:
    expected = set(TOOLS[name][1].get("properties", {}))
    if set(arguments) != expected:
        raise WorkerError(ErrorCode.INVALID_ENVELOPE,
                          f"{name} espera exatamente os argumentos {sorted(expected)}.")
    return arguments


def _handler(dispatcher: Dispatcher, name: str, arguments: dict):
    args = _arguments(name, arguments)
    if name == "worker.health":
        return dispatcher.health
    if name == "worker.capabilities":
        return dispatcher.capabilities
    if name == "worker.submit":
        return partial(dispatcher.submit, args["envelope"])
    if name == "worker.status":
        return partial(dispatcher.status, args["job_id"])
    if name == "worker.result":
        return partial(dispatcher.result, args["job_id"])
    if name == "worker.cancel":
        return partial(dispatcher.cancel, args["job_id"])
    raise WorkerError(ErrorCode.UNSUPPORTED_OPERATION, "Tool desconhecida neste worker.")


def create_worker_server(dispatcher: Dispatcher) -> Server:
    async def list_tools(_context, _params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=name, description=description, inputSchema=schema)
            for name, (description, schema) in TOOLS.items()
        ])

    async def call_tool(_context, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            if params.name not in TOOLS:
                raise WorkerError(ErrorCode.UNSUPPORTED_OPERATION, "Tool desconhecida neste worker.")
            call = _handler(dispatcher, params.name, dict(params.arguments or {}))
            # O dispatcher bloqueia (locks, espera curta no cancel, health do
            # Ollama); fora do loop de eventos ele nao trava as outras requisicoes.
            payload = await anyio.to_thread.run_sync(call)
            is_error = payload.get("status") == "rejected"
        except WorkerError as exc:
            payload, is_error = {"error": exc.to_dict()}, True
        except Exception as exc:  # noqa: BLE001 - nenhum traceback sai do notebook
            payload = {"error": WorkerError(
                ErrorCode.INTERNAL_ERROR, f"Falha interna do worker ({type(exc).__name__}).").to_dict()}
            is_error = True
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(payload, ensure_ascii=False))],
            structuredContent=payload,
            isError=is_error,
        )

    return Server(
        "nebula-worker",
        version=WORKER_VERSION,
        title="Nebula Notebook Worker",
        description="Worker restrito: executa jobs tipados do PC no Qwen Edge local.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
