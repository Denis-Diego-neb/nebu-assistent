"""Ponte entre o dispatcher local e o protocolo MCP oficial."""

from __future__ import annotations

import json
import time
from copy import deepcopy

import anyio
from mcp import types
from mcp.server import Server, ServerRequestContext

from core.dispatcher import Dispatcher
from integrations.mcp.audit import MCPAuditLog


_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["name", "ok"],
    "properties": {
        "name": {"type": "string"},
        "ok": {"type": "boolean"},
        "message": {"type": "string"},
        "requires_confirmation": {"type": "boolean"},
    },
    "additionalProperties": True,
}


class NebulaMCPAdapter:
    """Converte schemas e resultados sem duplicar a logica das ferramentas."""

    def __init__(self, dispatcher: Dispatcher, audit: MCPAuditLog | None = None) -> None:
        self.dispatcher = dispatcher
        self.audit = audit if audit is not None else MCPAuditLog()

    async def list_tools(
        self,
        _context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        tools = [
            types.Tool(
                name=item["name"],
                description=item["description"],
                inputSchema=deepcopy(item["inputSchema"]),
                outputSchema=deepcopy(_OUTPUT_SCHEMA),
            )
            for item in self.dispatcher.list_tools()
        ]
        return types.ListToolsResult(tools=tools)

    async def call_tool(
        self,
        _context: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        started = time.perf_counter()
        name = params.name
        try:
            result = await anyio.to_thread.run_sync(
                self.dispatcher.call_tool,
                {"name": name, "arguments": params.arguments or {}},
            )
        except ValueError as exc:
            result = {"name": name, "ok": False, "message": str(exc)}
        except Exception:
            result = {
                "name": name,
                "ok": False,
                "message": "Falha interna ao executar a tool.",
            }
        duration_ms = round((time.perf_counter() - started) * 1_000)
        ok = bool(result.get("ok", False))
        message = str(result.get("message") or (
            "Tool executada." if ok else "A tool nao foi executada."
        ))
        self.audit.record(
            tool=name,
            ok=ok,
            duration_ms=duration_ms,
            message=message,
        )
        return types.CallToolResult(
            content=[types.TextContent(text=message)],
            structuredContent=result,
            isError=not ok,
        )


def create_mcp_server(
    dispatcher: Dispatcher,
    *,
    audit: MCPAuditLog | None = None,
) -> Server:
    adapter = NebulaMCPAdapter(dispatcher, audit)
    return Server(
        "nebula-tools",
        version="1.0.0",
        title="Nebula Tools",
        description="Catalogo modular de automacao e dispositivos da Nebula.",
        on_list_tools=adapter.list_tools,
        on_call_tool=adapter.call_tool,
    )


def result_as_text(result: types.CallToolResult) -> str:
    """Formato curto usado pelo console SSH e por diagnosticos locais."""
    structured = result.structured_content
    if isinstance(structured, dict):
        return json.dumps(structured, ensure_ascii=False, indent=2)
    return "\n".join(
        block.text for block in result.content if isinstance(block, types.TextContent)
    )


__all__ = ["NebulaMCPAdapter", "create_mcp_server", "result_as_text"]
