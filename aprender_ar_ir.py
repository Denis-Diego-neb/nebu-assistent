"""Assistente curto para ensinar os botoes de energia ao Smart IR da Nebula."""

from __future__ import annotations

import argparse

from ar_ir_direto import ControleArDireto, ErroAr


ROTULOS = {
    "power_on": "LIGAR",
    "power_off": "DESLIGAR",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("button", choices=tuple(ROTULOS))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    print(
        f"Aponte o controle original para o Smart IR e aperte {ROTULOS[args.button]} uma vez.",
        flush=True,
    )
    try:
        ControleArDireto().aprender(args.button, args.timeout)
    except ErroAr as exc:
        print(f"ERRO: {exc}", flush=True)
        return 1
    print(f"OK: botao {ROTULOS[args.button]} aprendido.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
