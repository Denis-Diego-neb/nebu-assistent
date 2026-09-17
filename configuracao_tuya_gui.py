"""Logica testavel da configuracao Tuya exibida pela interface grafica."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import io
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from abajur_tuya import (
    ARQUIVO_CONFIGURACAO,
    ConfiguracaoTuya,
    ControleAbajurTuya,
    VERSOES_SUPORTADAS,
    pasta_dados_nebula,
)
from abajur_wifi import ErroAbajur

try:
    import tinytuya as _tinytuya
except ImportError:
    _tinytuya = None


class ErroConfiguracaoTuya(ValueError):
    """Erro seguro para exibicao, sem incluir a local key."""


@dataclass(frozen=True)
class DispositivoTuyaDescoberto:
    """Parte nao secreta de um anuncio Tuya encontrado na LAN."""

    device_id: str
    address: str
    version: float = 3.5


def _ler_objeto_json(caminho: Path) -> dict[str, object]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _primeiro_texto(*valores: object, padrao: str = "") -> str:
    for valor in valores:
        texto = str(valor or "").strip()
        if texto:
            return texto
    return padrao


def _versao_suportada(*valores: object) -> float:
    for valor in valores:
        try:
            versao = float(valor)
        except (TypeError, ValueError):
            continue
        if versao in VERSOES_SUPORTADAS:
            return versao
    return 3.5


def _itens_descobertos(dados: object) -> list[tuple[str, Mapping[str, object]]]:
    itens: list[tuple[str, Mapping[str, object]]] = []
    if isinstance(dados, Mapping):
        if any(chave in dados for chave in ("id", "gwId", "device_id", "dev_id")):
            return [("", dados)]
        for chave, valor in dados.items():
            if isinstance(valor, Mapping):
                itens.append((str(chave), valor))
    elif isinstance(dados, list):
        for valor in dados:
            if isinstance(valor, Mapping):
                itens.append(("", valor))
    return itens


def _normalizar_dispositivos(dados: object) -> list[DispositivoTuyaDescoberto]:
    resultado: list[DispositivoTuyaDescoberto] = []
    vistos: set[tuple[str, str]] = set()
    for endereco_chave, item in _itens_descobertos(dados):
        device_id = _primeiro_texto(
            item.get("id"),
            item.get("gwId"),
            item.get("device_id"),
            item.get("dev_id"),
        )
        if not device_id:
            continue
        address = _primeiro_texto(
            item.get("ip"),
            item.get("address"),
            endereco_chave,
            padrao="Auto",
        )
        version = _versao_suportada(
            item.get("ver"),
            item.get("version"),
            3.5,
        )
        chave = (device_id, address)
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(DispositivoTuyaDescoberto(device_id, address, version))
    return resultado


def dispositivos_do_snapshot(caminho: Path) -> list[DispositivoTuyaDescoberto]:
    """Le somente ID, IP e versao; chaves/tokens do snapshot sao ignorados."""

    dados = _ler_objeto_json(caminho)
    return _normalizar_dispositivos(dados.get("devices", []))


def carregar_configuracao_inicial(
    *,
    pasta_dados: Path | None = None,
    snapshot_path: Path | None = None,
) -> ConfiguracaoTuya:
    """Combina ambiente, JSON existente e snapshot para preencher o formulario."""

    pasta = pasta_dados or pasta_dados_nebula()
    existente = _ler_objeto_json(pasta / ARQUIVO_CONFIGURACAO)
    caminho_snapshot = snapshot_path or Path(__file__).resolve().parent / "snapshot.json"
    snapshots = dispositivos_do_snapshot(caminho_snapshot)
    snapshot = snapshots[0] if snapshots else None

    device_id = _primeiro_texto(
        os.environ.get("NEBULA_TUYA_DEVICE_ID"),
        existente.get("device_id"),
        snapshot.device_id if snapshot else "",
    )
    address = _primeiro_texto(
        os.environ.get("NEBULA_TUYA_ADDRESS"),
        existente.get("address"),
        snapshot.address if snapshot else "",
        padrao="Auto",
    )
    local_key = _primeiro_texto(
        os.environ.get("NEBULA_TUYA_LOCAL_KEY"),
        existente.get("local_key"),
    )
    version = _versao_suportada(
        os.environ.get("NEBULA_TUYA_VERSION"),
        existente.get("version"),
        snapshot.version if snapshot else None,
        3.5,
    )
    return ConfiguracaoTuya(device_id, address, local_key, version)


def criar_configuracao(
    device_id: str,
    address: str,
    version: str | float,
    local_key: str,
) -> ConfiguracaoTuya:
    """Valida os valores do formulario sem expor a chave nos erros."""

    device_id = device_id.strip()
    address = address.strip() or "Auto"
    local_key = local_key.strip()
    try:
        version_number = float(version)
    except (TypeError, ValueError) as exc:
        raise ErroConfiguracaoTuya(
            "Escolha uma versao de protocolo entre 3.1 e 3.5."
        ) from exc

    if address.lower() == "auto":
        address = "Auto"
    else:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ErroConfiguracaoTuya(
                "Informe um endereco IPv4 valido ou use Auto."
            ) from exc
        if parsed_address.version != 4:
            raise ErroConfiguracaoTuya(
                "Informe um endereco IPv4 valido ou use Auto."
            )
        address = str(parsed_address)

    config = ConfiguracaoTuya(device_id, address, local_key, version_number)
    try:
        config.validar()
    except ErroAbajur as exc:
        raise ErroConfiguracaoTuya(str(exc)) from exc
    return config


def detectar_dispositivos(
    tinytuya_backend: object | None = None,
) -> list[DispositivoTuyaDescoberto]:
    """Escuta anuncios Tuya na LAN sem consultar nem modificar DPS."""

    backend = _tinytuya if tinytuya_backend is None else tinytuya_backend
    if backend is None:
        raise ErroConfiguracaoTuya(
            "A biblioteca TinyTuya nao esta instalada. Instale o pacote tinytuya."
        )
    scan = getattr(backend, "deviceScan", None)
    if not callable(scan):
        raise ErroConfiguracaoTuya(
            "A instalacao do TinyTuya nao oferece deteccao de rede."
        )
    try:
        # TinyTuya pode imprimir mesmo quando uma dependencia interna reclama.
        # A saida e descartada para nunca levar dados de descoberta aos logs.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            dados = scan(verbose=False, color=False, poll=False)
    except Exception as exc:
        raise ErroConfiguracaoTuya(
            "Nao consegui detectar dispositivos Tuya na rede local. "
            "Confira o Wi-Fi e tente novamente."
        ) from exc
    return _normalizar_dispositivos(dados)


def escolher_dispositivo_preferido(
    dispositivos: list[DispositivoTuyaDescoberto],
    device_id_atual: str = "",
) -> DispositivoTuyaDescoberto | None:
    """Mantém o ID já configurado; só escolhe sozinho quando houver um único."""

    atual = device_id_atual.strip()
    if atual:
        encontrado = next(
            (item for item in dispositivos if item.device_id == atual),
            None,
        )
        if encontrado is not None:
            return encontrado
    return dispositivos[0] if len(dispositivos) == 1 else None


def salvar_configuracao(
    config: ConfiguracaoTuya,
    *,
    pasta_dados: Path | None = None,
) -> Path:
    """Grava a configuracao por troca atomica na pasta privada da Nebula."""

    try:
        config.validar()
    except ErroAbajur as exc:
        raise ErroConfiguracaoTuya(str(exc)) from exc

    pasta = pasta_dados or pasta_dados_nebula()
    destino = pasta / ARQUIVO_CONFIGURACAO
    temporario: Path | None = None
    conteudo = {
        "device_id": config.device_id,
        "address": config.address,
        "local_key": config.local_key,
        "version": config.version,
    }
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        descritor, nome_temporario = tempfile.mkstemp(
            prefix="abajur_tuya.", suffix=".tmp", dir=pasta
        )
        temporario = Path(nome_temporario)
        with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as arquivo:
            json.dump(conteudo, arquivo, ensure_ascii=False, indent=2)
            arquivo.write("\n")
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    except OSError as exc:
        if temporario is not None:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
        raise ErroConfiguracaoTuya(
            "Nao consegui salvar a configuracao Tuya na pasta local da Nebula."
        ) from exc
    return destino


def testar_configuracao(
    config: ConfiguracaoTuya,
    *,
    pasta_dados: Path | None = None,
    controle_factory: Callable[..., Any] = ControleAbajurTuya,
) -> dict[str, Any]:
    """Executa exclusivamente a consulta somente leitura ``status()``."""

    pasta = pasta_dados or pasta_dados_nebula()
    controle = controle_factory(config, pasta_dados=pasta)
    resposta = controle.status()
    return resposta if isinstance(resposta, dict) else {}


def mensagem_erro_segura(exc: Exception, *, local_key: str = "") -> str:
    """Converte excecoes em texto de UI e remove a chave se ela aparecer."""

    if isinstance(exc, (ErroConfiguracaoTuya, ErroAbajur)):
        mensagem = str(exc)
    else:
        mensagem = "Falha inesperada durante a configuracao Tuya."
    if local_key:
        mensagem = mensagem.replace(local_key, "[chave oculta]")
    return mensagem


__all__ = [
    "DispositivoTuyaDescoberto",
    "ErroConfiguracaoTuya",
    "carregar_configuracao_inicial",
    "criar_configuracao",
    "detectar_dispositivos",
    "dispositivos_do_snapshot",
    "escolher_dispositivo_preferido",
    "mensagem_erro_segura",
    "salvar_configuracao",
    "testar_configuracao",
]
