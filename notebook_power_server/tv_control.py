"""Controle local de Smart TVs Samsung Tizen e LG webOS."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import threading
import time
from typing import Any
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import urlopen

import websocket


CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NebulaPower"
CONFIG_FILE = CONFIG_DIR / "tvs.json"
DISCOVERY_TIMEOUT = 0.22

SAMSUNG_KEYS = {
    "power_off": "KEY_POWER",
    "volume_up": "KEY_VOLUP",
    "volume_down": "KEY_VOLDOWN",
    "mute": "KEY_MUTE",
    "channel_up": "KEY_CHUP",
    "channel_down": "KEY_CHDOWN",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "ok": "KEY_ENTER",
    "back": "KEY_RETURN",
    "home": "KEY_HOME",
    "source": "KEY_SOURCE",
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSE",
    "stop": "KEY_STOP",
}

LG_REQUESTS: dict[str, tuple[str, dict[str, object]]] = {
    "power_off": ("ssap://system/turnOff", {}),
    "volume_up": ("ssap://audio/volumeUp", {}),
    "volume_down": ("ssap://audio/volumeDown", {}),
    "channel_up": ("ssap://tv/channelUp", {}),
    "channel_down": ("ssap://tv/channelDown", {}),
    "play": ("ssap://media.controls/play", {}),
    "pause": ("ssap://media.controls/pause", {}),
    "stop": ("ssap://media.controls/stop", {}),
}

LG_BUTTONS = {
    "mute": "MUTE",
    "up": "UP",
    "down": "DOWN",
    "left": "LEFT",
    "right": "RIGHT",
    "ok": "ENTER",
    "back": "BACK",
    "home": "HOME",
    "source": "INPUT",
}
LG_BUTTONS.update({f"number_{number}": str(number) for number in range(10)})

LG_PERMISSIONS = [
    "LAUNCH",
    "CLOSE",
    "CONTROL_AUDIO",
    "CONTROL_INPUT_JOYSTICK",
    "CONTROL_INPUT_MEDIA_PLAYBACK",
    "CONTROL_INPUT_TV",
    "CONTROL_POWER",
    "READ_APP_STATUS",
    "READ_CURRENT_CHANNEL",
    "READ_INPUT_DEVICE_LIST",
    "READ_NETWORK_STATE",
    "READ_RUNNING_APPS",
    "READ_TV_CHANNEL_LIST",
    "WRITE_NOTIFICATION",
    "READ_POWER_STATE",
]


class TvError(RuntimeError):
    """Falha compreensível ao descobrir, parear ou controlar uma TV."""


def _valid_host(value: object) -> str:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError as exc:
        raise TvError("O endereço da TV é inválido.") from exc
    if address.version != 4 or not address.is_private:
        raise TvError("A TV precisa estar em uma rede IPv4 privada.")
    return str(address)


def _port_open(host: str, port: int, timeout: float = DISCOVERY_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _arp_mac(host: str) -> str:
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(
            ["arp", "-a", host],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.search(
        rf"(?im)^\s*{re.escape(host)}\s+([0-9a-f]{{2}}(?:-[0-9a-f]{{2}}){{5}})\s+",
        result.stdout,
    )
    return match.group(1).replace("-", ":").upper() if match else ""


def wake_on_lan(
    mac: str, broadcast: str = "255.255.255.255", host: str = ""
) -> None:
    clean = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(clean) != 12:
        raise TvError("A TV ainda não informou um endereço MAC para ser ligada.")
    packet = b"\xff" * 6 + bytes.fromhex(clean) * 16
    destinos = {broadcast, "255.255.255.255"}
    partes = host.split(".")
    if len(partes) == 4 and all(parte.isdigit() for parte in partes):
        destinos.add(".".join((*partes[:3], "255")))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(4):
            for destino in destinos:
                for porta in (9, 7):
                    sock.sendto(packet, (destino, porta))


class SamsungTv:
    def __init__(self, device: dict[str, object]) -> None:
        self.device = device
        self.host = _valid_host(device.get("host"))

    def _connect(self, timeout: float = 18.0) -> Any:
        name = base64.b64encode("Nebula".encode()).decode()
        query = {"name": name}
        token = str(self.device.get("token", "")).strip()
        if token:
            query["token"] = token
        url = f"ws://{self.host}:8001/api/v2/channels/samsung.remote.control?{urlencode(query)}"
        try:
            ws = websocket.create_connection(
                url,
                timeout=timeout,
                http_no_proxy=[self.host],
            )
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                message = json.loads(ws.recv())
                event = message.get("event")
                if event == "ms.channel.connect":
                    received = str(message.get("data", {}).get("token", "")).strip()
                    if received:
                        self.device["token"] = received
                    return ws
                if event in {"ms.channel.unauthorized", "ms.error"}:
                    raise TvError("A Samsung recusou o pareamento. Autorize a Nebula na tela da TV.")
            raise TvError("A Samsung não confirmou o pareamento a tempo.")
        except TvError:
            raise
        except Exception as exc:
            raise TvError("Não consegui conectar à Samsung. Confira se ela está ligada.") from exc

    def pair(self) -> None:
        ws = self._connect(25.0)
        ws.close()

    def action(self, action: str) -> None:
        if action == "power_on":
            wake_on_lan(str(self.device.get("mac", "")), host=self.host)
            return
        key = SAMSUNG_KEYS.get(action)
        if key is None:
            raise TvError("Esse comando ainda não é compatível com a Samsung.")
        ws = self._connect()
        try:
            ws.send(json.dumps({
                "method": "ms.remote.control",
                "params": {
                    "Cmd": "Click",
                    "DataOfCmd": key,
                    "Option": "false",
                    "TypeOfRemote": "SendRemoteKey",
                },
            }))
        finally:
            ws.close()

    def open_youtube(self, url: str) -> None:
        """Abre um vídeo do YouTube pelo canal remoto do Tizen."""
        ws = self._connect()
        app_id = "111299001912"
        try:
            try:
                ws.settimeout(3.5)
                ws.send(json.dumps({
                    "method": "ms.channel.emit",
                    "params": {"event": "ed.installedApp.get", "to": "host", "data": ""},
                }))
                limite = time.monotonic() + 3.5
                while time.monotonic() < limite:
                    mensagem = json.loads(ws.recv())
                    if mensagem.get("event") != "ed.installedApp.get":
                        continue
                    aplicativos = mensagem.get("data", [])
                    if isinstance(aplicativos, str):
                        aplicativos = json.loads(aplicativos)
                    if isinstance(aplicativos, list):
                        youtube = next((
                            app for app in aplicativos if isinstance(app, dict)
                            and "youtube" in str(app.get("name") or app.get("title") or "").casefold()
                        ), None)
                        if youtube:
                            app_id = str(youtube.get("appId") or youtube.get("app_id") or app_id)
                    break
            except Exception:
                pass
            ws.send(json.dumps({
                "method": "ms.channel.emit",
                "params": {
                    "event": "ed.apps.launch",
                    "to": "host",
                    "data": {
                        "action_type": "DEEP_LINK",
                        "appId": app_id,
                        "metaTag": url,
                    },
                },
            }))
        finally:
            ws.close()

    def open_link(self, url: str) -> None:
        # Tizen does not expose one universal browser deep-link API; opening
        # the URL through the existing YouTube channel remains the compatible path.
        self.open_youtube(url)


class LgWebOsTv:
    def __init__(self, device: dict[str, object]) -> None:
        self.device = device
        self.host = _valid_host(device.get("host"))
        self._request_id = 0

    def _connect_socket(self, timeout: float) -> Any:
        last_error: Exception | None = None
        for url in (f"ws://{self.host}:3000", f"wss://{self.host}:3001"):
            try:
                return websocket.create_connection(
                    url,
                    timeout=timeout,
                    sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False},
                    http_no_proxy=[self.host],
                    origin="null",
                )
            except Exception as exc:
                last_error = exc
        raise TvError("Não consegui conectar à LG webOS. Confira se ela está ligada.") from last_error

    def _connect(self, timeout: float = 25.0) -> Any:
        ws = self._connect_socket(timeout)
        payload: dict[str, object] = {
            "pairingType": "PROMPT",
            "manifest": {
                "manifestVersion": 1,
                "appVersion": "1.0",
                "localizedAppNames": {"": "Nebula Controle Universal"},
                "permissions": LG_PERMISSIONS,
            },
        }
        client_key = str(self.device.get("client_key", "")).strip()
        if client_key:
            payload["client-key"] = client_key
        ws.send(json.dumps({"id": "register", "type": "register", "payload": payload}))
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                message = json.loads(ws.recv())
                if message.get("type") == "registered":
                    received = str(message.get("payload", {}).get("client-key", "")).strip()
                    if received:
                        self.device["client_key"] = received
                    return ws
                if message.get("type") == "error":
                    raise TvError("A LG recusou o pareamento. Autorize a Nebula na tela da TV.")
        except Exception:
            ws.close()
            raise
        ws.close()
        raise TvError("A LG não confirmou o pareamento a tempo.")

    def _request(self, ws: Any, uri: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self._request_id += 1
        request_id = f"nebula_{self._request_id}"
        ws.send(json.dumps({
            "id": request_id,
            "type": "request",
            "uri": uri,
            "payload": payload or {},
        }))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            message = json.loads(ws.recv())
            if message.get("id") != request_id:
                continue
            if message.get("type") == "error" or message.get("payload", {}).get("returnValue") is False:
                raise TvError("A LG recusou esse comando.")
            response = message.get("payload", {})
            return response if isinstance(response, dict) else {}
        raise TvError("A LG não respondeu ao comando.")

    def pair(self) -> None:
        ws = self._connect(30.0)
        ws.close()

    def action(self, action: str) -> None:
        if action == "power_on":
            wake_on_lan(str(self.device.get("mac", "")), host=self.host)
            return
        ws = self._connect()
        try:
            request = LG_REQUESTS.get(action)
            if request is not None:
                self._request(ws, *request)
                return
            button = LG_BUTTONS.get(action)
            if button is None:
                raise TvError("Esse comando ainda não é compatível com a LG.")
            pointer = self._request(
                ws,
                "ssap://com.webos.service.networkinput/getPointerInputSocket",
            )
            socket_path = str(pointer.get("socketPath", "")).strip()
            if not socket_path:
                raise TvError("A LG não liberou o controle direcional.")
            pointer_ws = websocket.create_connection(
                socket_path,
                timeout=8,
                sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False},
                http_no_proxy=[self.host],
                origin="null",
            )
            try:
                pointer_ws.send(f"type:button\nname:{button}\n\n")
                pointer_ws.settimeout(4)
                try:
                    reply = pointer_ws.recv()
                except (websocket.WebSocketTimeoutException, TimeoutError):
                    reply = ""
                if reply and isinstance(reply, bytes):
                    reply = reply.decode("utf-8", errors="replace")
                if isinstance(reply, str) and "error" in reply.casefold():
                    raise TvError("A LG recusou o botão do controle remoto.")
            finally:
                pointer_ws.close()
        finally:
            ws.close()

    def open_youtube(self, url: str) -> None:
        self.open_link(url)

    def open_link(self, url: str) -> None:
        ws = self._connect()
        try:
            self._request(
                ws,
                "ssap://system.launcher/launch",
                {"id": "com.webos.app.browser", "params": {"contentTarget": url}},
            )
        finally:
            ws.close()


class TvManager:
    ACTIONS = frozenset({"power_on", *SAMSUNG_KEYS, *LG_REQUESTS, *LG_BUTTONS})

    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file
        self._lock = threading.RLock()
        self._devices = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, dict[str, object]] = {}
        for device_id, item in data.items():
            if not isinstance(device_id, str) or not isinstance(item, dict):
                continue
            try:
                item["host"] = _valid_host(item.get("host"))
            except TvError:
                continue
            if item.get("brand") in {"samsung", "lg"}:
                result[device_id] = item
        return result

    def _save(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.config_file.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self._devices, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.config_file)

    @staticmethod
    def _device_id(brand: str, host: str) -> str:
        return f"{brand}-{host.replace('.', '-')}"

    @staticmethod
    def _local_networks() -> list[ipaddress.IPv4Network]:
        configured = os.environ.get("NEBULA_TV_SUBNET", "").strip()
        networks: list[ipaddress.IPv4Network] = []
        if configured:
            for raw in configured.split(",")[:4]:
                try:
                    network = ipaddress.ip_network(raw.strip(), strict=False)
                except ValueError:
                    continue
                if isinstance(network, ipaddress.IPv4Network) and network.is_private and network.prefixlen >= 24:
                    networks.append(network)
        if networks:
            return networks
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                local = ipaddress.ip_address(sock.getsockname()[0])
            if isinstance(local, ipaddress.IPv4Address) and local.is_private:
                return [ipaddress.ip_network(f"{local}/24", strict=False)]
        except OSError:
            pass
        return []

    @staticmethod
    def _probe(host: str) -> dict[str, object] | None:
        if _port_open(host, 8001):
            try:
                with urlopen(f"http://{host}:8001/api/v2/", timeout=1.2) as response:
                    data = json.loads(response.read(64_000))
                device = data.get("device", {}) if isinstance(data, dict) else {}
                if isinstance(device, dict) and str(device.get("OS", "")).casefold() == "tizen":
                    return {
                        "brand": "samsung",
                        "host": host,
                        "name": str(device.get("name") or data.get("name") or "Samsung TV"),
                        "model": str(device.get("modelName") or device.get("model") or "Tizen"),
                        "mac": str(device.get("wifiMac") or _arp_mac(host)),
                    }
            except Exception:
                pass
        if _port_open(host, 3000):
            return {
                "brand": "lg",
                "host": host,
                "name": "LG webOS TV",
                "model": "webOS",
                "mac": _arp_mac(host),
            }
        return None

    def discover(self) -> list[dict[str, object]]:
        hosts: list[str] = []
        for network in self._local_networks():
            hosts.extend(str(host) for host in network.hosts())
        found: list[dict[str, object]] = []
        with ThreadPoolExecutor(max_workers=48, thread_name_prefix="NebulaTvScan") as pool:
            futures = {pool.submit(self._probe, host): host for host in hosts[:1024]}
            for future in as_completed(futures):
                try:
                    device = future.result()
                except Exception:
                    continue
                if device is not None:
                    found.append(device)
        with self._lock:
            for device in found:
                device_id = self._device_id(str(device["brand"]), str(device["host"]))
                previous = self._devices.get(device_id, {})
                previous.update(device)
                previous["id"] = device_id
                self._devices[device_id] = previous
            self._save()
        return self.list()

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            devices = [dict(item) for item in self._devices.values()]
        public = []
        for item in devices:
            brand = str(item.get("brand", ""))
            host = str(item.get("host", ""))
            public.append({
                "id": str(item.get("id", self._device_id(brand, host))),
                "brand": brand,
                "host": host,
                "name": str(item.get("name", "Smart TV")),
                "model": str(item.get("model", "")),
                "online": _port_open(host, 8001 if brand == "samsung" else 3000, 0.35),
                "paired": bool(item.get("token") if brand == "samsung" else item.get("client_key")),
                "can_power_on": bool(item.get("mac")),
            })
        return sorted(public, key=lambda item: (str(item["name"]), str(item["host"])))

    def _device(self, device_id: object) -> dict[str, object]:
        if not isinstance(device_id, str) or not re.fullmatch(r"[a-z0-9.-]{3,80}", device_id):
            raise TvError("Selecione uma TV válida.")
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                raise TvError("Essa TV não está cadastrada.")
            return device

    @staticmethod
    def _driver(device: dict[str, object]) -> SamsungTv | LgWebOsTv:
        if device.get("brand") == "samsung":
            return SamsungTv(device)
        if device.get("brand") == "lg":
            return LgWebOsTv(device)
        raise TvError("A marca dessa TV ainda não é compatível.")

    @staticmethod
    def _paired(device: dict[str, object]) -> bool:
        return bool(
            device.get("token")
            if device.get("brand") == "samsung"
            else device.get("client_key")
        )

    def _run_action(self, device: dict[str, object], action: str) -> None:
        if action != "power_on" and not self._paired(device):
            raise TvError(
                "A TV ainda não foi pareada. Ligue-a e autorize a Nebula na tela."
            )
        self._driver(device).action(action)

    def pair(self, device_id: object) -> dict[str, object]:
        device = self._device(device_id)
        self._driver(device).pair()
        with self._lock:
            self._save()
        return next(item for item in self.list() if item["id"] == device_id)

    def action(self, device_id: object, action: object) -> dict[str, object]:
        if not isinstance(action, str) or action not in self.ACTIONS:
            raise TvError("O comando solicitado não é permitido.")
        device = self._device(device_id)
        self._run_action(device, action)
        with self._lock:
            self._save()
        return {"ok": True, "message": "Comando enviado à TV.", "action": action}

    @staticmethod
    def _youtube_url(query: object) -> str:
        texto = str(query or "").strip()
        if not texto or len(texto) > 300:
            raise TvError("Digite a música ou cole um link do YouTube.")
        parsed = urlparse(texto)
        if parsed.scheme in {"http", "https"} and (
            parsed.hostname == "youtu.be"
            or str(parsed.hostname or "").endswith("youtube.com")
        ):
            return texto
        try:
            from youtube_player import primeiro_video

            resolvido = primeiro_video(texto)
        except Exception:
            resolvido = None
        return resolvido or f"https://www.youtube.com/results?search_query={quote_plus(texto)}"

    def _run_many(self, operation: Any) -> dict[str, object]:
        with self._lock:
            devices = [dict(item) for item in self._devices.values()]
        if not devices:
            raise TvError("Busque as Smart TVs da casa primeiro.")
        results: list[dict[str, object]] = []
        with ThreadPoolExecutor(
            max_workers=min(8, len(devices)), thread_name_prefix="NebulaTvGroup"
        ) as pool:
            futures = {pool.submit(operation, device): device for device in devices}
            for future in as_completed(futures):
                device = futures[future]
                try:
                    future.result()
                    results.append({
                        "id": device.get("id"), "name": device.get("name"), "ok": True,
                    })
                except Exception as exc:
                    results.append({
                        "id": device.get("id"), "name": device.get("name"),
                        "ok": False, "error": str(exc),
                    })
        successes = sum(bool(item["ok"]) for item in results)
        with self._lock:
            self._save()
        return {
            "ok": successes > 0,
            "successes": successes,
            "failures": len(results) - successes,
            "results": results,
        }

    def action_all(self, action: object) -> dict[str, object]:
        if not isinstance(action, str) or action not in self.ACTIONS:
            raise TvError("O comando solicitado não é permitido.")
        result = self._run_many(lambda device: self._run_action(device, action))
        if not result["ok"]:
            raise TvError("Nenhuma TV respondeu ao comando em grupo.")
        if action == "power_on":
            mensagem = (
                f"Sinal de ligar enviado para {result['successes']} TV(s), sem confirmação "
                "de que despertaram. Ative a inicialização por rede nas TVs."
            )
            result["delivery"] = "unconfirmed"
        else:
            mensagem = f"Comando confirmado por {result['successes']} TV(s)."
            result["delivery"] = "confirmed"
        result.update({"message": mensagem, "action": action})
        return result

    def youtube(self, query: object, device_id: object | None = None) -> dict[str, object]:
        url = self._youtube_url(query)
        if device_id:
            device = self._device(device_id)
            self._driver(device).open_youtube(url)
            with self._lock:
                self._save()
            return {
                "ok": True, "message": "YouTube aberto na TV selecionada.",
                "successes": 1, "failures": 0, "url": url,
            }
        result = self._run_many(lambda device: self._driver(device).open_youtube(url))
        if not result["ok"]:
            raise TvError("Nenhuma TV conseguiu abrir o YouTube.")
        result.update({
            "message": f"YouTube enviado para {result['successes']} TV(s).",
            "url": url,
        })
        return result

    def link(self, url: object, device_id: object | None = None) -> dict[str, object]:
        if not isinstance(url, str) or not re.fullmatch(r"https://[^\s]{6,2048}", url.strip(), re.IGNORECASE):
            raise TvError("Cole um link HTTPS válido de YouTube, Spotify ou outro serviço.")
        alvo = self._device(device_id) if device_id else None
        if alvo is not None:
            self._driver(alvo).open_link(url.strip())
            with self._lock:
                self._save()
            return {"ok": True, "message": "Link aberto na TV selecionada.", "successes": 1, "failures": 0}
        result = self._run_many(lambda device: self._driver(device).open_link(url.strip()))
        if not result["ok"]:
            raise TvError("Nenhuma TV conseguiu abrir o link.")
        result["message"] = f"Link enviado para {result['successes']} TV(s)."
        return result


__all__ = ["TvError", "TvManager", "wake_on_lan"]
