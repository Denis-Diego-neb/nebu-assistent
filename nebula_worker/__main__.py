"""Inicia o worker: ``python -m nebula_worker --config worker.json``.

Tambem e o ponto de entrada do NebulaWorker.exe. Imports absolutos de proposito:
o PyInstaller executa este arquivo como ``__main__``, sem pacote pai.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from nebula_worker import WORKER_VERSION
from nebula_worker.config import ConfigError, WorkerConfig, default_config_path, load_config
from nebula_worker.models.ollama_client import OllamaRunner
from nebula_worker.protocol.version import PROTOCOL_VERSION


def _emit(text: str) -> None:
    # No executavel sem console, stdout e None.
    if sys.stdout is not None:
        print(text, flush=True)


class _OmitPayload(logging.Filter):
    """Tira argumentos e traceback dos registros de bibliotecas de terceiros.

    Erro de validacao do pydantic, por exemplo, cita um trecho da entrada; num
    pedido malformado isso levaria parte do prompt para o disco (INV-007). Fica
    a mensagem fixa e o tipo da excecao, suficientes para diagnosticar.
    """

    THIRD_PARTY = ("mcp", "uvicorn", "starlette", "httpx", "anyio", "sse_starlette")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.split(".", 1)[0] in self.THIRD_PARTY:
            kind = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None
            record.msg = str(record.msg) + (f" [{kind}]" if kind else "")
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def _configure_logging(config: WorkerConfig) -> None:
    # Log de servico: partida, parada e erros de infraestrutura. Nenhum payload
    # passa por aqui; o registro de jobs e a auditoria de metadados.
    log_dir = config.runtime_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "worker.log", maxBytes=2_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.addFilter(_OmitPayload())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # O SDK MCP registra detalhes de requisicoes em DEBUG/INFO; so avisos interessam.
    for noisy in ("mcp", "uvicorn.access", "httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _check(config: WorkerConfig) -> int:
    report = {
        "worker_version": WORKER_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "bind": f"{config.bind_host}:{config.port}",
        "tls": bool(config.tls_certfile),
        "allowed_clients": [str(network) for network in config.allowed_clients],
        "trusted_keys": sorted(config.trusted_keys),
        "models": {},
    }
    healthy = True
    for model in config.models:
        runner = OllamaRunner(model.base_url, model.model, options=model.options)
        available = runner.is_available()
        healthy = healthy and available
        report["models"][model.alias] = {"model": model.model, "ollama_disponivel": available}
    _emit(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if healthy else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nebula_worker", description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config_path(),
                        help="Arquivo JSON de configuracao do worker.")
    parser.add_argument("--check", action="store_true",
                        help="Valida a configuracao e o Ollama local, sem abrir a porta.")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        _emit(f"nebula-worker {WORKER_VERSION} (protocolo {PROTOCOL_VERSION})")
        return 0
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        _emit(f"Configuracao invalida: {exc}")
        return 2
    if args.check:
        return _check(config)
    _configure_logging(config)
    from nebula_worker.server import serve

    try:
        serve(config)
    except Exception:  # noqa: BLE001 - registra a causa antes de o processo terminar
        logging.getLogger("nebula_worker").exception("O worker terminou com erro.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
