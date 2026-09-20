"""Escolha de rota HTTP: LAN primeiro, rede remota configurada em seguida."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class DeviceEndpoint:
    lan_url: str
    remote_url: str
    token: str = field(repr=False)

    def urls(self) -> tuple[str, ...]:
        urls = tuple(dict.fromkeys(url.rstrip("/") for url in (self.lan_url, self.remote_url) if url))
        if not urls or len(self.token) < 24:
            raise ValueError("Configure o endereço do dispositivo e seu token de pareamento.")
        for url in urls:
            parsed = urlsplit(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("Endereço de dispositivo inválido.")
        return urls


class DeviceConnection:
    def __init__(self, endpoint: DeviceEndpoint, session=None):
        self.endpoint = endpoint
        self.session = session if session is not None else requests.Session()

    @property
    def headers(self):
        return {"X-Nebula-Token": self.endpoint.token}

    def discover(self) -> tuple[str, list[dict]]:
        for url in self.endpoint.urls():
            try:
                response = self.session.get(url + "/api/tools", headers=self.headers,
                                            timeout=(2, 5), allow_redirects=False)
            except (requests.ConnectionError, requests.Timeout):
                continue
            if response.status_code in {401, 403}:
                raise PermissionError("Token de pareamento rejeitado pelo dispositivo.")
            if response.status_code >= 500:
                continue
            if response.status_code != 200:
                raise RuntimeError("O endereço não oferece o catálogo de tools da Nebula.")
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
                raise RuntimeError("Catálogo de tools inválido.")
            return url, data["tools"]
        raise ConnectionError("Dispositivo indisponível pela LAN e pela rota remota.")

    def call_tool(self, name: str, arguments: dict) -> dict:
        url, tools = self.discover()
        if name not in {tool.get("name") for tool in tools if isinstance(tool, dict)}:
            raise ValueError("Tool não oferecida pelo dispositivo.")
        try:
            # Não reenvia POST após timeout: a primeira chamada pode ter executado.
            response = self.session.post(
                url + "/api/tools/call", json={"name": name, "arguments": arguments},
                headers=self.headers, timeout=(3, 90), allow_redirects=False,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise ConnectionError("Sem confirmação da execução; o comando não foi reenviado.") from exc
        if response.status_code != 200:
            raise RuntimeError(f"Chamada recusada pelo servidor (HTTP {response.status_code}).")
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
            raise RuntimeError("Resultado da tool inválido.")
        return data
