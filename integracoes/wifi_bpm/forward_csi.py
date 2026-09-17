"""Encaminha JSONL de um capturador CSI real para a Nebula autenticada."""
import argparse
import json
import os
import sys
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--token-env", default="NEBULA_POWER_TOKEN")
    args = parser.parse_args()
    address = urlparse(args.url)
    if address.scheme not in {"http", "https"} or not address.hostname or address.username or address.query or address.fragment:
        parser.error("Use o endereço HTTP(S) da sua Nebula, sem credenciais na URL.")
    token = os.getenv(args.token_env, "")
    if not token:
        parser.error("Defina a variável de ambiente com a credencial do hub Nebula.")
    opener = build_opener(NoRedirect)
    while True:
        line = sys.stdin.buffer.readline(100_001)
        if not line:
            break
        if len(line) > 100_000:
            raise SystemExit("Amostra excedeu o limite de 100 KB.")
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict) or "source" not in payload or not ({"csi", "samples"} & payload.keys()):
                raise ValueError("Formato CSI ausente")
            request = Request(args.url.rstrip("/") + "/api/wifi-bpm/ingest", data=line,
                headers={"Content-Type": "application/json", "X-Nebula-Power-Token": token}, method="POST")
            with opener.open(request, timeout=5) as response:
                state = json.loads(response.read(100_000))
            print(json.dumps({key: state.get(key) for key in ("status", "bpm", "quality", "message")}, ensure_ascii=False), flush=True)
        except Exception:
            # Não continuar após perda de amostras sem sinalizar o problema.
            raise SystemExit("Coleta interrompida: confira formato, relógio, conexão e credencial. Consulte o status na Nebula.")


if __name__ == "__main__":
    main()
