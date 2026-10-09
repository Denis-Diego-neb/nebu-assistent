"""Porta de entrada HTTP: cliente permitido, taxa e token, antes do MCP.

Tudo e recusado aqui, antes de o SDK ler o corpo: um cliente fora da lista ou
sem token nunca chega a ter o JSON interpretado. Host/Origin (DNS rebinding) e
Content-Type ficam com o TransportSecurity do proprio SDK, logo depois.
"""

from __future__ import annotations

import hmac
import json
import threading
import time
from ipaddress import ip_address

from nebula_worker.observability.audit import AuditLog


class GatewayGuard:
    def __init__(self, app, *, token: str, allowed_clients, requests_per_minute: int,
                 audit: AuditLog, clock=time.monotonic) -> None:
        self.app = app
        self._expected = ("Bearer " + token).encode("ascii")
        self.allowed_clients = tuple(allowed_clients)
        self.capacity = float(requests_per_minute)
        self.refill_per_second = requests_per_minute / 60.0
        self.audit = audit
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._last_denial: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # O transporte MCP e HTTP puro; WebSocket nao faz parte do contrato.
            await send({"type": "websocket.close", "code": 1008})
            return
        client = (scope.get("client") or ("", 0))[0] or ""
        if not self._client_allowed(client):
            self._deny(client, "client_not_allowed")
            await _reply(send, 403, "CLIENT_NOT_ALLOWED", "Cliente fora da lista permitida.")
            return
        if not self._take(client):
            self._deny(client, "rate_limited")
            await _reply(send, 429, "RATE_LIMITED", "Muitas requisicoes; aguarde.",
                         extra=[(b"retry-after", b"5")])
            return
        values = [value for name, value in scope.get("headers", []) if name == b"authorization"]
        if len(values) != 1:
            self._deny(client, "missing_token")
            await _reply(send, 401, "UNAUTHORIZED", "Token ausente.",
                         extra=[(b"www-authenticate", b"Bearer")])
            return
        if not hmac.compare_digest(values[0], self._expected):
            self._deny(client, "bad_token")
            await _reply(send, 401, "UNAUTHORIZED", "Token invalido.",
                         extra=[(b"www-authenticate", b"Bearer")])
            return
        await self.app(scope, receive, send)

    def _client_allowed(self, client: str) -> bool:
        try:
            address = ip_address(client.split("%", 1)[0])
        except ValueError:
            return False
        if address.version == 6 and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return any(address.version == network.version and address in network
                   for network in self.allowed_clients)

    def _take(self, client: str) -> bool:
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.get(client, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_second)
            if tokens < 1.0:
                self._buckets[client] = (tokens, now)
                return False
            self._buckets[client] = (tokens - 1.0, now)
            if len(self._buckets) > 1024:
                # Poucos clientes legitimos; evita crescer sem limite sob varredura.
                self._buckets = {client: self._buckets[client]}
            return True

    def _deny(self, client: str, reason: str) -> None:
        # Uma linha por cliente e motivo a cada 10 s: varredura nao enche o disco.
        now = self.clock()
        key = (client, reason)
        with self._lock:
            if now - self._last_denial.get(key, float("-inf")) < 10:
                return
            self._last_denial[key] = now
            if len(self._last_denial) > 1024:
                self._last_denial = {key: now}
        self.audit.record("denied", client=client[:80], reason=reason)


async def _reply(send, status: int, code: str, message: str, extra=None) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
               (b"cache-control", b"no-store")]
    headers.extend(extra or [])
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
