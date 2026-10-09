"""Configuracao do worker: tudo que e local ao notebook, validado antes de abrir a porta.

JSON em vez do YAML do GOAL: a biblioteca padrao le JSON e o executavel do
notebook nao ganha dependencia nova por causa de um arquivo de configuracao.
O token nunca fica no arquivo, so o nome da variavel de ambiente que o guarda.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, fields
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from nebula_worker.protocol.envelope import ALIAS_RE, required_scope
from nebula_worker.protocol.ticket import KEY_ID_RE, key_id_for, public_key_from_text
from nebula_worker.worker.dispatcher import Limits

DEFAULT_PORT = 8790
DEFAULT_TOKEN_ENV = "NEBULA_WORKER_TOKEN"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
MIN_TOKEN_CHARS = 32
TAILSCALE_V4 = ip_network("100.64.0.0/10")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# Opcoes de hardware e amostragem que o notebook decide sozinho.
MODEL_OPTION_KEYS = frozenset({
    "num_thread", "num_gpu", "num_batch", "main_gpu", "num_ctx",
    "temperature", "top_k", "top_p", "min_p", "repeat_penalty",
})
_TOP_KEYS = frozenset({
    "bind_host", "port", "token_env", "allowed_clients", "host_names", "trusted_keys",
    "models", "limits", "runtime_dir", "tls_certfile", "tls_keyfile", "requests_per_minute",
})
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                          r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    model: str
    base_url: str
    options: dict
    keep_alive: str


@dataclass(frozen=True)
class WorkerConfig:
    bind_host: str
    port: int
    token: str
    allowed_clients: tuple[IPv4Network | IPv6Network, ...]
    host_names: tuple[str, ...]
    trusted_keys: dict[str, Ed25519PublicKey]
    models: tuple[ModelConfig, ...]
    limits: Limits
    runtime_dir: Path
    tls_certfile: Path | None
    tls_keyfile: Path | None
    requests_per_minute: int

    @property
    def allowed_scopes(self) -> frozenset[str]:
        return frozenset(required_scope(model.alias, "generate") for model in self.models)

    @property
    def allowed_host_headers(self) -> list[str]:
        host = f"[{self.bind_host}]" if ":" in self.bind_host else self.bind_host
        headers = [f"{host}:{self.port}"]
        headers += [f"{name}:{self.port}" for name in self.host_names]
        if ip_address(self.bind_host).is_loopback:
            headers.append(f"localhost:{self.port}")
        return headers


def default_base_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "NebulaWorker"
    return Path.home() / ".local" / "state" / "nebula-worker"


def default_config_path() -> Path:
    return default_base_dir() / "worker.json"


def load_config(path: Path, environ: dict | None = None) -> WorkerConfig:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Arquivo de configuracao nao encontrado: {path}") from exc
    except ValueError as exc:
        raise ConfigError(f"Configuracao nao e JSON valido: {exc}") from exc
    if environ is None:
        environ = dict(os.environ)
        name = data.get("token_env", DEFAULT_TOKEN_ENV) if isinstance(data, dict) else DEFAULT_TOKEN_ENV
        if isinstance(name, str) and not environ.get(name):
            stored = _user_environment(name)
            if stored:
                environ[name] = stored
    return parse_config(data, environ)


def _user_environment(name: str) -> str:
    """Le a variavel do usuario no registro do Windows.

    Um processo aberto antes do instalador gravar o token (o lancador da
    tarefa, por exemplo) herda um ambiente antigo; o registro nao envelhece.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""


def _private(address) -> bool:
    return address.is_loopback or address.is_private or (
        address.version == 4 and address in TAILSCALE_V4)


def _network_private(network) -> bool:
    return network.is_loopback or network.is_private or (
        network.version == 4 and network.subnet_of(TAILSCALE_V4))


def parse_config(data: object, environ) -> WorkerConfig:
    if not isinstance(data, dict):
        raise ConfigError("A configuracao deve ser um objeto JSON.")
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"Campos desconhecidos na configuracao: {sorted(unknown)}")

    try:
        bind = ip_address(str(data.get("bind_host", "")))
    except ValueError as exc:
        raise ConfigError("bind_host deve ser um endereco IP explicito.") from exc
    # Secao 22 do GOAL: so loopback ou a interface privada escolhida. Curinga e
    # IP publico abririam o worker para redes que ninguem escolheu.
    if bind.is_unspecified:
        raise ConfigError("bind_host nao pode ser 0.0.0.0 nem ::; escolha a interface.")
    if not _private(bind):
        raise ConfigError("bind_host precisa ser loopback, LAN privada ou Tailscale (100.64.0.0/10).")

    port = data.get("port", DEFAULT_PORT)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ConfigError("port deve ser inteiro entre 1024 e 65535.")

    token_env = data.get("token_env", DEFAULT_TOKEN_ENV)
    if not isinstance(token_env, str) or _ENV_NAME_RE.fullmatch(token_env) is None:
        raise ConfigError("token_env deve ser o nome de uma variavel de ambiente.")
    token = str(environ.get(token_env, "")).strip()
    if len(token) < MIN_TOKEN_CHARS or not token.isascii() or any(c.isspace() for c in token):
        raise ConfigError(
            f"Defina {token_env} com ao menos {MIN_TOKEN_CHARS} caracteres ASCII, sem espacos."
        )

    clients_raw = data.get("allowed_clients", ["127.0.0.1/32", "::1/128"])
    if not isinstance(clients_raw, list) or not clients_raw:
        raise ConfigError("allowed_clients deve ser uma lista de redes (CIDR).")
    clients = []
    for item in clients_raw:
        try:
            network = ip_network(str(item), strict=True)
        except ValueError as exc:
            raise ConfigError(f"Rede invalida em allowed_clients: {item}") from exc
        if not _network_private(network):
            raise ConfigError(f"allowed_clients so aceita redes privadas: {item}")
        clients.append(network)

    names_raw = data.get("host_names", [])
    if not isinstance(names_raw, list) or not all(
            isinstance(name, str) and _HOSTNAME_RE.fullmatch(name) for name in names_raw):
        raise ConfigError("host_names deve ser uma lista de nomes de host validos.")

    keys_raw = data.get("trusted_keys")
    if not isinstance(keys_raw, dict) or not keys_raw:
        raise ConfigError("trusted_keys deve mapear key_id -> chave publica do PC.")
    trusted: dict[str, Ed25519PublicKey] = {}
    for key_id, text in keys_raw.items():
        if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
            raise ConfigError(f"key_id invalido: {key_id}")
        try:
            public_key = public_key_from_text(str(text))
        except ValueError as exc:
            raise ConfigError(f"Chave publica invalida para {key_id}.") from exc
        # O id e derivado da chave: um id trocado indicaria copia errada.
        if key_id_for(public_key) != key_id:
            raise ConfigError(f"key_id {key_id} nao corresponde a chave publica informada.")
        trusted[key_id] = public_key

    models = _parse_models(data.get("models"))
    limits = _parse_limits(data.get("limits", {}))

    runtime_raw = data.get("runtime_dir")
    runtime_dir = Path(runtime_raw) if runtime_raw else default_base_dir() / "runtime"

    tls_cert, tls_key = data.get("tls_certfile"), data.get("tls_keyfile")
    if bool(tls_cert) != bool(tls_key):
        raise ConfigError("Informe tls_certfile e tls_keyfile juntos.")
    if tls_cert and not (Path(tls_cert).is_file() and Path(tls_key).is_file()):
        raise ConfigError("Arquivos TLS nao encontrados.")

    rate = data.get("requests_per_minute", 120)
    if type(rate) is not int or not 10 <= rate <= 6000:
        raise ConfigError("requests_per_minute deve ficar entre 10 e 6000.")

    return WorkerConfig(
        bind_host=str(bind), port=port, token=token, allowed_clients=tuple(clients),
        host_names=tuple(names_raw), trusted_keys=trusted, models=models, limits=limits,
        runtime_dir=runtime_dir,
        tls_certfile=Path(tls_cert) if tls_cert else None,
        tls_keyfile=Path(tls_key) if tls_key else None,
        requests_per_minute=rate,
    )


def _parse_models(raw: object) -> tuple[ModelConfig, ...]:
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("models deve mapear alias -> configuracao do modelo.")
    models = []
    for alias, spec in raw.items():
        if not isinstance(alias, str) or ALIAS_RE.fullmatch(alias) is None:
            raise ConfigError(f"Alias de modelo invalido: {alias}")
        if not isinstance(spec, dict):
            raise ConfigError(f"models.{alias} deve ser um objeto.")
        unknown = set(spec) - {"provider", "model", "base_url", "options", "keep_alive", "enabled"}
        if unknown:
            raise ConfigError(f"models.{alias}: campos desconhecidos {sorted(unknown)}")
        if spec.get("enabled", True) is False:
            continue
        if spec.get("provider", "ollama") != "ollama":
            raise ConfigError(f"models.{alias}: somente o provider ollama e suportado.")
        model = spec.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 128:
            raise ConfigError(f"models.{alias}.model deve nomear o modelo do Ollama.")
        base_url = spec.get("base_url", DEFAULT_OLLAMA_URL)
        parsed = urlparse(str(base_url))
        # O worker so conversa com o Ollama da propria maquina; apontar para
        # outro host transformaria o notebook em relay de modelos alheios.
        if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
            raise ConfigError(f"models.{alias}.base_url deve ser http://127.0.0.1:<porta>.")
        options = spec.get("options", {})
        if not isinstance(options, dict) or not set(options) <= MODEL_OPTION_KEYS or not all(
                type(value) in (int, float) for value in options.values()):
            raise ConfigError(
                f"models.{alias}.options aceita somente numeros em {sorted(MODEL_OPTION_KEYS)}.")
        keep_alive = spec.get("keep_alive", "30m")
        if not isinstance(keep_alive, str) or re.fullmatch(r"-?\d+[smh]?", keep_alive) is None:
            raise ConfigError(f"models.{alias}.keep_alive invalido.")
        models.append(ModelConfig(alias, model.strip(), str(base_url), dict(options), keep_alive))
    if not models:
        raise ConfigError("Nenhum modelo habilitado.")
    return tuple(models)


_LIMIT_RANGES = {
    "max_input_chars": (100, 1_000_000),
    "max_output_tokens": (16, 131_072),
    "max_timeout_ms": (1_000, 3_600_000),
    "max_context_tokens": (256, 262_144),
    "max_queue": (1, 64),
    "result_ttl_seconds": (30, 86_400),
    "forget_after_seconds": (60, 86_400),
    "max_result_bytes": (1_024, 10_000_000),
    "max_ticket_ttl_seconds": (30, 3_600),
    "clock_skew_seconds": (0, 600),
}


def _parse_limits(raw: object) -> Limits:
    if not isinstance(raw, dict):
        raise ConfigError("limits deve ser um objeto.")
    unknown = set(raw) - set(_LIMIT_RANGES)
    if unknown:
        raise ConfigError(f"limits: campos desconhecidos {sorted(unknown)}")
    values = {}
    for name, value in raw.items():
        low, high = _LIMIT_RANGES[name]
        if type(value) is not int or not low <= value <= high:
            raise ConfigError(f"limits.{name} deve ficar entre {low} e {high}.")
        values[name] = value
    known = {field.name for field in fields(Limits)}
    return Limits(**{key: value for key, value in values.items() if key in known})
