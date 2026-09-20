"""Inicializa um executor sem interface e sem consultar a Qwen.

Uso: python -m scripts.run_tool_server --host 0.0.0.0 --port 8767
Token: variável NEBULA_TOOL_TOKEN. O módulo de transporte não conhece a Nebula.
"""

import argparse
import os

from main import Nebula, Texto
from core.action_contracts import ACOES_QWEN
from core.bootstrap import criar_dispatcher
from services.tool_server import ToolServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    token = os.environ.get("NEBULA_TOOL_TOKEN", "")
    if len(token) < 24:
        parser.error("Defina NEBULA_TOOL_TOKEN com pelo menos 24 caracteres antes de iniciar.")
    host = Nebula(Texto())
    # Este primeiro nó publica somente o módulo migrado. Qwen e encaminhamento
    # ao Codex pertencem ao host, não ao catálogo do nó de execução do abajur.
    executor = criar_dispatcher(host, nomes={name for name in ACOES_QWEN if name.startswith("abajur_")})
    try:
        with ToolServer((args.host, args.port), executor, token) as server:
            print(f"Executor de tools ativo em {args.host}:{args.port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        host.fechar()


if __name__ == "__main__":
    main()
