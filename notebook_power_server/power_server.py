"""Hub doméstico autenticado da Nebula: Wake-on-LAN e Smart TVs."""

from __future__ import annotations

import hmac
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

try:
    from versao import VERSAO_NEBULA
except ImportError:
    try:
        texto_versao = (Path(__file__).resolve().parent.parent / "versao.py").read_text(
            encoding="utf-8"
        )
        achou_versao = re.search(
            r'VERSAO_NEBULA\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']',
            texto_versao,
        )
        VERSAO_NEBULA = achou_versao.group(1) if achou_versao else "desconhecida"
    except OSError:
        VERSAO_NEBULA = "desconhecida"

try:
    from .tv_control import TvError, TvManager
    from .universal_control import UniversalController
    from .air_timer import AirTimer
except ImportError:
    from tv_control import TvError, TvManager
    from universal_control import UniversalController
    from air_timer import AirTimer

try:
    from abajur_tuya import ConfiguracaoTuya, ControleAbajurTuya
    from abajur_wifi import ErroAbajur
except ImportError:
    ConfiguracaoTuya = ControleAbajurTuya = None  # type: ignore[assignment,misc]
    class ErroAbajur(RuntimeError):
        pass

try:
    from ar_ir_direto import ControleArDireto, ErroAr
except ImportError:
    ControleArDireto = None  # type: ignore[assignment,misc]
    class ErroAr(RuntimeError):
        pass


PORT = 8766
_POWER_TOKEN_CONFIGURADO = os.environ.get("NEBULA_POWER_TOKEN", "").strip()
POWER_TOKEN = _POWER_TOKEN_CONFIGURADO or secrets.token_urlsafe(32)
TARGET_MAC = os.environ.get("NEBULA_PC_MAC", "00:E0:23:7C:7B:4D")
BROADCAST = os.environ.get("NEBULA_BROADCAST", "192.168.15.255")
MAX_BODY_BYTES = 16_384
MAX_UPDATE_BYTES = 160 * 1024 * 1024
MONITOR_LOG_FILE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "NebulaPower" / "server.log"
)
TVS = TvManager()
_PC_AGENT_URL = os.environ.get("NEBULA_PC_AGENT_URL", "").strip().rstrip("/")
PC_AGENT_URLS = (
    (_PC_AGENT_URL,)
    if _PC_AGENT_URL
    else (
        "http://192.168.15.12:8765",
        "https://desktop-0sdb1i7.tail46f27e.ts.net",
    )
)
NOTEBOOK_FALLBACK_DELAY = max(
    15, int(os.environ.get("NEBULA_NOTEBOOK_FALLBACK_SECONDS", "45"))
)
NOTEBOOK_ASSISTANT = Path(os.environ.get(
    "NEBULA_NOTEBOOK_ASSISTANT",
    str(Path(sys.executable).resolve().parent / "NebulaNotebook.exe"),
))


class ServerMonitor:
    """Métricas e eventos do hub, compartilhados com a janela de monitoramento."""

    def __init__(self, log_file: Path = MONITOR_LOG_FILE) -> None:
        self.log_file = log_file
        self.started_at = time.time()
        self.lock = threading.RLock()
        self.events: queue.Queue[str] = queue.Queue()
        self.recent: deque[str] = deque(maxlen=500)
        self.total_requests = 0
        self.successful_requests = 0
        self.denied_requests = 0
        self.failed_requests = 0
        self.clients: dict[str, float] = {}
        self.last_client = "—"

    def _publish(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
        with self.lock:
            self.recent.append(line)
        self.events.put(line)
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            if self.log_file.exists() and self.log_file.stat().st_size > 2_000_000:
                rotated = self.log_file.with_suffix(".log.1")
                rotated.unlink(missing_ok=True)
                self.log_file.replace(rotated)
            with self.log_file.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            pass

    def record_event(self, message: str) -> None:
        self._publish(message)

    def record_request(self, method: str, path: str, status: int, client: str) -> None:
        with self.lock:
            self.total_requests += 1
            if 200 <= status < 400:
                self.successful_requests += 1
            elif status in (401, 403):
                self.denied_requests += 1
            else:
                self.failed_requests += 1
            self.clients[client] = time.time()
            self.last_client = client
        self._publish(f"{client:<15} {method:<6} {path:<22} → {status}")

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            now = time.time()
            active_clients = sum(1 for stamp in self.clients.values() if now - stamp <= 300)
            return {
                "total": self.total_requests,
                "successful": self.successful_requests,
                "denied": self.denied_requests,
                "failed": self.failed_requests,
                "active_clients": active_clients,
                "known_clients": len(self.clients),
                "last_client": self.last_client,
                "uptime_seconds": max(0, int(now - self.started_at)),
            }


MONITOR = ServerMonitor()


def notebook_assistant_running() -> bool:
    """Evita abrir uma segunda cópia da assistente no notebook."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq NebulaNotebook.exe", "/NH"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=flags, timeout=10, check=False,
    )
    return "NebulaNotebook.exe" in result.stdout


def show_notebook_assistant(timeout: float = 2.0) -> bool:
    """Pede a instancia grafica que restaure sua janela."""
    request = Request(
        "http://127.0.0.1:8765/api/show",
        data=b"{}",
        method="POST",
        headers={
            "X-Nebula-Power-Token": POWER_TOKEN,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, OSError, URLError, ValueError):
        return False
    return isinstance(result, dict) and bool(result.get("ok"))


def launch_notebook_assistant() -> str:
    if notebook_assistant_running() and show_notebook_assistant():
        return "A Nebula já estava aberta no notebook."
    if not NOTEBOOK_ASSISTANT.is_file():
        raise RuntimeError("NebulaNotebook.exe não está instalado no notebook.")
    if not notebook_assistant_running():
        subprocess.Popen(
            [str(NOTEBOOK_ASSISTANT)], cwd=str(NOTEBOOK_ASSISTANT.parent),
            close_fds=True,
        )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if show_notebook_assistant():
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(
            "A Nebula iniciou no notebook, mas a interface nao respondeu em 30 segundos."
        )
    return "O PC não respondeu; a Nebula foi aberta no notebook."


class HomeBrain:
    """Estado central do controle, mesmo quando o PC gamer esta desligado."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.state: dict[str, object] = {
            "ready": True, "hub": "notebook", "pc_online": False,
            "muted": True, "mode": "manual", "rpm": None,
            "rpm_percent": None, "boost": None, "boost_percent": None,
            "range": None, "receiving": False,
            "telemetry_valid": False, "lamp": "notebook",
            "lamp_power": None, "lamp_selection": None, "error": None,
        }
        self.pc_command: dict[str, object] | None = None
        self.lamp = None
        self.air = ControleArDireto() if ControleArDireto is not None else None
        self.air_timer = AirTimer(self.air, Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Nebula' / 'air_timer.json')
        if ConfiguracaoTuya is not None and ControleAbajurTuya is not None:
            try:
                config = ConfiguracaoTuya.carregar()
                if config is not None:
                    self.lamp = ControleAbajurTuya(config)
            except (ErroAbajur, OSError):
                self.lamp = None

    def queue_pc_launch(self, unlock_proof: object = None) -> dict[str, object]:
        """Registra a ordem que o agente do PC executara depois do Wake-on-LAN."""
        command = {
            "id": uuid.uuid4().hex,
            "action": "launch_nebula",
            "created_at": time.time(),
            "unlock_proof": unlock_proof if isinstance(unlock_proof, dict) else None,
        }
        with self.lock:
            self.pc_command = command
        return dict(command)

    def current_pc_command(self) -> dict[str, object] | None:
        with self.lock:
            return dict(self.pc_command) if self.pc_command is not None else None

    def schedule_notebook_fallback(self, command_id: str) -> None:
        thread = threading.Thread(
            target=self._notebook_fallback_worker,
            args=(command_id,),
            name=f"NebulaFallback-{command_id[:8]}",
            daemon=True,
        )
        thread.start()

    def _notebook_fallback_worker(self, command_id: str) -> None:
        time.sleep(NOTEBOOK_FALLBACK_DELAY)
        with self.lock:
            current = self.pc_command
            if not current or current.get("id") != command_id:
                return
        try:
            self._pc("GET")
            with self.lock:
                self.state["pc_online"] = True
            return
        except RuntimeError:
            with self.lock:
                self.state["pc_online"] = False
        try:
            message = launch_notebook_assistant()
            with self.lock:
                self.state["fallback"] = "notebook"
                self.state["fallback_message"] = message
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            with self.lock:
                self.state["fallback"] = "failed"
                self.state["fallback_message"] = str(exc)

    def _pc(self, method: str, data: dict[str, object] | None = None) -> dict[str, object]:
        body = None if data is None else json.dumps(data).encode("utf-8")
        last_error: Exception | None = None
        for endpoint in PC_AGENT_URLS:
            request = Request(
                endpoint + "/api/control", data=body, method=method,
                headers={
                    "X-Nebula-Power-Token": POWER_TOKEN,
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=3) as response:
                    result = json.loads(response.read().decode("utf-8"))
                if isinstance(result, dict):
                    return result
                last_error = ValueError("resposta invalida")
            except (HTTPError, OSError, URLError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(
            "O PC gamer esta desligado ou o agente Nebula nao respondeu."
        ) from last_error

    def status(self) -> dict[str, object]:
        try:
            remote = self._pc("GET")
            pc_state = remote.get("state")
            if isinstance(pc_state, dict):
                with self.lock:
                    lamp_power = self.state.get("lamp_power")
                    lamp_selection = self.state.get("lamp_selection")
                    self.state.update(pc_state)
                    self.state.update({
                        "hub": "notebook", "pc_online": True,
                        "lamp_power": lamp_power,
                        "lamp_selection": lamp_selection,
                    })
        except RuntimeError:
            with self.lock:
                self.state["pc_online"] = False
                if self.state.get("mode") in {"rpm", "boost", "ambilight", "music"}:
                    self.state["receiving"] = False
        with self.lock:
            estado = dict(self.state)
        if self.air is not None:
            estado["air"] = self.air.estado()
            estado["air"]["timer"] = self.air_timer.status()
        return estado

    def action(self, action: str, value: object) -> dict[str, object]:
        action = str(action).strip().casefold()
        if action.startswith("air."):
            if self.air is None:
                raise RuntimeError("O Smart IR ainda nao foi configurado no notebook.")
            if action == "air.timer":
                return {**self.air_timer.set(value), "state": self.status()}
            resultado = self.air.executar(action.removeprefix("air."), value)
            if action == "air.power" and not value:
                self.air_timer.set(0)
            return {**resultado, "state": self.status()}
        if action.startswith("lamp."):
            lamp = self.lamp
            if lamp is None:
                raise RuntimeError(
                    "O abajur ainda nao foi configurado no cerebro do notebook."
                )
            try:
                self._pc("POST", {"action": "mode", "value": "manual"})
            except RuntimeError:
                pass
            if action == "lamp.power":
                lamp.energia(bool(value))
                with self.lock: self.state["lamp_power"] = bool(value)
            elif action == "lamp.color":
                lamp.cor(str(value))
                with self.lock:
                    self.state["lamp_power"] = True
                    self.state["lamp_selection"] = str(value)
            elif action == "lamp.temperature":
                lamp.temperatura(str(value))
                with self.lock:
                    self.state["lamp_power"] = True
                    self.state["lamp_selection"] = str(value)
            elif action == "lamp.brightness":
                lamp.brilho(int(value))
            else:
                raise ValueError("Acao do abajur invalida.")
            with self.lock: self.state["mode"] = "manual"
            return {"ok": True, "message": "Abajur controlado pelo notebook.", "state": self.status()}

        if action == "mute":
            with self.lock: self.state["muted"] = bool(value)
            try:
                result = self._pc("POST", {"action": action, "value": value})
                if isinstance(result.get("state"), dict):
                    with self.lock: self.state.update(result["state"])  # type: ignore[arg-type]
            except RuntimeError:
                pass
            return {"ok": True, "message": "Modo mudo atualizado no notebook.", "state": self.status()}

        if action == "mode" and str(value).casefold() == "manual":
            with self.lock: self.state["mode"] = "manual"
            try:
                return self._pc("POST", {"action": action, "value": value})
            except RuntimeError:
                return {"ok": True, "message": "Modos desativados no hub.", "state": self.status()}
        result = self._pc("POST", {"action": action, "value": value})
        state = result.get("state")
        if isinstance(state, dict):
            with self.lock:
                self.state.update(state)
                self.state["hub"] = "notebook"
                self.state["pc_online"] = True
        return {**result, "state": self.status()}


BRAIN = HomeBrain()


def wake() -> None:
    mac = bytes.fromhex(TARGET_MAC.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(4):
            sock.sendto(packet, (BROADCAST, 9))


def preparar_atualizacao(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    """Recebe um executavel validado e agenda a troca depois da resposta HTTP."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Atualizacao automatica so esta disponivel no hub instalado.")
    try:
        tamanho = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Tamanho da atualizacao invalido.") from exc
    if tamanho < 1024 or tamanho > MAX_UPDATE_BYTES:
        raise RuntimeError("O pacote de atualizacao tem tamanho invalido.")
    hash_esperado = handler.headers.get("X-Nebula-SHA256", "").strip().casefold()
    if len(hash_esperado) != 64 or any(c not in "0123456789abcdef" for c in hash_esperado):
        raise RuntimeError("A atualizacao nao informou um SHA-256 valido.")

    alvo = Path(sys.executable).resolve()
    pasta = alvo.parent
    novo = pasta / "NebulaPowerServer.update.exe"
    temporario = pasta / "NebulaPowerServer.update.tmp"
    digest = hashlib.sha256()
    restante = tamanho
    with temporario.open("wb") as arquivo:
        while restante:
            bloco = handler.rfile.read(min(1024 * 1024, restante))
            if not bloco:
                raise RuntimeError("A atualizacao chegou incompleta.")
            arquivo.write(bloco)
            digest.update(bloco)
            restante -= len(bloco)
    if not hmac.compare_digest(digest.hexdigest(), hash_esperado):
        temporario.unlink(missing_ok=True)
        raise RuntimeError("A atualizacao falhou na verificacao de integridade.")
    with temporario.open("rb") as arquivo:
        if arquivo.read(2) != b"MZ":
            temporario.unlink(missing_ok=True)
            raise RuntimeError("O pacote recebido nao e um executavel Windows valido.")
    temporario.replace(novo)

    script = pasta / "aplicar_atualizacao.ps1"
    launcher = pasta / "iniciar_servicos_notebook.ps1"
    script.write_text(
        "param([int]$Processo,[string]$Novo,[string]$Alvo,[string]$Launcher)\n"
        "$ErrorActionPreference='Stop'\n"
        "Wait-Process -Id $Processo -ErrorAction SilentlyContinue\n"
        "$limite=(Get-Date).AddSeconds(30)\n"
        "do {\n"
        "  try { Copy-Item -LiteralPath $Novo -Destination $Alvo -Force; $ok=$true }\n"
        "  catch { Start-Sleep -Milliseconds 400 }\n"
        "} while (-not $ok -and (Get-Date) -lt $limite)\n"
        "if (-not $ok) { exit 2 }\n"
        "Remove-Item -LiteralPath $Novo -Force -ErrorAction SilentlyContinue\n"
        "Start-Process -FilePath $Alvo -WorkingDirectory (Split-Path -Parent $Alvo) -WindowStyle Normal\n",
        encoding="utf-8-sig",
    )
    subprocess.Popen(
        [
            "powershell.exe", "-NoProfile", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Processo", str(os.getpid()), "-Novo", str(novo),
            "-Alvo", str(alvo), "-Launcher", str(launcher),
        ],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
    threading.Timer(1.0, os._exit, args=(0,)).start()
    return {
        "ok": True,
        "message": "Atualizacao recebida; o hub sera reiniciado automaticamente.",
        "version": handler.headers.get("X-Nebula-Version", "").strip(),
    }


def preparar_assistente_notebook(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    """Instala a cópia da interface completa usada no fallback do notebook."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Atualização disponível somente no hub instalado.")
    try:
        tamanho = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Tamanho da atualização inválido.") from exc
    if tamanho < 1024 or tamanho > MAX_UPDATE_BYTES:
        raise RuntimeError("O pacote da assistente tem tamanho inválido.")
    hash_esperado = handler.headers.get("X-Nebula-SHA256", "").strip().casefold()
    if len(hash_esperado) != 64 or any(c not in "0123456789abcdef" for c in hash_esperado):
        raise RuntimeError("A atualização não informou um SHA-256 válido.")

    alvo = Path(sys.executable).resolve().parent / "NebulaNotebook.exe"
    temporario = alvo.with_suffix(".update.tmp")
    digest = hashlib.sha256()
    restante = tamanho
    with temporario.open("wb") as arquivo:
        while restante:
            bloco = handler.rfile.read(min(1024 * 1024, restante))
            if not bloco:
                raise RuntimeError("A atualização chegou incompleta.")
            arquivo.write(bloco)
            digest.update(bloco)
            restante -= len(bloco)
    if not hmac.compare_digest(digest.hexdigest(), hash_esperado):
        temporario.unlink(missing_ok=True)
        raise RuntimeError("A atualização falhou na verificação de integridade.")
    with temporario.open("rb") as arquivo:
        if arquivo.read(2) != b"MZ":
            temporario.unlink(missing_ok=True)
            raise RuntimeError("O pacote não é um executável Windows válido.")

    estava_aberta = notebook_assistant_running()
    if estava_aberta:
        subprocess.run(
            ["taskkill.exe", "/IM", "NebulaNotebook.exe", "/F"],
            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10, check=False,
        )
    temporario.replace(alvo)
    if estava_aberta:
        subprocess.Popen([str(alvo)], cwd=str(alvo.parent), close_fds=True)
    return {
        "ok": True,
        "message": "Assistente de fallback instalada no notebook.",
        "version": handler.headers.get("X-Nebula-Version", "").strip(),
    }


def wake_nebula() -> dict[str, object]:
    wake()
    command = BRAIN.queue_pc_launch()
    BRAIN.schedule_notebook_fallback(str(command["id"]))
    return {"ok": True, "message": "Sinal enviado; aguardando a Nebula iniciar.",
            "command_id": command["id"], "delivery": "unconfirmed"}


UNIVERSAL = UniversalController(BRAIN, TVS, wake_nebula)


class Handler(BaseHTTPRequestHandler):
    def authorized(self) -> bool:
        supplied = self.headers.get("X-Nebula-Power-Token", "")
        return hmac.compare_digest(supplied, POWER_TOKEN)

    def respond(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        MONITOR.record_request(
            self.command,
            urlparse(self.path).path,
            status,
            self.client_address[0],
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict[str, object]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise TvError("Tamanho da requisição inválido.") from exc
        if size < 0 or size > MAX_BODY_BYTES:
            raise TvError("A requisição é grande demais.")
        try:
            data = json.loads(self.rfile.read(size) or b"{}")
        except (UnicodeDecodeError, ValueError) as exc:
            raise TvError("O corpo da requisição não contém JSON válido.") from exc
        if not isinstance(data, dict):
            raise TvError("O corpo da requisição precisa ser um objeto JSON.")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if not self.authorized():
            self.respond(401, {"error": "Não autorizado"})
        elif path == "/health":
            self.respond(200, {
                "ok": True,
                "service": "Nebula Home Hub",
                "version": VERSAO_NEBULA,
                "features": ["wake_on_lan", "smart_tvs", "tv_groups", "youtube_multiroom", "central_brain", "lamp", "air_ir_local", "pc_agent", "pc_launch_command", "auto_update", "notebook_fallback", "assistant_update", "universal_control", "home_assistant"],
            })
        elif path == "/pc/command":
            self.respond(200, {"command": BRAIN.current_pc_command()})
        elif path == "/control":
            self.respond(200, {"state": BRAIN.status()})
        elif path == "/tvs":
            self.respond(200, {"tvs": TVS.list()})
        elif path == "/universal/devices":
            try:
                self.respond(200, UNIVERSAL.devices())
            except Exception:
                self.respond(503, {"error": "Não foi possível atualizar os dispositivos."})
        else:
            self.respond(404, {"error": "Não encontrado"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self.authorized():
            self.respond(401, {"error": "Não autorizado"})
            return
        try:
            if path == "/update":
                self.respond(202, preparar_atualizacao(self))
                return
            if path == "/assistant-update":
                self.respond(200, preparar_assistente_notebook(self))
                return
            data = self.body()
            if path == "/wake":
                wake()
                command = BRAIN.queue_pc_launch(data.get("unlock_proof"))
                BRAIN.schedule_notebook_fallback(str(command["id"]))
                MONITOR.record_event(
                    f"Inicialização autorizada; comando {str(command['id'])[:8]} enviado."
                )
                self.respond(200, {
                    "ok": True,
                    "message": "Sinal enviado; se o PC não responder, a Nebula abrirá no notebook.",
                    "command_id": command["id"],
                    "fallback_seconds": NOTEBOOK_FALLBACK_DELAY,
                })
            elif path == "/tvs/discover":
                UNIVERSAL.invalidate()
                self.respond(200, {"ok": True, "tvs": TVS.discover()})
            elif path == "/tvs/pair":
                self.respond(200, {"ok": True, "tv": TVS.pair(data.get("id"))})
            elif path == "/tvs/action":
                self.respond(200, TVS.action(data.get("id"), data.get("action")))
            elif path == "/tvs/action-all":
                self.respond(200, TVS.action_all(data.get("action")))
            elif path == "/tvs/youtube":
                self.respond(200, TVS.youtube(data.get("query"), data.get("id")))
            elif path == "/tvs/link":
                self.respond(200, TVS.link(data.get("url"), data.get("id")))
            elif path == "/control":
                self.respond(200, BRAIN.action(str(data.get("action", "")), data.get("value")))
            elif path == "/universal/action":
                self.respond(200, UNIVERSAL.action(data.get("device_id"), data.get("action")))
            elif path == "/universal/discover":
                self.respond(200, UNIVERSAL.discover())
            else:
                self.respond(404, {"error": "Não encontrado"})
        except (TvError, ErroAbajur, ErroAr, RuntimeError, ValueError) as exc:
            self.respond(400, {"error": str(exc)})
        except Exception:
            self.respond(500, {"error": "O hub não conseguiu concluir a operação."})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _format_uptime(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def run_monitor_window(server: ThreadingHTTPServer) -> None:
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title(f"Nebula Home Hub {VERSAO_NEBULA} — Monitor")
    root.geometry("920x590")
    root.minsize(720, 450)
    root.configure(bg="#080d16")

    title = tk.Frame(root, bg="#080d16")
    title.pack(fill="x", padx=24, pady=(20, 8))
    tk.Label(
        title, text="NEBULA HOME HUB", bg="#080d16", fg="#f5f9ff",
        font=("Segoe UI", 20, "bold"),
    ).pack(side="left")
    tk.Label(
        title, text="● SERVIDOR ATIVO", bg="#080d16", fg="#44dc8c",
        font=("Segoe UI", 11, "bold"),
    ).pack(side="right")
    tk.Label(
        root,
        text=f"Porta {server.server_port}  •  versão {VERSAO_NEBULA}  •  log: {MONITOR_LOG_FILE}",
        bg="#080d16", fg="#8290a6", font=("Segoe UI", 10), anchor="w",
    ).pack(fill="x", padx=24, pady=(0, 16))

    cards = tk.Frame(root, bg="#080d16")
    cards.pack(fill="x", padx=18, pady=(0, 12))
    metric_vars: dict[str, tk.StringVar] = {}
    for key, label in (
        ("total", "REQUISIÇÕES"),
        ("active_clients", "CLIENTES 5 MIN"),
        ("denied", "BLOQUEADAS"),
        ("uptime", "TEMPO ATIVO"),
    ):
        card = tk.Frame(cards, bg="#101a2a", padx=16, pady=12)
        card.pack(side="left", fill="x", expand=True, padx=6)
        variable = tk.StringVar(value="0")
        metric_vars[key] = variable
        tk.Label(
            card, textvariable=variable, bg="#101a2a", fg="#79c6ff",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            card, text=label, bg="#101a2a", fg="#8290a6",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")

    connection_var = tk.StringVar(value="Última conexão: —")
    tk.Label(
        root, textvariable=connection_var, bg="#080d16", fg="#b8c5d8",
        font=("Segoe UI", 10), anchor="w",
    ).pack(fill="x", padx=24, pady=(0, 8))

    log_view = ScrolledText(
        root, bg="#050911", fg="#cfdaea", insertbackground="#cfdaea",
        selectbackground="#174d79", relief="flat", borderwidth=0,
        font=("Cascadia Mono", 10), padx=14, pady=12, wrap="none",
    )
    log_view.pack(fill="both", expand=True, padx=24, pady=(0, 12))
    log_view.configure(state="normal")
    with MONITOR.lock:
        initial_lines = list(MONITOR.recent)
    if initial_lines:
        log_view.insert("end", "\n".join(initial_lines) + "\n")
    log_view.configure(state="disabled")

    footer = tk.Frame(root, bg="#080d16")
    footer.pack(fill="x", padx=24, pady=(0, 18))
    tk.Label(
        footer,
        text="Fechar minimiza a janela; o servidor continua funcionando.",
        bg="#080d16", fg="#6f7c90", font=("Segoe UI", 9),
    ).pack(side="left")

    def clear_view() -> None:
        log_view.configure(state="normal")
        log_view.delete("1.0", "end")
        log_view.configure(state="disabled")

    tk.Button(
        footer, text="Limpar visualização", command=clear_view,
        bg="#15263c", fg="#d9eaff", activebackground="#1d3858",
        activeforeground="#ffffff", relief="flat", padx=14, pady=7,
        font=("Segoe UI", 9, "bold"),
    ).pack(side="right")

    def refresh() -> None:
        new_lines: list[str] = []
        while True:
            try:
                new_lines.append(MONITOR.events.get_nowait())
            except queue.Empty:
                break
        if new_lines:
            log_view.configure(state="normal")
            log_view.insert("end", "\n".join(new_lines) + "\n")
            log_view.see("end")
            log_view.configure(state="disabled")
        state = MONITOR.snapshot()
        metric_vars["total"].set(str(state["total"]))
        metric_vars["active_clients"].set(str(state["active_clients"]))
        metric_vars["denied"].set(str(state["denied"]))
        metric_vars["uptime"].set(_format_uptime(int(state["uptime_seconds"])))
        connection_var.set(
            f"Última conexão: {state['last_client']}  •  "
            f"sucesso: {state['successful']}  •  erros: {state['failed']}"
        )
        root.after(250, refresh)

    root.protocol("WM_DELETE_WINDOW", root.iconify)
    server_thread = threading.Thread(
        target=server.serve_forever, name="NebulaHomeHub", daemon=True
    )
    server_thread.start()
    refresh()
    try:
        root.mainloop()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    if not _POWER_TOKEN_CONFIGURADO:
        raise SystemExit(
            "Configure NEBULA_POWER_TOKEN com pelo menos 24 caracteres antes de iniciar."
        )
    if len(POWER_TOKEN) < 24:
        raise SystemExit("NEBULA_POWER_TOKEN precisa ter pelo menos 24 caracteres.")
    http_server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    BRAIN.air_timer.start()
    MONITOR.record_event(f"Servidor iniciado em 0.0.0.0:{PORT}.")
    try:
        run_monitor_window(http_server)
    except Exception as exc:
        MONITOR.record_event(f"Monitor visual indisponível: {exc}. Servidor em modo silencioso.")
        http_server.serve_forever()
