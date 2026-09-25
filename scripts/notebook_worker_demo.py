"""Demo exigida pela secao 32 do MCP_GOAL.md.

1. O PC envia "return exactly {"ok": true}" como job isolado.
2. O notebook valida protocolo e capacidade.
3. O notebook entrega so esse prompt ao Qwen Edge.
4. O notebook devolve um JobResult tipado.
5. O PC correlaciona por job_id + trace_id.
6. A auditoria do notebook tem metadados, nao o prompt.

Uso no PC principal, com NEBULA_NOTEBOOK_WORKER_URL e NEBULA_WORKER_TOKEN definidos:
    .venv\\Scripts\\python.exe -m scripts.notebook_worker_demo
"""

from __future__ import annotations

import argparse
import json
import os

from core.capabilities.ticket import TicketSigner
from core.mcp.clients.notebook_worker import NotebookWorkerClient, NotebookWorkerError
from nebula_worker.protocol.envelope import build_generate_envelope

PROMPT = 'return exactly {"ok": true}'
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("NEBULA_NOTEBOOK_WORKER_URL", ""),
                        help="Ex.: http://100.78.67.81:8790/mcp")
    parser.add_argument("--timeout", type=int, default=180, help="Prazo do job em segundos.")
    args = parser.parse_args(argv)
    token = os.environ.get("NEBULA_WORKER_TOKEN", "")
    if not args.url or not token:
        print("Defina NEBULA_NOTEBOOK_WORKER_URL (ou --url) e NEBULA_WORKER_TOKEN.")
        return 2
    client = NotebookWorkerClient(args.url, token, TicketSigner.load())
    try:
        health = client.health_sync()
        print("health:", json.dumps(health, ensure_ascii=False))
        envelope = build_generate_envelope(
            PROMPT, output_format="json", schema=SCHEMA, temperature=0, seed=32,
            max_output_tokens=64, timeout_ms=args.timeout * 1000,
        )
        result = client.run_sync(envelope)
    except NotebookWorkerError as exc:
        print(f"Falhou: {exc.code}: {exc.message}")
        return 1
    print("result:", json.dumps(result, ensure_ascii=False))
    correlated = result["job_id"] == envelope["job_id"] and result["trace_id"] == envelope["trace_id"]
    ok = result["status"] == "completed" and result["output"]["payload"] == {"ok": True}
    print(f"correlacao job_id+trace_id: {'ok' if correlated else 'FALHOU'}")
    print(f"payload {{\"ok\": true}}: {'ok' if ok else 'diferente'}")
    print("Confira no notebook que a auditoria nao tem o prompt:")
    print(r"  %LOCALAPPDATA%\NebulaWorker\runtime\audit\worker.jsonl")
    return 0 if correlated and ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
