"""Console interativo que acessa o servidor MCP da Nebula por SSH."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import PureWindowsPath

import anyio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from integrations.mcp.server import result_as_text


DEFAULT_PROJECT = r"C:\Users\Nebullar\Documents\assistente virtual"


def _remote_command(project: str) -> str:
    python = str(PureWindowsPath(project) / ".venv" / "Scripts" / "python.exe")
    # cmd.exe entende aspas duplas para caminhos com espaco. Os valores sao
    # configuracao local do operador, e nunca argumentos vindos de uma tool.
    return f'cd /d "{project}" && "{python}" -m scripts.run_mcp_server'


def build_transport(destination: str, project: str) -> StdioServerParameters:
    return StdioServerParameters(
        command="ssh.exe",
        args=[destination, "cmd.exe", "/d", "/s", "/c", _remote_command(project)],
    )


async def console(destination: str, project: str) -> None:
    async with Client(build_transport(destination, project)) as client:
        catalog = await client.list_tools()
        print(f"Conectado ao MCP da Nebula: {len(catalog.tools)} tools.")
        print("Comandos: tools | call NOME {JSON} | exit")
        while True:
            try:
                line = await anyio.to_thread.run_sync(input, "mcp> ")
            except (EOFError, KeyboardInterrupt):
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
            try:
                parts = shlex.split(line, posix=False)
                if len(parts) < 2 or parts[0].casefold() != "call":
                    raise ValueError("Use: call NOME {JSON}")
                name = parts[1].strip('"')
                raw = line[line.find(parts[1]) + len(parts[1]):].strip()
                arguments = json.loads(raw) if raw else {"argumento": ""}
                if not isinstance(arguments, dict):
                    raise ValueError("Os argumentos precisam ser um objeto JSON.")
                result = await client.call_tool(name, arguments)
                print(result_as_text(result))
            except (ValueError, json.JSONDecodeError) as exc:
                print(f"Entrada invalida: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="Destino SSH, por exemplo Nebullar@192.168.15.12")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Pasta do projeto no PC MCP")
    args = parser.parse_args()
    anyio.run(console, args.destination, args.project)


if __name__ == "__main__":
    main()
