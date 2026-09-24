"""Executa o catalogo modular da Nebula como servidor MCP por stdio.

Uso local: python -m scripts.run_mcp_server
Uso por SSH: ssh usuario@pc python -m scripts.run_mcp_server
"""

from __future__ import annotations

import anyio
from mcp.server.stdio import stdio_server

from core.bootstrap import criar_dispatcher
from integrations.mcp.server import create_mcp_server
from main import Nebula, Texto


async def serve() -> None:
    host = Nebula(Texto(), abrir_navegador=True)
    server = create_mcp_server(criar_dispatcher(host))
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        host.fechar()


def main() -> None:
    anyio.run(serve)


if __name__ == "__main__":
    main()
