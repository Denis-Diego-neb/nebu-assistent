"""Console humano para inspecionar o servidor MCP da Nebula.

Este processo roda no PC servidor. Ele pode ser iniciado por uma sessao SSH e
usa o transporte MCP em memoria, mantendo a linha interativa livre para o
operador.
"""

from __future__ import annotations

import json

import anyio
from mcp.client import Client

from core.bootstrap import criar_dispatcher
from integrations.mcp.server import create_mcp_server, result_as_text
from main import Nebula, Texto


async def run_console() -> None:
    host = Nebula(Texto(), abrir_navegador=True)
    server = create_mcp_server(criar_dispatcher(host))
    try:
        async with Client(server) as client:
            catalog = await client.list_tools()
            print(f"Nebula MCP conectado: {len(catalog.tools)} tools.")
            print('Use "tools", "call NOME {JSON}" ou "exit".')
            while True:
                try:
                    line = await anyio.to_thread.run_sync(input, "mcp> ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                line = line.strip()
                if not line:
                    continue
                if line.casefold() in {"exit", "quit", "sair"}:
                    break
                if line.casefold() == "tools":
                    catalog = await client.list_tools(cache_mode="reload")
                    for tool in catalog.tools:
                        print(f"{tool.name:<32} {tool.description or ''}")
                    continue
                if not line.casefold().startswith("call "):
                    print("Use: call NOME {JSON}")
                    continue
                try:
                    rest = line[5:].lstrip()
                    name, separator, raw = rest.partition(" ")
                    if not name:
                        raise ValueError("Informe o nome da tool.")
                    arguments = json.loads(raw) if separator and raw.strip() else {"argumento": ""}
                    if not isinstance(arguments, dict):
                        raise ValueError("Os argumentos precisam ser um objeto JSON.")
                    result = await client.call_tool(name, arguments)
                    print(result_as_text(result))
                except (ValueError, json.JSONDecodeError) as exc:
                    print(f"Entrada invalida: {exc}")
    finally:
        host.fechar()


def main() -> None:
    anyio.run(run_console)


if __name__ == "__main__":
    main()
