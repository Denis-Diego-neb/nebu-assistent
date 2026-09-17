"""Assistente interativo para configurar o controle Tuya local da lâmpada."""

from __future__ import annotations

from getpass import getpass
import json
import os
from pathlib import Path

from abajur_tuya import (
    ARQUIVO_CONFIGURACAO,
    ConfiguracaoTuya,
    ControleAbajurTuya,
    VERSOES_SUPORTADAS,
    pasta_dados_nebula,
)
from abajur_wifi import ErroAbajur


def _ler_json_objeto(caminho: Path) -> dict[str, object]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _dispositivos_snapshot(caminho: Path) -> list[dict[str, object]]:
    """Extrai somente ID, IP e versão; a chave do snapshot nunca é usada."""
    dados = _ler_json_objeto(caminho)
    dispositivos = dados.get("devices", [])
    if not isinstance(dispositivos, list):
        return []
    resultado: list[dict[str, object]] = []
    for item in dispositivos:
        if not isinstance(item, dict):
            continue
        device_id = str(item.get("id", "")).strip()
        if not device_id:
            continue
        resultado.append(
            {
                "device_id": device_id,
                "address": str(item.get("ip", "")).strip(),
                "version": item.get("ver", item.get("version", 3.5)),
            }
        )
    return resultado


def _escolher_snapshot(dispositivos: list[dict[str, object]]) -> dict[str, object]:
    if not dispositivos:
        return {}
    if len(dispositivos) == 1:
        print("Encontrei uma lâmpada Tuya no snapshot local.")
        return dispositivos[0]
    print("Encontrei mais de um dispositivo Tuya no snapshot:")
    for indice, item in enumerate(dispositivos, start=1):
        endereco = str(item.get("address") or "endereço automático")
        versao = str(item.get("version") or "desconhecida")
        print(f"  {indice}. endereço {endereco}, protocolo {versao}")
    while True:
        resposta = input("Qual deles é a lâmpada? [1]: ").strip() or "1"
        try:
            return dispositivos[int(resposta) - 1]
        except (ValueError, IndexError):
            print("Escolha um número da lista.")


def _perguntar(texto: str, padrao: str = "", *, mostrar_padrao: bool = True) -> str:
    sufixo = f" [{padrao}]" if padrao and mostrar_padrao else ""
    resposta = input(f"{texto}{sufixo}: ").strip()
    return resposta or padrao


def _salvar_configuracao(config: ConfiguracaoTuya, pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / ARQUIVO_CONFIGURACAO
    temporario = caminho.with_suffix(".tmp")
    conteudo = {
        "device_id": config.device_id,
        "address": config.address,
        "local_key": config.local_key,
        "version": config.version,
    }
    try:
        temporario.write_text(
            json.dumps(conteudo, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporario.replace(caminho)
    except OSError as exc:
        raise ErroAbajur("Não consegui salvar a configuração local da lâmpada.") from exc
    return caminho


def _chave_valida(chave: str) -> bool:
    try:
        return len(chave.encode("ascii")) == 16
    except UnicodeEncodeError:
        return False


def main() -> int:
    pasta = pasta_dados_nebula()
    existente = _ler_json_objeto(pasta / ARQUIVO_CONFIGURACAO)
    snapshot = _escolher_snapshot(
        _dispositivos_snapshot(Path(__file__).resolve().parent / "snapshot.json")
    )

    print("\nConfiguração do controle local da lâmpada (sem celular durante o uso).")
    id_padrao = str(
        os.environ.get("NEBULA_TUYA_DEVICE_ID")
        or existente.get("device_id")
        or snapshot.get("device_id")
        or ""
    ).strip()
    device_id = _perguntar(
        "Device ID Tuya" if not id_padrao else "Device ID Tuya [detectado; Enter mantém]",
        id_padrao,
        mostrar_padrao=False,
    )
    if not device_id:
        print("Não encontrei o Device ID. Rode `python -m tinytuya scan` e tente novamente.")
        return 2

    endereco_padrao = str(
        os.environ.get("NEBULA_TUYA_ADDRESS")
        or existente.get("address")
        or snapshot.get("address")
        or "Auto"
    ).strip()
    endereco = _perguntar("IP da lâmpada ou Auto", endereco_padrao) or "Auto"

    versao_padrao = str(
        os.environ.get("NEBULA_TUYA_VERSION")
        or existente.get("version")
        or snapshot.get("version")
        or "3.5"
    ).strip()
    while True:
        valor_versao = _perguntar("Versão do protocolo Tuya", versao_padrao)
        try:
            versao = float(valor_versao)
        except ValueError:
            versao = 0.0
        if versao in VERSOES_SUPORTADAS:
            break
        print("Use uma versão entre 3.1 e 3.5; esta lâmpada foi descoberta como 3.5.")

    chave_existente = str(
        os.environ.get("NEBULA_TUYA_LOCAL_KEY")
        or existente.get("local_key")
        or ""
    ).strip()
    aviso_chave = "Local key Tuya (entrada oculta)"
    if chave_existente:
        aviso_chave = "Nova local key (entrada oculta; Enter mantém a atual)"
    while True:
        digitada = getpass(f"{aviso_chave}: ").strip()
        chave = digitada or chave_existente
        if not chave or _chave_valida(chave):
            break
        print("A local key precisa ter exatamente 16 caracteres ASCII.")

    config = ConfiguracaoTuya(
        device_id=device_id,
        address=endereco,
        local_key=chave,
        version=versao,
    )
    try:
        caminho = _salvar_configuracao(config, pasta)
    except ErroAbajur as exc:
        print(exc)
        return 1
    print(f"Configuração salva em {caminho}.")

    if not chave:
        print(
            "Ainda falta a local key. Em uma pasta fora do projeto, rode "
            "`python -m tinytuya wizard`, copie a chave da lâmpada e execute "
            "este configurador novamente."
        )
        return 2

    try:
        config.validar()
        ControleAbajurTuya(config, pasta_dados=pasta).status()
    except ErroAbajur as exc:
        print(f"A configuração foi salva, mas o teste somente leitura falhou: {exc}")
        return 1
    print("Conexão confirmada: a lâmpada respondeu ao teste somente leitura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

