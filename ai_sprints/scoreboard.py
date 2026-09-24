"""Placar local, auditavel e idempotente das avaliacoes finais do Gemini."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_sprints.review_contract import gemini_rewards, parse_gemini_review


AGENTS = ("worker_4b", "reviewer_9b")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".scoreboard-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _score_lock(root: Path):
    directory = root / "ai_sprints"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".scoreboard.lock").open("a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class SprintScoreboard:
    """Registra uma unica avaliacao Gemini para cada job e fingerprint."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "ai_sprints" / "scoreboard.json"

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": None,
            "agents": {agent: {"score": 0, "reviews": 0, "last_sprint": None} for agent in AGENTS},
            "sprints": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or set(value.get("agents", {})) != set(AGENTS):
            raise ValueError("Placar local possui formato invalido.")
        if not isinstance(value.get("sprints"), dict):
            raise ValueError("Historico de sprints do placar e invalido.")
        return value

    @staticmethod
    def _review_digest(review: dict[str, Any]) -> str:
        canonical = json.dumps(review, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record(self, *, job_id: str, fingerprint: str, status: str, review: dict[str, Any]) -> bool:
        """Salva rewards validados. Retorna False quando e uma repeticao segura."""
        if not job_id or not fingerprint:
            raise ValueError("job_id e fingerprint sao obrigatorios para o placar.")
        parse_gemini_review(review)
        rewards = gemini_rewards(review)
        digest = self._review_digest(review)
        now = datetime.now().isoformat(timespec="seconds")
        with _score_lock(self.root):
            board = self._load()
            record_id = f"{job_id}:{fingerprint}"
            existing = board["sprints"].get(record_id)
            if existing:
                if existing.get("review_sha256") == digest:
                    return False
                raise ValueError("Sprint ja possui uma avaliacao diferente no placar.")
            board["sprints"][record_id] = {
                "job_id": job_id, "fingerprint": fingerprint, "status": status, "recorded_at": now,
                "review_sha256": digest, "rewards": rewards,
                "verdict": review["verdict"], "summary": review["summary"],
                "blocking_findings": review["blocking_findings"],
                "required_tests": review["required_tests"],
            }
            for agent in AGENTS:
                entry = board["agents"][agent]
                entry["score"] += rewards[agent]["delta"]
                entry["reviews"] += 1
                entry["last_sprint"] = job_id
            board["updated_at"] = now
            _atomic_json(self.path, board)
        return True

    def ranking(self) -> list[dict[str, Any]]:
        with _score_lock(self.root):
            board = self._load()
        return [{"agent": agent, **board["agents"][agent]} for agent in sorted(AGENTS, key=lambda name: (-board["agents"][name]["score"], name))]


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta o placar das sprints Nebula.")
    parser.add_argument("--status", action="store_true", help="Exibe ranking e quantidade de avaliacoes.")
    args = parser.parse_args()
    board = SprintScoreboard(PROJECT_ROOT)
    if args.status:
        print(json.dumps(board.ranking(), ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
