"""Gera a chave de assinatura do PC e mostra o que vai para o worker.json do notebook.

Uso no PC principal:
    .venv\\Scripts\\python.exe -m scripts.notebook_worker_keys           # cria a chave se faltar
    .venv\\Scripts\\python.exe -m scripts.notebook_worker_keys --token   # tambem sugere um token novo
    .venv\\Scripts\\python.exe -m scripts.notebook_worker_keys --rotate  # troca a chave (invalida a antiga)

A chave privada nunca sai do PC; o notebook recebe so a publica.
"""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from core.capabilities.ticket import TicketSigner, default_key_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key-file", type=Path, default=None, help="Caminho da chave privada no PC.")
    parser.add_argument("--rotate", action="store_true", help="Substitui a chave existente.")
    parser.add_argument("--token", action="store_true", help="Gera tambem um NEBULA_WORKER_TOKEN novo.")
    args = parser.parse_args(argv)
    path = args.key_file or default_key_file()
    if path.exists() and not args.rotate:
        signer = TicketSigner.load(path)
        print(f"Chave existente: {path}")
    else:
        signer = TicketSigner.generate(path, overwrite=args.rotate)
        print(f"Chave {'rotacionada' if args.rotate else 'criada'}: {path}")
    print(f"key_id: {signer.key_id}")
    print("\nCole no worker.json do notebook:")
    print(json.dumps({"trusted_keys": {signer.key_id: signer.public_key_text}}, indent=2))
    if args.token:
        token = secrets.token_urlsafe(36)
        print("\nToken novo (defina o MESMO valor no PC e no notebook, fora do repositorio):")
        print(f'  setx NEBULA_WORKER_TOKEN "{token}"')
        print("Depois reabra os terminais/servicos para herdarem a variavel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
