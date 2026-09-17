"""Controle local do ar-condicionado pelo Smart IR Tuya, sem eKasa ou ADB."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct
import sys
import threading
from typing import Callable

from tinytuya.Contrib.IRRemoteControlDevice import IRRemoteControlDevice
from tinytuya import CONTROL
from ir_coolix import supports_temperature, temperature_code


CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula"
CONFIG_FILE = CONFIG_DIR / "ar_ir.json"
STATE_FILE = CONFIG_DIR / "ar_ir_state.json"
CODES_FILE = CONFIG_DIR / "ar_ir_codes.json"

MODES = {
    "cool": "Ar Frio",
    "heat": "Ar Quente",
    "auto": "Auto",
    "fan": "Fornecer ar",
    "dry": "Desumidificacao",
}
FANS = {
    "auto": "Auto",
    "low": "Fraco",
    "medium": "Medio",
    "high": "Forte",
}

_MODE_BITS = {"auto": 0x0, "fan": 0x1, "heat": 0x2, "dry": 0x4, "cool": 0x8}
_FAN_BITS = {"high": 0x1, "medium": 0x2, "low": 0x4, "auto": 0x7}


class ErroAr(RuntimeError):
    """Falha segura ao controlar o ar pelo Smart IR."""


class EmissorIrConfirmado(IRRemoteControlDevice):
    """Espera o ACK do emissor antes de liberar sua conexão TCP.

    O helper TinyTuya usa nowait e descarta retornos de erro. Aqui todos os
    campos de um comando permanecem no mesmo pacote, inclusive no layout 2.
    Um ACK confirma o hub; o ar ainda não oferece retorno físico por IR.
    """

    def set_value(self, index, value, nowait=False):
        return self.set_multiple_values({str(index): value}, nowait=nowait)

    def set_multiple_values(self, data, nowait=False):
        self.cmd_retcode = None
        payload = self.generate_payload(CONTROL, {str(key): value for key, value in data.items()})
        result = self._send_receive(payload, getresponse=True)
        if isinstance(result, dict) and ("Error" in result or "Err" in result):
            raise ErroAr("O Ekaza recusou ou não recebeu o comando. Confira a conexão e a configuração do emissor.")
        if self.cmd_retcode not in (None, 0):
            raise ErroAr("O Ekaza respondeu com erro ao comando infravermelho.")
        if result is None and self.cmd_retcode is None:
            raise ErroAr("O Ekaza não confirmou o recebimento. O estado do ar não foi alterado no app.")
        return result


@dataclass(frozen=True)
class ConfiguracaoArIr:
    device_id: str
    address: str
    local_key: str
    version: float = 3.5
    control_type: int = 1

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "ConfiguracaoArIr | None":
        candidatos = []
        if caminho is not None:
            candidatos.append(caminho)
        variavel = os.environ.get("NEBULA_AR_IR_CONFIG")
        if variavel:
            candidatos.append(Path(variavel))
        candidatos.extend((CONFIG_FILE, Path(sys.executable).resolve().parent / "ar_ir.json"))
        if not getattr(sys, "frozen", False):
            candidatos.append(Path(__file__).resolve().parent / "ar_ir.json")
        for candidato in candidatos:
            try:
                dados = json.loads(candidato.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(dados, dict):
                continue
            device_id = str(dados.get("device_id", "")).strip()
            address = str(dados.get("address", "")).strip()
            local_key = str(dados.get("local_key", "")).strip()
            try:
                version = float(dados.get("version", 3.5))
            except (TypeError, ValueError):
                version = 3.5
            try:
                control_type = int(dados.get("control_type", 1))
            except (TypeError, ValueError):
                control_type = 1
            if control_type not in {1, 2}:
                control_type = 1
            if device_id and address and len(local_key) == 16:
                return cls(device_id, address, local_key, version, control_type)
        return None


def _codigo_ir_valido(codigo: object) -> bool:
    if not isinstance(codigo, str) or not 8 <= len(codigo) <= 32_768:
        return False
    candidato = codigo[1:] if len(codigo) % 4 == 1 and codigo.startswith("1") else codigo
    try:
        bruto = base64.b64decode(candidato, validate=True)
    except (ValueError, TypeError):
        return False
    return 4 <= len(bruto) <= 24_576 and len(bruto) % 2 == 0


def quadro_voltas(*, power: bool, temperature: int, mode: str, fan: str) -> bytes:
    """Monta o quadro de 80 bits usado pelo controle Voltas."""
    if mode not in _MODE_BITS:
        raise ValueError("Modo do ar invalido.")
    if fan not in _FAN_BITS:
        raise ValueError("Velocidade do ar invalida.")
    if not 16 <= temperature <= 30:
        raise ValueError("A temperatura deve ficar entre 16 e 30 graus.")
    estado = [
        0x33,
        _MODE_BITS[mode] | (_FAN_BITS[fan] << 5),
        0x00,
        0x10 | (temperature - 16),
        0x3B,
        0x3B,
        0x3B,
        0x11,
        0x00,
    ]
    if power:
        estado[2] |= 0x80
    estado.append((~sum(estado)) & 0xFF)
    return bytes(estado)


def pulsos_voltas(quadro: bytes) -> list[int]:
    """Converte o quadro Voltas em pulsos de 38 kHz aceitos pelo Smart IR."""
    if len(quadro) != 10:
        raise ValueError("O quadro Voltas precisa ter 10 bytes.")
    pulsos: list[int] = []
    for byte in quadro:
        for bit in range(7, -1, -1):
            pulsos.extend((1026, 2553 if byte & (1 << bit) else 554))
    pulsos.extend((1026, 30000))
    return pulsos


def codigo_base64_voltas(quadro: bytes) -> str:
    pulsos = pulsos_voltas(quadro)
    formato = "<" + str(len(pulsos)) + "H"
    return base64.b64encode(struct.pack(formato, *pulsos)).decode("ascii")


class ControleArDireto:
    """Mantem o estado e transmite diretamente ao Smart IR pela rede local."""

    def __init__(
        self,
        config: ConfiguracaoArIr | None = None,
        state_file: Path = STATE_FILE,
        device_factory: Callable[..., IRRemoteControlDevice] = EmissorIrConfirmado,
        codes_file: Path = CODES_FILE,
    ) -> None:
        self.config = config or ConfiguracaoArIr.carregar()
        self.state_file = state_file
        self.device_factory = device_factory
        self.codes_file = codes_file
        self._lock = threading.RLock()
        self._codes: dict[str, str] = {}
        self._last_error: str | None = None
        self._state: dict[str, object] = {
            "power": False,
            "temperature": 17,
            "mode": "cool",
            "fan": "high",
        }
        self._carregar_estado()
        self._carregar_codigos()

    def _carregar_estado(self) -> None:
        try:
            dados = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(dados, dict):
            return
        if isinstance(dados.get("power"), bool):
            self._state["power"] = dados["power"]
        if isinstance(dados.get("temperature"), int) and 16 <= dados["temperature"] <= 30:
            self._state["temperature"] = dados["temperature"]
        if dados.get("mode") in MODES:
            self._state["mode"] = dados["mode"]
        if dados.get("fan") in FANS:
            self._state["fan"] = dados["fan"]

    def _salvar_estado(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.state_file.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporario.replace(self.state_file)

    def _carregar_codigos(self) -> None:
        try:
            dados = json.loads(self.codes_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(dados, dict):
            return
        self._codes = {
            str(nome): str(codigo)
            for nome, codigo in dados.items()
            if nome in {"power_on", "power_off"} and _codigo_ir_valido(codigo)
        }

    def _salvar_codigos(self) -> None:
        self.codes_file.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.codes_file.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(self._codes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporario.replace(self.codes_file)

    def _novo_dispositivo(self) -> IRRemoteControlDevice:
        config = self.config
        if config is None:
            raise ErroAr("O Smart IR ainda nao foi configurado na Nebula.")
        return self.device_factory(
            config.device_id,
            config.address,
            config.local_key,
            version=config.version,
            control_type=config.control_type,
        )

    def estado(self) -> dict[str, object]:
        with self._lock:
            estado = dict(self._state)
        estado.update(
            {
                "available": self.config is not None,
                "source": "Smart IR direto via Wi-Fi",
                "assumed_state": True,
                "supported_actions": (["power", "temperature"] if supports_temperature(self._codes.get("power_on")) else ["power"]) if self._codes else ["power", "temperature", "mode", "fan"],
                "temperature_min": 17 if self._codes else 16,
                "error": self._last_error,
                "learned_power": all(
                    nome in self._codes for nome in ("power_on", "power_off")
                ),
                "mode_label": MODES.get(str(estado.get("mode")), ""),
                "fan_label": FANS.get(str(estado.get("fan")), ""),
            }
        )
        if self.config is None:
            estado["error"] = "O Smart IR ainda nao foi configurado na Nebula."
        return estado

    def _enviar(self, estado: dict[str, object], acao: str) -> None:
        coolix = supports_temperature(self._codes.get("power_on"))
        if self._codes and acao != "power" and not (acao == "temperature" and coolix):
            raise ErroAr("Ligar e desligar usam o controle aprendido. Temperatura, modo e ventilacao ainda precisam de sinais compativeis.")
        aprendido = None
        if acao == "power":
            aprendido = self._codes.get("power_on" if estado["power"] else "power_off")
        if coolix and estado["power"]:
            codigo = temperature_code(self._codes["power_on"], int(estado["temperature"]))
        elif aprendido:
            codigo = aprendido
        else:
            if self._codes:
                raise ErroAr("Este botao de energia ainda nao foi aprendido pelo Ekaza.")
            quadro = quadro_voltas(
                power=bool(estado["power"]),
                temperature=int(estado["temperature"]),
                mode=str(estado["mode"]),
                fan=str(estado["fan"]),
            )
            codigo = codigo_base64_voltas(quadro)
        dispositivo = self._novo_dispositivo()
        try:
            dispositivo.set_socketTimeout(5)
            dispositivo.set_socketPersistent(True)
            dispositivo.send_button(codigo)
        except ErroAr:
            raise
        except Exception as exc:
            raise ErroAr(
                "O Smart IR nao respondeu. Confirme se ele esta ligado no Wi-Fi."
            ) from exc
        finally:
            try:
                dispositivo.close()
            except Exception:
                pass

    def aprender(self, nome: str, timeout: int = 30) -> dict[str, object]:
        """Aprende um botao do controle fisico sem armazenar a chave do Smart IR."""
        if nome not in {"power_on", "power_off"}:
            raise ValueError("Botao de aprendizado invalido.")
        dispositivo = self._novo_dispositivo()
        try:
            dispositivo.set_socketTimeout(5)
            dispositivo.set_socketPersistent(True)
            codigo = dispositivo.receive_button(max(5, min(int(timeout), 60)))
        except Exception as exc:
            raise ErroAr(
                "O Smart IR nao recebeu o sinal. Aponte o controle para ele e tente de novo."
            ) from exc
        finally:
            try:
                dispositivo.close()
            except Exception:
                pass
        if not _codigo_ir_valido(codigo):
            raise ErroAr("O Smart IR nao capturou um codigo infravermelho valido.")
        with self._lock:
            self._codes[nome] = str(codigo)
            self._salvar_codigos()
        return {"ok": True, "button": nome, "learned_power": len(self._codes) == 2}

    def executar(self, acao: str, valor: object) -> dict[str, object]:
        acao = str(acao).strip().casefold()
        if acao not in {"power", "temperature", "mode", "fan"}:
            raise ValueError("Acao do ar invalida.")
        with self._lock:
            proximo = dict(self._state)
            if acao == "power":
                proximo["power"] = bool(valor)
            elif acao == "temperature":
                temperatura = int(valor)
                if not 16 <= temperatura <= 30:
                    raise ValueError("A temperatura deve ficar entre 16 e 30 graus.")
                proximo.update({"power": True, "temperature": temperatura})
            elif acao == "mode":
                modo = str(valor).casefold()
                if modo not in MODES:
                    raise ValueError("Modo do ar invalido.")
                proximo.update({"power": True, "mode": modo})
            else:
                ventilacao = str(valor).casefold()
                if ventilacao not in FANS:
                    raise ValueError("Velocidade do ar invalida.")
                proximo.update({"power": True, "fan": ventilacao})
            try:
                self._enviar(proximo, acao)
            except ErroAr as exc:
                self._last_error = str(exc)
                raise
            self._last_error = None
            self._state = proximo
            self._salvar_estado()
        return {
            "ok": True,
            "message": "Comando recebido pelo Ekaza. O ar não confirma a recepção do infravermelho.",
            "delivery": "hub_acknowledged",
            "air": self.estado(),
        }


__all__ = [
    "ConfiguracaoArIr",
    "ControleArDireto",
    "CODES_FILE",
    "ErroAr",
    "FANS",
    "MODES",
    "codigo_base64_voltas",
    "pulsos_voltas",
    "quadro_voltas",
]
