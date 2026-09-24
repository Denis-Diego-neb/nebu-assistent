"""Ritmo adaptativo das sprints; nao encerra jogos nem inferencias em andamento."""
from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlparse

import psutil

from core.agents.ollama_client import OllamaClient


GAME_NAMES = frozenset({
    "childrenofmorta.exe", "children of morta.exe",
    "beamng.drive.x64.exe", "beamng.drive.x64.vulkan.exe", "acs.exe", "acc.exe",
    "assettocorsa.exe", "rocketleague.exe", "cs2.exe", "gta5.exe", "gta5_enhanced.exe",
    "forzahorizon5.exe", "eurotrucks2.exe", "amtrucks.exe", "minecraft.windows.exe",
    "valorant-win64-shipping.exe", "fortniteclient-win64-shipping.exe",
})


def active_games():
    names = GAME_NAMES | {s.strip().casefold() for s in
                          os.getenv("NEBULA_SPRINT_GAME_EXES", "").split(",") if s.strip()}
    found = []
    for process in psutil.process_iter(["name", "exe"]):
        try:
            name = (process.info["name"] or "").casefold()
            executable = (process.info["exe"] or "").replace("\\", "/").casefold()
            steam_game = "/steamapps/common/" in executable and not any(
                word in name for word in ("launcher", "crash", "helper", "service", "setup"))
            if name in names or steam_game:
                found.append(name)
        except (psutil.Error, OSError):
            continue
    return sorted(set(found))


def game_interval(normal, games):
    if games and all("morta" in game for game in games):
        return max(normal, 60)
    return max(normal, int(os.getenv("NEBULA_SPRINT_GAME_INTERVAL", "300"))) if games else normal


def game_threads(games):
    available = psutil.cpu_count(logical=True) or 2
    limit = 2 if beamng_active(games) else 8 if games and all("morta" in game for game in games) else 4
    return min(available, limit)


def beamng_active(games):
    return any(name.startswith("beamng.drive") for name in games)


class SprintOllamaClient(OllamaClient):
    def chat(self, *args, **kwargs):
        # CPU desde o inicio: um jogo aberto no meio da chamada nao disputa GPU.
        # A afinidade dinamica do runner limita tambem chamadas ja em andamento.
        if urlparse(self.host).hostname in {"127.0.0.1", "localhost", "::1"}:
            kwargs["num_gpu"] = 0
            kwargs["num_thread"] = max(1, psutil.cpu_count(logical=False) or 2)
            if active_games():
                kwargs["num_thread"] = game_threads(active_games())
        return super().chat(*args, **kwargs)


class GamePacer:
    def __init__(self):
        self.games = []
        self.saved = {}
        self.stop = threading.Event()
        self.thread = None

    def poll(self):
        self.games = active_games()
        if not self.games:
            self.restore()
            return
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (process.info["name"] or "").casefold()
                command = process.info["cmdline"] or []
                # Apenas runners locais, nunca o jogo nem o servidor remoto.
                if name != "ollama.exe" or "runner" not in command:
                    continue
                key = (process.pid, process.create_time())
                if key not in self.saved:
                    self.saved[key] = (process.nice(), process.cpu_affinity())
                affinity = self.saved[key][1]
                process.cpu_affinity(affinity[-min(game_threads(self.games), len(affinity)):])
                process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
            except (psutil.Error, OSError):
                continue

    def restore(self):
        for (pid, created), (priority, affinity) in list(self.saved.items()):
            try:
                process = psutil.Process(pid)
                if process.create_time() == created:
                    process.cpu_affinity(affinity)
                    process.nice(priority)
                self.saved.pop((pid, created), None)
            except psutil.NoSuchProcess:
                self.saved.pop((pid, created), None)
            except (psutil.Error, OSError):
                pass

    def __enter__(self):
        def monitor():
            while not self.stop.is_set():
                self.poll()
                self.stop.wait(3)
        self.thread = threading.Thread(target=monitor, name="sprint-game-pacer", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=5)
        self.restore()

    def wait(self, normal, should_stop):
        start = time.monotonic()
        while not should_stop():
            if time.monotonic() - start >= game_interval(normal, self.games):
                return
            time.sleep(1)
