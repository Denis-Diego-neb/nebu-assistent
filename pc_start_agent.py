"""Agente leve que recebe do notebook a ordem para abrir a Nebula no PC."""

from __future__ import annotations

import csv
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


POWER_TOKEN = os.environ.get(
    "NEBULA_POWER_TOKEN", "npw_A71_x99e_8f4c2a91d7604b3e"
)
NOTEBOOK_ENDPOINTS = (
    "http://100.78.67.81:8766",
    "http://192.168.15.4:8766",
    "http://192.168.15.86:8766",
)
PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula"
STATE_FILE = CONFIG_DIR / "pc_start_agent.json"
LOG_FILE = CONFIG_DIR / "pc_start_agent.log"
POLL_SECONDS = 3


def log(message: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as stream:
        stream.write(f"{stamp} {message}\n")
    try:
        if LOG_FILE.stat().st_size > 512_000:
            LOG_FILE.write_text(f"{stamp} log reiniciado.\n", encoding="utf-8")
    except OSError:
        pass


def load_last_command() -> str:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("last_command", "")) if isinstance(data, dict) else ""


def save_last_command(command_id: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"last_command": command_id}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(STATE_FILE)


def version_key(path: Path) -> tuple[int, int, int]:
    match = re.fullmatch(r"Nebula-(\d+)\.(\d+)\.(\d+)\.exe", path.name)
    return tuple(map(int, match.groups())) if match else (-1, -1, -1)


def configured_executable() -> Path | None:
    explicit = os.environ.get("NEBULA_EXECUTABLE", "").strip().strip('"')
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
    candidates = [
        path for path in PROJECT_DIR.glob("Nebula-*.exe")
        if version_key(path) != (-1, -1, -1)
    ]
    return max(candidates, key=version_key) if candidates else None


def running_nebula_names() -> set[str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["tasklist.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        timeout=10,
        check=False,
    )
    names: set[str] = set()
    for row in csv.reader(result.stdout.splitlines()):
        if row and re.fullmatch(r"Nebula-\d+\.\d+\.\d+\.exe", row[0], re.I):
            names.add(row[0].casefold())
    return names


def nebula_is_running() -> bool:
    return bool(running_nebula_names())


def show_nebula() -> bool:
    request = Request(
        "http://127.0.0.1:8765/api/show",
        data=b"{}",
        method="POST",
        headers={
            "X-Nebula-Power-Token": POWER_TOKEN,
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError):
        return False
    return isinstance(payload, dict) and bool(payload.get("ok"))


def launch_nebula() -> str:
    executable = configured_executable()
    if executable is None:
        raise RuntimeError("Nenhum executavel Nebula-x.y.z.exe foi encontrado.")
    running = running_nebula_names()
    target_name = executable.name.casefold()
    if target_name in running:
        return (
            "Janela da Nebula restaurada."
            if show_nebula()
            else "A versao atual da Nebula ja estava aberta."
        )
    for obsolete_name in sorted(running):
        subprocess.run(
            ["taskkill.exe", "/IM", obsolete_name, "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
            check=False,
        )
    subprocess.Popen(
        [str(executable)],
        cwd=str(PROJECT_DIR),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
    return f"Nebula aberta: {executable.name}."


def fetch_command() -> dict[str, object] | None:
    last_error: Exception | None = None
    for endpoint in NOTEBOOK_ENDPOINTS:
        request = Request(
            endpoint + "/pc/command",
            headers={
                "X-Nebula-Power-Token": POWER_TOKEN,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            command = payload.get("command") if isinstance(payload, dict) else None
            return command if isinstance(command, dict) else None
        except (HTTPError, URLError, OSError, ValueError) as exc:
            last_error = exc
    if last_error is not None:
        raise RuntimeError(str(last_error)) from last_error
    return None


def acquire_single_instance() -> socket.socket:
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    guard.bind(("127.0.0.1", 48767))
    guard.listen(1)
    return guard


def run() -> None:
    try:
        guard = acquire_single_instance()
    except OSError:
        return
    last_command = load_last_command()
    log("Agente iniciado.")
    try:
        log(launch_nebula())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        log(f"Falha na abertura inicial: {exc}")
    from phone_usb_panel import start_usb_panel_watcher
    start_usb_panel_watcher(POWER_TOKEN)
    offline_logged = False
    while True:
        try:
            command = fetch_command()
            offline_logged = False
            if command is not None:
                command_id = str(command.get("id", ""))
                action = str(command.get("action", ""))
                if command_id and command_id != last_command and action == "launch_nebula":
                    log(launch_nebula())
                    save_last_command(command_id)
                    last_command = command_id
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            if not offline_logged:
                log(f"Notebook indisponivel: {exc}")
                offline_logged = True
        time.sleep(POLL_SECONDS)
    guard.close()


if __name__ == "__main__":
    run()
