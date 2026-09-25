"""Resumo de sprints para o monitor autenticado do notebook."""
import json
import os
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from ai_sprints.game_pacing import active_games, game_interval, game_threads, beamng_active
from integrations.mcp.audit import read_recent_audit_events


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def snapshot(root: Path):
    base = root / "ai_sprints"
    states = [(path.parent.name, read_json(path)) for path in
              (base / "autopilot_runs").glob("*/state.json")]
    counts = Counter(state.get("status", "unknown") for _, state in states)
    board = read_json(base / "scoreboard.json")
    records = sorted(board.get("sprints", {}).values(), key=lambda s: s["recorded_at"], reverse=True)
    recent = [{"job": item["job_id"], "status": item["status"],
               "summary": item.get("summary", "")[:600],
               "rewards": item["rewards"], "at": item["recorded_at"]} for item in records[:3]]
    alerts = []
    for item in recent:
        if any(reward["delta"] <= -5 for reward in item["rewards"].values()):
            alerts.append("Nota baixa: " + item["job"])
    pending = [state.get("updated_at") for _, state in states if state.get("status") == "waiting_gemini"]
    oldest = min((stamp for stamp in pending if stamp), default=None)
    minutes = max(0, int((datetime.now() - datetime.fromisoformat(oldest)).total_seconds() / 60)) if oldest else 0
    if pending:
        alerts.append(f"{len(pending)} aguardando Gemini; mais antigo ha {minutes} min. Ponte Web requer envio/resposta.")
    state = read_json(base / "autopilot_state.json")
    games = active_games()
    if beamng_active(games):
        alerts.insert(0, "BeamNG aberto: novas tarefas pausadas; chamada atual limitada a 2 threads.")
    return {"updated_at": datetime.now().isoformat(timespec="seconds"),
            "paused": bool(state.get("paused")), "running": bool(state.get("watcher_pid")),
            "counts": dict(counts), "total": len(states), "evaluated": len(records),
            "agents": board.get("agents", {}), "recent": recent,
            "alerts": alerts[:4], "games": games,
            "mcp_events": read_recent_audit_events(limit=8),
            "interval_seconds": game_interval(30, games),
            "threads": game_threads(games) if games else (__import__('psutil').cpu_count(logical=False) or 2)}


def _config(nome: str) -> str:
    """Do ambiente ou, no Windows, das variaveis do usuario no registro.

    O watcher e reiniciado por shells que nasceram antes da variavel existir;
    sem o registro, ele deixava de reportar e o hub mostrava "sem atualizacao
    do PC" enquanto as sprints seguiam normalmente.
    """
    valor = os.getenv(nome, "").strip()
    if valor or os.name != "nt":
        return valor
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as chave:
            return str(winreg.QueryValueEx(chave, nome)[0]).strip()
    except OSError:
        return ""


class HubReporter:
    def __init__(self, root, set_paused):
        self.root, self.set_paused = root, set_paused
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        url = _config("NEBULA_SPRINT_HUB_URL").rstrip("/")
        token = _config("NEBULA_POWER_TOKEN")
        if not url or not token:
            return self
        def run():
            while not self.stop.is_set():
                try:
                    response = requests.post(url + "/sprints", json=snapshot(self.root),
                                             headers={"X-Nebula-Power-Token": token}, timeout=4)
                    response.raise_for_status()
                    command = response.json().get("command")
                    if command in {"pause", "resume"}:
                        self.set_paused(command == "pause")
                except (requests.RequestException, ValueError, OSError):
                    pass
                self.stop.wait(15)
        self.thread = threading.Thread(target=run, name="sprint-hub-reporter", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
