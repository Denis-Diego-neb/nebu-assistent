"""Hub doméstico autenticado da Nebula: Wake-on-LAN e Smart TVs."""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
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
from urllib.parse import parse_qs, urlparse

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
    import front_assets
except ImportError:
    # Executado de dentro de notebook_power_server/: a pasta do repositório
    # ainda não está no sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        import front_assets
    except ImportError:
        front_assets = None  # type: ignore[assignment]

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
if not _POWER_TOKEN_CONFIGURADO and os.name == "nt":
    # Atualizacoes iniciadas por processos antigos podem herdar um ambiente
    # anterior a configuracao do token do usuario.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            _POWER_TOKEN_CONFIGURADO = str(winreg.QueryValueEx(key, "NEBULA_POWER_TOKEN")[0]).strip()
    except OSError:
        pass
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
MCP_SSH_DESTINATION = os.environ.get(
    "NEBULA_MCP_SSH_DESTINATION", "Nebullar@192.168.15.12"
).strip()
MCP_REMOTE_PROJECT = os.environ.get(
    "NEBULA_MCP_REMOTE_PROJECT", r"C:\Users\Nebullar\Documents\assistente virtual"
).strip()


def launch_mcp_ssh_terminal() -> None:
    """Abre um console visivel no servidor MCP do PC atraves do OpenSSH."""
    ssh = shutil.which("ssh.exe")
    if not ssh:
        raise RuntimeError("O cliente OpenSSH nao esta instalado no notebook.")
    if not MCP_SSH_DESTINATION or not MCP_REMOTE_PROJECT:
        raise RuntimeError("Configure o destino SSH e a pasta remota do MCP.")
    escaped_project = MCP_REMOTE_PROJECT.replace("'", "''")
    remote_python = str(Path(MCP_REMOTE_PROJECT) / ".venv" / "Scripts" / "python.exe")
    escaped_python = remote_python.replace("'", "''")
    remote_script = (
        f"Set-Location -LiteralPath '{escaped_project}'; "
        f"& '{escaped_python}' -m scripts.mcp_console"
    )
    encoded = base64.b64encode(remote_script.encode("utf-16-le")).decode("ascii")
    ssh_command = [
        ssh, "-t", MCP_SSH_DESTINATION,
        "powershell.exe", "-NoLogo", "-NoProfile", "-EncodedCommand", encoded,
    ]
    terminal = shutil.which("wt.exe")
    if terminal:
        command = [terminal, "new-tab", "--title", "Nebula MCP", *ssh_command]
    else:
        command = ["cmd.exe", "/k", *ssh_command]
    subprocess.Popen(command, close_fds=True)


class ServerMonitor:
    """Métricas e eventos do hub, compartilhados com a janela de monitoramento."""

    def __init__(self, log_file: Path = MONITOR_LOG_FILE) -> None:
        self.log_file = log_file
        self.started_at = time.time()
        self.lock = threading.RLock()
        self.events: queue.Queue[str] = queue.Queue()
        self.recent: deque[str] = deque(maxlen=500)
        # Numera cada linha para o console web saber o que ainda não recebeu.
        self.sequence = 0
        self.total_requests = 0
        self.successful_requests = 0
        self.denied_requests = 0
        self.failed_requests = 0
        self.clients: dict[str, float] = {}
        self.last_client = "—"
        self.sprints: dict = {}
        self.sprints_received = 0.0
        self.sprint_command: str | None = None
        self.mcp_event_ids: deque[str] = deque(maxlen=200)

    def receive_sprints(self, data: dict) -> dict:
        if not isinstance(data.get("counts"), dict) or not isinstance(data.get("recent"), list):
            raise ValueError("Resumo das sprints invalido.")
        if len(data["recent"]) > 3 or not all(type(v) is int and v >= 0 for v in data["counts"].values()):
            raise ValueError("Contagens de sprints invalidas.")
        for item in data["recent"]:
            if not isinstance(item, dict) or not isinstance(item.get("rewards"), dict):
                raise ValueError("Notas de sprint invalidas.")
            for reward in item["rewards"].values():
                if not isinstance(reward, dict) or type(reward.get("delta")) is not int or not -10 <= reward["delta"] <= 10:
                    raise ValueError("Nota de sprint invalida.")
        mcp_events = data.get("mcp_events", [])
        if not isinstance(mcp_events, list) or len(mcp_events) > 8:
            raise ValueError("Eventos MCP invalidos.")
        for event in mcp_events:
            if not isinstance(event, dict):
                raise ValueError("Evento MCP invalido.")
            if not isinstance(event.get("id"), str) or not 1 <= len(event["id"]) <= 64:
                raise ValueError("Identificador MCP invalido.")
            if not isinstance(event.get("tool"), str) or not 1 <= len(event["tool"]) <= 128:
                raise ValueError("Nome de tool MCP invalido.")
            if type(event.get("ok")) is not bool:
                raise ValueError("Resultado MCP invalido.")
            if type(event.get("duration_ms")) is not int or not 0 <= event["duration_ms"] <= 3_600_000:
                raise ValueError("Duracao MCP invalida.")
            if not isinstance(event.get("message", ""), str) or len(event.get("message", "")) > 300:
                raise ValueError("Mensagem MCP invalida.")
        new_mcp_events = []
        with self.lock:
            changed = data.get("evaluated") != self.sprints.get("evaluated")
            self.sprints = data
            self.sprints_received = time.time()
            command = self.sprint_command
            # Repete ate o PC confirmar o estado no proximo heartbeat.
            if command and data.get("paused") == (command == "pause"):
                self.sprint_command = None
                command = None
            for event in mcp_events:
                if event["id"] not in self.mcp_event_ids:
                    self.mcp_event_ids.append(event["id"])
                    new_mcp_events.append(event)
        if changed:
            self.record_event(f"SPRINTS: {data.get('evaluated', 0)} avaliadas / {data.get('total', 0)}; "
                              + "; ".join(str(x)[:200] for x in data.get("alerts", [])[:2]))
        for event in new_mcp_events:
            status = "OK" if event["ok"] else "ERRO"
            message = " ".join(event.get("message", "").split())[:180]
            suffix = f" - {message}" if message else ""
            self.record_event(
                f"MCP {status}: {event['tool']} ({event['duration_ms']} ms){suffix}"
            )
        return {"ok": True, "command": command}

    def sprint_snapshot(self) -> dict:
        with self.lock:
            return {"data": self.sprints.copy(), "age_seconds":
                    int(time.time() - self.sprints_received) if self.sprints_received else None,
                    "pending_command": self.sprint_command}

    def command_sprints(self, command: str) -> None:
        if command not in {"pause", "resume"}:
            raise ValueError("Comando de sprint invalido.")
        with self.lock:
            self.sprint_command = command
        self.record_event("SPRINTS: solicitado " + command + "; aguardando PC.")

    def _publish(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
        with self.lock:
            self.recent.append(line)
            self.sequence += 1
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

    def history_since(self, after: int) -> dict[str, object]:
        """Linhas publicadas depois de ``after``, com o novo cursor.

        ``reset`` avisa que o pedido ficou para trás do buffer e o console
        precisa recomeçar a visualização em vez de emendar linhas soltas.
        """
        with self.lock:
            fim = self.sequence
            inicio = fim - len(self.recent)
            if after >= fim:
                return {"cursor": fim, "lines": [], "reset": False}
            reset = after < inicio
            comeco = 0 if reset else after - inicio
            return {"cursor": fim, "lines": list(self.recent)[comeco:], "reset": reset}

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


class Terminais:
    """Sessões de comando do hub: sprints e tarefas longas que rodam a fio.

    A saída fica num buffer circular com cursor, igual ao log do monitor, para
    o console e as duas IAs acompanharem por polling sem perder linha e sem
    precisarem falar entre si. É execução de comando de verdade: só passa pelo
    ``hub_autorizado`` — de fora da máquina, exige o token.
    """

    MAXIMO_VIVOS = 6
    LINHAS_POR_SESSAO = 4000
    MAXIMO_SESSOES = 24

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sessoes: dict[str, dict[str, object]] = {}

    def _raiz(self, cwd: object) -> Path:
        if not cwd:
            return Path(sys.executable).resolve().parent
        caminho = Path(str(cwd)).expanduser()
        if not caminho.is_dir():
            raise ValueError(f"Pasta inexistente: {caminho}")
        return caminho

    def abrir(self, comando: object, cwd: object = None, autor: object = "usuario") -> dict[str, object]:
        texto = str(comando or "").strip()
        if not texto:
            raise ValueError("Informe um comando.")
        if len(texto) > 4000:
            raise ValueError("Comando longo demais.")
        raiz = self._raiz(cwd)
        with self.lock:
            vivos = sum(1 for s in self.sessoes.values() if s["proc"].poll() is None)
            if vivos >= self.MAXIMO_VIVOS:
                raise ValueError(
                    f"Já há {self.MAXIMO_VIVOS} comandos em execução. Encerre um antes."
                )
        try:
            proc = subprocess.Popen(
                texto, shell=True, cwd=str(raiz),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                # Sem stdin: um comando que pedir confirmação termina em vez de
                # travar a sessão para sempre esperando alguém digitar.
                stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise ValueError(f"Não consegui iniciar: {exc}") from exc
        ident = uuid.uuid4().hex[:12]
        sessao = {
            "id": ident, "comando": texto, "cwd": str(raiz),
            "autor": str(autor or "usuario")[:40], "proc": proc,
            "linhas": deque(maxlen=self.LINHAS_POR_SESSAO), "sequencia": 0,
            "inicio": time.time(), "fim": None, "codigo": None,
        }
        with self.lock:
            self.sessoes[ident] = sessao
            if len(self.sessoes) > self.MAXIMO_SESSOES:
                mortas = [i for i, s in self.sessoes.items()
                          if s["fim"] is not None and i != ident]
                for antiga in sorted(mortas, key=lambda i: self.sessoes[i]["fim"])[
                        : len(self.sessoes) - self.MAXIMO_SESSOES]:
                    self.sessoes.pop(antiga, None)
        threading.Thread(target=self._drenar, args=(sessao,),
                         name=f"terminal-{ident}", daemon=True).start()
        MONITOR.record_event(f"Terminal {ident}: {texto[:90]} ({sessao['autor']}).")
        return self.resumo(ident)

    def _escrever(self, sessao: dict[str, object], linha: str) -> None:
        with self.lock:
            sessao["linhas"].append(linha)
            sessao["sequencia"] = int(sessao["sequencia"]) + 1

    def _drenar(self, sessao: dict[str, object]) -> None:
        proc = sessao["proc"]
        try:
            for linha in proc.stdout:
                self._escrever(sessao, linha.rstrip("\n")[:4000])
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass
            codigo = proc.wait()
            with self.lock:
                sessao["fim"] = time.time()
                sessao["codigo"] = codigo
            self._escrever(sessao, f"[hub] encerrado com código {codigo}")
            MONITOR.record_event(f"Terminal {sessao['id']}: código {codigo}.")

    def resumo(self, ident: str) -> dict[str, object]:
        with self.lock:
            sessao = self.sessoes.get(ident)
            if sessao is None:
                raise ValueError("Sessão desconhecida.")
            return {
                "id": sessao["id"], "comando": sessao["comando"], "cwd": sessao["cwd"],
                "autor": sessao["autor"], "cursor": sessao["sequencia"],
                "executando": sessao["proc"].poll() is None,
                "codigo": sessao["codigo"],
                "inicio": sessao["inicio"], "fim": sessao["fim"],
                "segundos": round((sessao["fim"] or time.time()) - sessao["inicio"], 1),
            }

    def listar(self) -> list[dict[str, object]]:
        with self.lock:
            ids = list(self.sessoes)
        sessoes = []
        for ident in ids:
            try:
                sessoes.append(self.resumo(ident))
            except ValueError:
                continue
        return sorted(sessoes, key=lambda s: s["inicio"], reverse=True)

    def historico(self, ident: str, after: int) -> dict[str, object]:
        """Linhas depois de ``after``; ``reset`` avisa que o cursor ficou para trás."""
        resumo = self.resumo(ident)
        with self.lock:
            sessao = self.sessoes[ident]
            fim = int(sessao["sequencia"])
            linhas = list(sessao["linhas"])
        inicio = fim - len(linhas)
        if after >= fim:
            resumo.update(cursor=fim, lines=[], reset=False)
            return resumo
        reset = after < inicio
        resumo.update(cursor=fim, reset=reset,
                      lines=linhas[0 if reset else after - inicio:])
        return resumo

    def encerrar(self, ident: str) -> dict[str, object]:
        with self.lock:
            sessao = self.sessoes.get(ident)
            if sessao is None:
                raise ValueError("Sessão desconhecida.")
            proc = sessao["proc"]
        if proc.poll() is None:
            # taskkill /T derruba a árvore: shell=True cria um cmd.exe
            # intermediário e matar só ele deixaria o processo real órfão.
            if os.name == "nt":
                subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                               check=False, capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._escrever(sessao, "[hub] encerrado a pedido.")
        return self.resumo(ident)


TERMINAIS = Terminais()


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

    def hub_autorizado(self) -> bool:
        """O console é local por padrão; de fora da máquina exige o token."""
        if self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return True
        return self.authorized()

    def enviar(self, status: int, corpo: bytes, tipo: str) -> None:
        """Resposta crua do console, fora da contagem de requisições do hub.

        O console consulta o log a cada poucos segundos; registrar essas
        chamadas encheria justamente o log que ele mostra.
        """
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def enviar_json(self, status: int, payload: dict[str, object]) -> None:
        self.enviar(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")

    def servir_hub(self, path: str) -> None:
        if not self.hub_autorizado():
            self.enviar_json(401, {"error": "Não autorizado"})
            return
        if path == "/hub":
            self.send_response(303)
            self.send_header("Location", "/hub/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        nome = path[len("/hub/"):]
        if path == "/hub/state":
            metricas = MONITOR.snapshot()
            self.enviar_json(200, {
                "metrics": metricas,
                "uptime": _format_uptime(int(metricas["uptime_seconds"])),
                "sprints": MONITOR.sprint_snapshot(),
                "port": self.server.server_port,
                "version": VERSAO_NEBULA,
                "log_file": str(MONITOR_LOG_FILE),
            })
            return
        if path == "/hub/events":
            try:
                after = int(parse_qs(urlparse(self.path).query).get("after", ["0"])[0] or 0)
            except ValueError:
                after = 0
            self.enviar_json(200, MONITOR.history_since(max(0, after)))
            return
        if path == "/hub/terminal":
            self.enviar_json(200, {"sessions": TERMINAIS.listar()})
            return
        if path.startswith("/hub/terminal/"):
            ident = path[len("/hub/terminal/"):].strip("/")
            try:
                depois = int(parse_qs(urlparse(self.path).query).get("after", ["0"])[0] or 0)
            except ValueError:
                depois = 0
            try:
                self.enviar_json(200, TERMINAIS.historico(ident, max(0, depois)))
            except ValueError as exc:
                self.enviar_json(404, {"error": str(exc)})
            return
        if front_assets is None:
            self.enviar(503, b"Front do hub indisponivel.", "text/plain; charset=utf-8")
            return
        recurso = front_assets.carregar(nome or "hub.html")
        if recurso is None:
            if nome:
                self.enviar(404, b"Nao encontrado", "text/plain; charset=utf-8")
            else:
                self.enviar(200, front_assets.INDISPONIVEL.encode(), "text/html; charset=utf-8")
            return
        corpo, tipo = recurso
        self.enviar(200, corpo, tipo)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/hub" or path.startswith("/hub/"):
            self.servir_hub(path)
            return
        if not self.authorized():
            self.respond(401, {"error": "Não autorizado"})
        elif path == "/health":
            self.respond(200, {
                "ok": True,
                "service": "Nebula Home Hub",
                "version": VERSAO_NEBULA,
                "features": ["wake_on_lan", "smart_tvs", "tv_groups", "youtube_multiroom", "central_brain", "lamp", "air_ir_local", "pc_agent", "pc_launch_command", "auto_update", "notebook_fallback", "assistant_update", "universal_control", "home_assistant", "sprint_monitor", "mcp_audit"],
            })
        elif path == "/pc/command":
            self.respond(200, {"command": BRAIN.current_pc_command()})
        elif path == "/sprints":
            self.respond(200, MONITOR.sprint_snapshot())
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
        if path == "/hub/terminal" or path.startswith("/hub/terminal/"):
            if not self.hub_autorizado():
                self.enviar_json(401, {"error": "Não autorizado"}); return
            try:
                if path == "/hub/terminal":
                    corpo = self.body()
                    aberta = TERMINAIS.abrir(corpo.get("command"), corpo.get("cwd"),
                                             corpo.get("author", "usuario"))
                    self.enviar_json(201, aberta); return
                ident = path[len("/hub/terminal/"):].strip("/")
                if ident.endswith("/stop"):
                    self.enviar_json(200, TERMINAIS.encerrar(ident[:-len("/stop")]))
                    return
                self.enviar_json(404, {"error": "Rota desconhecida."}); return
            except (TvError, ValueError) as exc:
                self.enviar_json(400, {"error": str(exc)}); return
        if path == "/hub/command":
            if not self.hub_autorizado():
                self.enviar_json(401, {"error": "Não autorizado"}); return
            try:
                MONITOR.command_sprints(str(self.body().get("command", "")))
            except (TvError, ValueError) as exc:
                self.enviar_json(400, {"error": str(exc)}); return
            self.enviar_json(200, {"ok": True}); return
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
            if path == "/sprints":
                self.respond(200, MONITOR.receive_sprints(data))
            elif path == "/wake":
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


HUB_FUNDO = "#07060c"
HUB_VIDRO = "#100e19"
HUB_BORDA = "#242131"
HUB_TEXTO = "#ece8f6"
HUB_SUAVE = "#827c91"
HUB_FRACO = "#5f5a6d"
HUB_LOG = "#0a0812"


def _acento_hub(segundos: float) -> str:
    """Mesmo passeio de cor do front: azul, violeta, rosa e de volta."""
    import colorsys
    import math

    matiz = 215 + 145 * (0.5 - 0.5 * math.cos(segundos * math.pi / 90))
    vermelho, verde, azul = colorsys.hls_to_rgb((matiz % 360) / 360, 0.74, 0.62)
    return f"#{int(vermelho * 255):02x}{int(verde * 255):02x}{int(azul * 255):02x}"


def _classificar_linha(linha: str) -> str:
    """Mesma leitura do console web: sucesso, bloqueio, falha ou aviso."""
    achou = re.search(r"→\s*(\d{3})\s*$", linha)
    if not achou:
        return "nota"
    status = int(achou.group(1))
    if status in (401, 403):
        return "bloqueada"
    if status >= 400:
        return "falha"
    return "ok"


NAVEGADORES = (
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
)


def _encontrar_navegador() -> str:
    for nome in ("chrome.exe", "msedge.exe", "brave.exe", "chromium.exe"):
        achado = shutil.which(nome)
        if achado:
            return achado
    bases = [os.environ.get(v, "") for v in
             ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for base in filter(None, bases):
        for sufixo in NAVEGADORES:
            caminho = Path(base) / sufixo
            if caminho.is_file():
                return str(caminho)
    return ""


def abrir_modo_estrelas(server: ThreadingHTTPServer) -> bool:
    """Console espacial em janela própria: é o único modo do hub.

    A janela Tk antiga continua no código como reserva para quando não houver
    navegador ou área de trabalho — sem ela o hub ficaria sem rosto nenhum.
    """
    endereco = f"http://127.0.0.1:{server.server_port}/hub/"
    navegador = _encontrar_navegador()
    if not navegador:
        return False
    perfil = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NebulaPower" / "console"
    try:
        perfil.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [navegador, f"--app={endereco}", f"--user-data-dir={perfil}",
             "--start-fullscreen", "--no-first-run", "--no-default-browser-check"],
            close_fds=True,
        )
    except OSError:
        return False
    MONITOR.record_event(f"Modo estrelas aberto em {endereco}.")
    return True


def run_monitor_window(server: ThreadingHTTPServer) -> None:
    """Janela nativa do hub, na mesma temática espacial do front da Nebula.

    O conteúdo é desenhado sobre um céu estrelado em ``tk.Canvas``; só o log e
    os botões são widgets reais, posicionados sobre o céu. F11 alterna a tela
    cheia e há um atalho para o console web, que tem a nebulosa em WebGL.
    """
    import random
    import tkinter as tk
    import webbrowser
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title(f"Nebula Home Hub {VERSAO_NEBULA} — Monitor")
    root.geometry("1060x820")
    root.minsize(760, 520)
    root.configure(bg=HUB_FUNDO)

    ceu = tk.Canvas(root, bg=HUB_FUNDO, highlightthickness=0, bd=0)
    ceu.pack(fill="both", expand=True)

    sorteio = random.Random(73421)
    estrelas = [
        (sorteio.random(), sorteio.random(), sorteio.choice((0.6, 0.8, 1.0, 1.4)),
         sorteio.choice(("#2c2a3a", "#3b3950", "#565270", "#7f7b99", "#b9b4cf")))
        for _ in range(230)
    ]

    def arredondado(x1: float, y1: float, x2: float, y2: float, raio: int = 16, **opcoes) -> int:
        pontos = [
            x1 + raio, y1, x2 - raio, y1, x2, y1, x2, y1 + raio,
            x2, y2 - raio, x2, y2, x2 - raio, y2, x1 + raio, y2,
            x1, y2, x1, y2 - raio, x1, y1 + raio, x1, y1,
        ]
        return ceu.create_polygon(pontos, smooth=True, **opcoes)

    metricas = ("total", "active_clients", "denied", "uptime")
    rotulos = {"total": "REQUISIÇÕES", "active_clients": "CLIENTES 5 MIN",
               "denied": "BLOQUEADAS", "uptime": "TEMPO ATIVO"}
    itens: dict[str, int] = {}

    log = ScrolledText(
        ceu, bg=HUB_LOG, fg="#9f99ae", insertbackground="#9f99ae",
        selectbackground="#2c2545", relief="flat", borderwidth=0,
        font=("Cascadia Mono", 10), padx=16, pady=14, wrap="none",
    )
    log.tag_configure("ok", foreground="#a9a2bb")
    log.tag_configure("bloqueada", foreground="#e0b3b3")
    log.tag_configure("falha", foreground="#ffb9a3")
    log.tag_configure("nota", foreground="#cdc3e2")

    def escrever(linhas: list[str]) -> None:
        log.configure(state="normal")
        for linha in linhas:
            log.insert("end", linha + "\n", _classificar_linha(linha))
        log.see("end")
        log.configure(state="disabled")

    with MONITOR.lock:
        iniciais = list(MONITOR.recent)
    escrever(iniciais)

    def limpar() -> None:
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")

    def abrir_console() -> None:
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/hub/")

    def alternar_tela_cheia(_evento: object = None) -> str:
        cheia = not bool(root.attributes("-fullscreen"))
        root.attributes("-fullscreen", cheia)
        botao_tela.configure(text="Sair da tela cheia (F11)" if cheia else "Tela cheia (F11)")
        return "break"

    def sair_tela_cheia(_evento: object = None) -> None:
        if root.attributes("-fullscreen"):
            alternar_tela_cheia()

    def botao(texto: str, comando) -> tk.Button:
        return tk.Button(
            ceu, text=texto, command=comando, bg=HUB_VIDRO, fg="#bcb7ca",
            activebackground="#1b1828", activeforeground=HUB_TEXTO,
            relief="flat", borderwidth=0, padx=15, pady=8,
            font=("Segoe UI", 9), cursor="hand2",
        )

    botao_pausar = botao("Pausar após a tarefa atual", lambda: MONITOR.command_sprints("pause"))
    botao_retomar = botao("Retomar sprints", lambda: MONITOR.command_sprints("resume"))
    botao_limpar = botao("Limpar visualização", limpar)
    botao_console = botao("Abrir console no navegador", abrir_console)
    botao_tela = botao("Tela cheia (F11)", alternar_tela_cheia)
    rodape = (botao_pausar, botao_retomar, botao_limpar, botao_console, botao_tela)

    root.bind("<F11>", alternar_tela_cheia)
    root.bind("<Escape>", sair_tela_cheia)

    estado_visual = {"acento": "#9eabff", "sprints": "Aguardando resumo do PC…", "alerta": False}

    def desenhar(_evento: object = None) -> None:
        largura = max(ceu.winfo_width(), 1)
        altura = max(ceu.winfo_height(), 1)
        acento = estado_visual["acento"]
        ceu.delete("all")
        itens.clear()

        for fx, fy, raio, cor in estrelas:
            x, y = fx * largura, fy * altura
            ceu.create_oval(x - raio, y - raio, x + raio, y + raio, fill=cor, outline="")

        margem = 34
        ceu.create_text(margem, 40, anchor="w", text="✧", fill=acento, font=("Segoe UI", 21))
        ceu.create_text(margem + 30, 42, anchor="w", text="N E B U L A   H O M E   H U B",
                        fill=HUB_TEXTO, font=("Segoe UI Semibold", 15))
        ceu.create_text(largura - margem, 42, anchor="e", text="● SERVIDOR ATIVO",
                        fill=acento, font=("Segoe UI Semibold", 9))
        ceu.create_text(
            margem, 74, anchor="w",
            text=f"NOTEBOOK · PORTA {server.server_port} · VERSÃO {VERSAO_NEBULA} · LOG {MONITOR_LOG_FILE}",
            fill=HUB_FRACO, font=("Segoe UI", 8),
        )

        topo, alto = 100, 78
        vao = (largura - margem * 2 - 12 * 3) / 4
        for indice, chave in enumerate(metricas):
            x1 = margem + indice * (vao + 12)
            arredondado(x1, topo, x1 + vao, topo + alto, fill=HUB_VIDRO, outline=HUB_BORDA)
            itens[chave] = ceu.create_text(
                x1 + 18, topo + 30, anchor="w", text="—", fill=acento,
                font=("Segoe UI Light", 22),
            )
            ceu.create_text(x1 + 18, topo + 58, anchor="w", text=rotulos[chave],
                            fill=HUB_FRACO, font=("Segoe UI Semibold", 7))

        itens["conexao"] = ceu.create_text(
            margem, topo + alto + 22, anchor="w", text="Última conexão: —",
            fill=HUB_SUAVE, font=("Segoe UI", 9),
        )

        sprint_topo = topo + alto + 40
        sprint_alto = 112
        arredondado(margem, sprint_topo, largura - margem, sprint_topo + sprint_alto,
                    fill=HUB_VIDRO, outline=HUB_BORDA)
        ceu.create_text(margem + 18, sprint_topo + 20, anchor="w",
                        text="SPRINTS · AVALIAÇÕES GEMINI", fill=acento,
                        font=("Segoe UI Semibold", 8))
        itens["sprints"] = ceu.create_text(
            margem + 18, sprint_topo + 38, anchor="nw", text=estado_visual["sprints"],
            fill="#ffc891" if estado_visual["alerta"] else "#bdb5cb",
            font=("Segoe UI", 9), width=max(200, largura - margem * 2 - 36),
        )

        altura_rodape = 52
        log_topo = sprint_topo + sprint_alto + 16
        log_base = altura - altura_rodape - 16
        if log_base - log_topo > 80:
            arredondado(margem, log_topo, largura - margem, log_base,
                        fill=HUB_LOG, outline=HUB_BORDA)
            ceu.create_window(
                margem + 4, log_topo + 4, anchor="nw", window=log,
                width=largura - margem * 2 - 8, height=log_base - log_topo - 8,
            )

        x = margem
        for widget in rodape:
            ceu.create_window(x, altura - altura_rodape + 14, anchor="nw", window=widget)
            x += widget.winfo_reqwidth() + 8
        ceu.create_text(
            largura - margem, altura - 16, anchor="e",
            text="Fechar minimiza a janela; o servidor continua funcionando.",
            fill=HUB_FRACO, font=("Segoe UI", 8),
        )

    ceu.bind("<Configure>", desenhar)

    def refresh() -> None:
        novas: list[str] = []
        while True:
            try:
                novas.append(MONITOR.events.get_nowait())
            except queue.Empty:
                break
        if novas:
            escrever(novas)

        estado = MONITOR.snapshot()
        sprint = MONITOR.sprint_snapshot()
        resumo = sprint["data"]
        if resumo:
            contagens = resumo.get("counts", {})
            linhas = [
                f"{'PAUSADA' if resumo.get('paused') else 'ATIVA'} · "
                f"{resumo.get('evaluated', 0)}/{resumo.get('total', 0)} avaliadas · "
                f"{contagens.get('waiting_gemini', 0)} aguardando Gemini · "
                f"CPU até {resumo.get('threads', '?')} threads / intervalo {resumo.get('interval_seconds', '?')}s"
            ]
            idade = sprint["age_seconds"]
            if idade and idade > 60:
                linhas.append(f"SEM ATUALIZAÇÃO DO PC há {idade}s")
            if sprint["pending_command"]:
                linhas.append("Comando pendente: " + str(sprint["pending_command"]))
            linhas.extend(str(x) for x in resumo.get("alerts", [])[:2])
            for item in resumo.get("recent", [])[:2]:
                notas = " | ".join(
                    f"{nome}: {premio.get('delta', 0):+d}"
                    for nome, premio in item.get("rewards", {}).items()
                )
                linhas.append(f"{item.get('job')}: {notas}\n{str(item.get('summary', ''))[:260]}")
            estado_visual["sprints"] = "\n".join(linhas)
            estado_visual["alerta"] = bool(resumo.get("alerts")) or bool(idade and idade > 60)

        acento = _acento_hub(estado["uptime_seconds"])
        if acento != estado_visual["acento"] or not itens:
            estado_visual["acento"] = acento
            desenhar()
        valores = {
            "total": str(estado["total"]),
            "active_clients": str(estado["active_clients"]),
            "denied": str(estado["denied"]),
            "uptime": _format_uptime(int(estado["uptime_seconds"])),
        }
        for chave, valor in valores.items():
            if chave in itens:
                ceu.itemconfigure(itens[chave], text=valor)
        if "conexao" in itens:
            ceu.itemconfigure(itens["conexao"], text=(
                f"Última conexão: {estado['last_client']}  ·  "
                f"sucesso: {estado['successful']}  ·  erros: {estado['failed']}"
            ))
        if "sprints" in itens:
            ceu.itemconfigure(
                itens["sprints"], text=estado_visual["sprints"],
                fill="#ffc891" if estado_visual["alerta"] else "#bdb5cb",
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
    # O modo estrelas é o único acesso do hub. A janela Tk só entra se não
    # houver navegador, e NEBULA_HUB_JANELA=1 força ela de volta.
    forcar_janela = os.environ.get("NEBULA_HUB_JANELA", "").strip() == "1"
    if not forcar_janela and abrir_modo_estrelas(http_server):
        try:
            http_server.serve_forever()
        finally:
            http_server.server_close()
    else:
        try:
            run_monitor_window(http_server)
        except Exception as exc:
            MONITOR.record_event(f"Monitor visual indisponível: {exc}. Servidor em modo silencioso.")
            http_server.serve_forever()
