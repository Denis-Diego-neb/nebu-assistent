"""Verifica manualmente os dois agentes Ollama usados nas sprints."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agents import OllamaClient


def main() -> None:
    agents = (
        ("worker PC", OllamaClient("http://127.0.0.1:11434", "qwen3.5:4b")),
        ("reviewer notebook", OllamaClient("http://192.168.15.4:11434", "qwen3.5:9b")),
    )
    for name, agent in agents:
        print(f"{name}: {'online' if agent.is_alive() else 'offline'}")


if __name__ == "__main__":
    main()
