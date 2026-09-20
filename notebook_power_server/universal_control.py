"""Catálogo único dos controles locais e de uma instalação Home Assistant."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class UniversalError(ValueError):
    pass


def actions(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in items]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HomeAssistant:
    """Token fica no hub; comandos aceitos pertencem ao catálogo conhecido."""

    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url if url is not None else os.getenv("NEBULA_HA_URL", "")).rstrip("/")
        self.token = token if token is not None else os.getenv("NEBULA_HA_TOKEN", "")
        self._entities: dict[str, dict] = {}
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def _request(self, path: str, payload: dict | None = None):
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise UniversalError("Endereço do Home Assistant inválido no hub.")
        request = Request(self.url + path,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with build_opener(_NoRedirect).open(request, timeout=4) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise UniversalError("O catálogo do Home Assistant excedeu o limite.")
            return json.loads(raw)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            # Não incluir URL, headers ou corpo remoto nas mensagens públicas.
            raise UniversalError("Home Assistant indisponível; confira endereço e token no hub.") from exc

    @staticmethod
    def _commands(entity: dict) -> dict[str, tuple[str, dict]]:
        domain = entity["entity_id"].split(".")[0]
        if domain in {"light", "switch", "fan", "input_boolean"}:
            return {"turn_on": ("Ligar", {}), "turn_off": ("Desligar", {})}
        if domain == "scene":
            return {"turn_on": ("Ativar cena", {})}
        if domain == "climate":
            modes = entity.get("attributes", {}).get("hvac_modes", [])
            return {"hvac_" + mode: (label, {"hvac_mode": mode}) for mode, label in
                    (("off", "Desligar"), ("cool", "Resfriar"), ("heat", "Aquecer"), ("auto", "Automático")) if mode in modes}
        if domain == "media_player":
            # MediaPlayerEntityFeature da API do Home Assistant.
            flags = entity.get("attributes", {}).get("supported_features", 0)
            flags = flags if isinstance(flags, int) else 0
            offered = ((128, "turn_on", "Ligar"), (256, "turn_off", "Desligar"),
                       (16384, "media_play", "Reproduzir"), (1, "media_pause", "Pausar"),
                       (32, "media_next_track", "Próxima"), (1024, "volume_up", "Volume +"),
                       (1024, "volume_down", "Volume −"))
            return {key: (label, {}) for flag, key, label in offered if flags & flag}
        return {}

    def devices(self) -> list[dict]:
        if not self.configured:
            return []
        raw = self._request("/api/states")
        if not isinstance(raw, list):
            raise UniversalError("Catálogo do Home Assistant inválido.")
        entities = {}
        result = []
        for entity in raw:
            if not isinstance(entity, dict):
                continue
            key = entity.get("entity_id", "")
            if not isinstance(key, str) or not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", key):
                continue
            if not isinstance(entity.get("attributes", {}), dict):
                continue
            commands = self._commands(entity)
            if not commands:
                continue
            entities[key] = entity
            available = entity.get("state") not in {"unavailable", "unknown"}
            result.append({"id": "ha:" + key, "name": str(entity.get("attributes", {}).get("friendly_name", key)),
                "kind": key.split(".")[0], "source": "Home Assistant", "available": available,
                "state": entity.get("state"), "status": "Disponível" if available else "Indisponível",
                "actions": actions(*[(command, value[0]) for command, value in commands.items()]) if available else []})
        with self._lock:
            self._entities = entities
        return result

    def action(self, entity_id: str, action: str) -> dict:
        with self._lock:
            entity = self._entities.get(entity_id)
        if entity is None:
            self.devices()
            with self._lock:
                entity = self._entities.get(entity_id)
        if entity is None or entity.get("state") in {"unavailable", "unknown"}:
            raise UniversalError("Dispositivo desconhecido ou indisponível; atualize o catálogo.")
        commands = self._commands(entity)
        if action not in commands:
            raise UniversalError("Esse comando não está disponível para o dispositivo.")
        domain = entity_id.split(".")[0]
        service = "set_hvac_mode" if action.startswith("hvac_") else action
        self._request(f"/api/services/{domain}/{service}", {"entity_id": entity_id, **commands[action][1]})
        return {"ok": True, "message": "Comando enviado ao Home Assistant.", "delivery": "unconfirmed"}


class UniversalController:
    def __init__(self, brain, tvs, wake_callback, home_assistant=None):
        self.brain, self.tvs, self.wake_callback = brain, tvs, wake_callback
        self.ha = home_assistant if home_assistant is not None else HomeAssistant()
        self._lock = threading.RLock()
        self._cache: dict | None = None
        self._expires = 0.0

    def invalidate(self) -> None:
        with self._lock:
            self._expires = 0.0

    def _local_devices(self) -> list[dict]:
        # Catálogo não precisa esperar sondagem do PC para permitir Wake-on-LAN.
        items = [{"id": "pc:main", "name": "PC · Nebula", "kind": "computer", "source": "Wake-on-LAN",
                  "available": True, "status": "Inicialização pela rede", "actions": actions(("wake", "Ligar Nebula"))}]
        if self.brain.lamp is not None:
            items.append({"id": "local:lamp", "name": "Abajur", "kind": "light", "source": "Tuya local",
                "available": True, "status": "Configurado · estado não consultado", "actions": actions(
                    ("turn_on", "Ligar"), ("turn_off", "Desligar"), ("warm", "Luz quente"), ("cool", "Luz fria"))})
        if self.brain.air is not None and self.brain.air.estado().get("available"):
            items.append({"id": "local:air", "name": "Ar-condicionado", "kind": "climate", "source": "Smart IR local",
                "available": True, "status": "Infravermelho · envio sem retorno", "actions": actions(
                    ("turn_on", "Ligar"), ("turn_off", "Desligar"), ("temp_down", "Temperatura −"), ("temp_up", "Temperatura +"))})
            if "temperature" not in self.brain.air.estado().get("supported_actions", ["temperature"]):
                items[-1]["actions"] = actions(("turn_on", "Ligar"), ("turn_off", "Desligar"))
                items[-1]["status"] = "Ligar e desligar aprendidos do controle original"
            items[-1]["air"] = self.brain.air.estado()
            if hasattr(self.brain, "air_timer") and isinstance(self.brain.air_timer.status(), dict):
                items[-1]["air"]["timer"] = self.brain.air_timer.status()
                items[-1]["timer_available"] = True
                items[-1]["actions"].append({"id": "timer_cancel", "label": "Cancelar timer"})
        return items

    def _tv_devices(self) -> list[dict]:
        result = []
        for tv in self.tvs.list():
            cmds = []
            if tv.get("can_power_on"):
                cmds.append(("power_on", "Ligar"))
            if tv.get("online"):
                if tv.get("paired"):
                    cmds.extend((("power_off", "Desligar"), ("volume_down", "Volume −"), ("volume_up", "Volume +"),
                                 ("mute", "Mudo"), ("home", "Início"), ("up", "↑"), ("left", "←"),
                                 ("ok", "OK"), ("right", "→"), ("down", "↓"), ("back", "Voltar")))
                    if tv.get("brand") == "lg":
                        cmds.extend((
                            (f"number_{number}", str(number)) for number in range(10)
                        ))
                else:
                    cmds.append(("pair", "Parear TV"))
            result.append({"id": "tv:" + tv["id"], "name": tv["name"], "kind": "tv", "source": tv["brand"],
                "available": bool(cmds), "online": bool(tv.get("online")),
                "status": "Online" if tv.get("online") else "Offline · ligar depende da TV",
                "actions": actions(*cmds)})
        return result

    def devices(self, *, refresh: bool = False) -> dict:
        # Single flight: clientes simultâneos reutilizam a mesma consulta de rede.
        with self._lock:
            if not refresh and self._cache is not None and time.monotonic() < self._expires:
                return deepcopy(self._cache)
            items = self._local_devices()
            errors = []
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="NebulaCatalog") as pool:
                jobs = [("TVs", pool.submit(self._tv_devices)), ("Home Assistant", pool.submit(self.ha.devices))]
                for name, job in jobs:
                    try:
                        items.extend(job.result())
                    except Exception:
                        errors.append(name + " indisponível. Atualize para tentar novamente.")
            self._cache = {"devices": items, "count": len(items), "errors": errors,
                "home_assistant_configured": self.ha.configured, "updated_at": time.time(),
                "message": "Controle os aparelhos configurados. Outros dispositivos precisam de uma integração compatível."}
            self._expires = time.monotonic() + 10
            return deepcopy(self._cache)

    def discover(self) -> dict:
        self.tvs.discover()
        return self.devices(refresh=True)

    def action(self, device_id: object, action: object) -> dict:
        if not isinstance(device_id, str) or not isinstance(action, str):
            raise UniversalError("Informe dispositivo e comando válidos.")
        if device_id.startswith("ha:"):
            result = self.ha.action(device_id[3:], action)
        elif device_id == "pc:main" and action == "wake":
            result = self.wake_callback()
        elif device_id.startswith("tv:"):
            if action == "pair":
                result = {"ok": True, "tv": self.tvs.pair(device_id[3:]), "message": "TV pareada."}
            else:
                result = self.tvs.action(device_id[3:], action)
        else:
            if device_id == "local:lamp" and re.fullmatch(r"color_[0-9a-fA-F]{6}", action):
                result = self.brain.action("lamp.color", "#" + action[6:].upper())
                self.invalidate()
                return result
            if device_id == "local:lamp" and re.fullmatch(r"brightness_[0-9]{1,3}", action):
                brightness = int(action.removeprefix("brightness_"))
                if not 1 <= brightness <= 100:
                    raise UniversalError("Brilho deve ficar entre 1 e 100.")
                result = self.brain.action("lamp.brightness", brightness)
                self.invalidate()
                return result
            if device_id == "local:air" and (action == "timer_cancel" or re.fullmatch(r"timer_set_[0-9]{1,4}", action)):
                minutes = 0 if action == "timer_cancel" else int(action.removeprefix("timer_set_"))
                result = self.brain.action("air.timer", minutes)
                self.invalidate()
                return result
            commands = {
                "local:lamp": {"turn_on": ("lamp.power", True), "turn_off": ("lamp.power", False),
                               "warm": ("lamp.temperature", "quente"), "cool": ("lamp.temperature", "fria")},
                "local:air": {"turn_on": ("air.power", True), "turn_off": ("air.power", False),
                              "temp_down": ("air.temperature", -1), "temp_up": ("air.temperature", 1)},
            }
            command = commands.get(device_id, {}).get(action)
            if command is None:
                raise UniversalError("Dispositivo ou comando não permitido.")
            if device_id == "local:air" and action in {"temp_down", "temp_up"}:
                if self.brain.air is None:
                    raise UniversalError("Configure o Smart IR no hub.")
                temperature = int(self.brain.air.estado().get("temperature", 24))
                minimum = int(self.brain.air.estado().get("temperature_min", 16))
                command = (command[0], max(minimum, min(30, temperature + command[1])))
            result = self.brain.action(*command)
        self.invalidate()
        return result
