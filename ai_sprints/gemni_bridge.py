"""Inspeciona a fila do Gemini Web e registra a resposta obtida no navegador."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.gemini import GeminiBrowserReviewGate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Lista revisoes aguardando Gemini")
    parser.add_argument("--show", metavar="JOB_ID", help="Mostra o prompt para o navegador")
    parser.add_argument("--record", metavar="JOB_ID", help="Registra a resposta do Gemini")
    parser.add_argument("--response-file", type=Path, help="Arquivo JSON retornado pelo Gemini")
    args = parser.parse_args()
    gate = GeminiBrowserReviewGate(PROJECT_ROOT)

    if args.list:
        gate.outbox.mkdir(parents=True, exist_ok=True)
        for request_path in sorted(gate.outbox.glob("*.json")):
            result = gate.result_path(request_path.stem)
            print(f"{request_path.stem}: {'respondido' if result.exists() else 'aguardando'}")
        return
    if args.show:
        request = json.loads(gate.request_path(args.show).read_text(encoding="utf-8"))
        print(request["prompt"])
        return
    if args.record:
        if args.response_file is None:
            raise SystemExit("--record exige --response-file.")
        response = args.response_file.read_text(encoding="utf-8")
        print(gate.record(args.record, response))
        return
    parser.error("use --list, --show ou --record")


if __name__ == "__main__":
    main()
