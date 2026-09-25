"""Composicao e ciclo de vida do worker: monta as pecas e abre a porta HTTP."""

from __future__ import annotations

import logging

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from nebula_worker.capabilities.validator import TicketValidator
from nebula_worker.config import WorkerConfig
from nebula_worker.gateway.guard import GatewayGuard
from nebula_worker.gateway.tools import create_worker_server
from nebula_worker.models.ollama_client import OllamaRunner
from nebula_worker.models.registry import ModelRegistry
from nebula_worker.observability.audit import AuditLog
from nebula_worker.sandbox.workspace import Workspaces
from nebula_worker.worker.dispatcher import Dispatcher

LOG = logging.getLogger("nebula_worker")
MCP_PATH = "/mcp"


def build_dispatcher(config: WorkerConfig, *, runner_factory=OllamaRunner) -> tuple[Dispatcher, AuditLog]:
    runtime = config.runtime_dir
    audit = AuditLog(runtime / "audit" / "worker.jsonl")
    runners = {
        model.alias: runner_factory(
            model.base_url, model.model, options=model.options, keep_alive=model.keep_alive,
            # Folga para texto que o filtro ainda vai reduzir (cerca de Markdown, espacos).
            max_response_bytes=config.limits.max_result_bytes * 2,
        )
        for model in config.models
    }
    validator = TicketValidator(
        config.trusted_keys, config.allowed_scopes,
        max_ttl_seconds=config.limits.max_ticket_ttl_seconds,
        clock_skew_seconds=config.limits.clock_skew_seconds,
        replay_file=runtime / "replay.json",
    )
    dispatcher = Dispatcher(
        models=ModelRegistry(runners), validator=validator,
        workspaces=Workspaces(runtime / "jobs"), audit=audit, limits=config.limits,
    )
    return dispatcher, audit


def build_app(config: WorkerConfig, dispatcher: Dispatcher, audit: AuditLog):
    server = create_worker_server(dispatcher)
    # Unicode escapado pode ocupar ate 6 bytes por caractere no JSON.
    body_limit = min(16_000_000, config.limits.max_input_chars * 6 + 65_536)
    inner = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        json_response=True,
        stateless_http=True,
        host=config.bind_host,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=config.allowed_host_headers,
            # Nenhuma origem de navegador: o unico cliente e o PC, que nao envia Origin.
            allowed_origins=[],
        ),
        max_request_body_size=body_limit,
    )
    return GatewayGuard(inner, token=config.token, allowed_clients=config.allowed_clients,
                        requests_per_minute=config.requests_per_minute, audit=audit)


def uvicorn_config(config: WorkerConfig, app) -> uvicorn.Config:
    return uvicorn.Config(
        app,
        host=config.bind_host,
        port=config.port,
        log_config=None,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        date_header=False,
        lifespan="on",
        timeout_keep_alive=5,
        limit_concurrency=64,
        ssl_certfile=str(config.tls_certfile) if config.tls_certfile else None,
        ssl_keyfile=str(config.tls_keyfile) if config.tls_keyfile else None,
    )


def serve(config: WorkerConfig) -> None:
    dispatcher, audit = build_dispatcher(config)
    try:
        app = build_app(config, dispatcher, audit)
        scheme = "https" if config.tls_certfile else "http"
        LOG.info("Worker MCP em %s://%s:%s%s; modelos: %s", scheme, config.bind_host, config.port,
                 MCP_PATH, ", ".join(model.alias for model in config.models))
        uvicorn.Server(uvicorn_config(config, app)).run()
    finally:
        dispatcher.close()
