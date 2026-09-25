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
# Cada papel so pontua pelo proprio trabalho. Antes, os +301 do worker_4b eram
# todos de patches do Codex (fallback) e o 9B era punido por revisoes de outra
# versao ou ausentes; o placar somava sem olhar a origem.
SCORED_SOURCES = {"worker_4b": frozenset({"qwen_4b"}), "reviewer_9b": frozenset({"qwen_9b"})}


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
            "version": 2,
            "updated_at": None,
            "agents": {agent: {"score": 0, "reviews": 0, "last_sprint": None} for agent in AGENTS},
            "sprints": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") not in {1, 2} or set(value.get("agents", {})) != set(AGENTS):
            raise ValueError("Placar local possui formato invalido.")
        if not isinstance(value.get("sprints"), dict):
            raise ValueError("Historico de sprints do placar e invalido.")
        return value

    @staticmethod
    def _review_digest(review: dict[str, Any]) -> str:
        canonical = json.dumps(review, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record(self, *, job_id: str, fingerprint: str, status: str, review: dict[str, Any],
               worker_source: str | None, reviewer_source: str | None,
               replace: bool = False) -> bool:
        """Salva rewards validados. Retorna False quando e uma repeticao segura.

        ``replace`` so vale para uma sprint reaberta de proposito (ex.: o revisor
        julgado sem a regra do exercicio): a avaliacao nova substitui a antiga,
        os pontos antigos saem do total de cada agente e a antiga fica em
        ``superseded``. Sem isso a mesma sprint somaria duas vezes.
        """
        if not job_id or not fingerprint:
            raise ValueError("job_id e fingerprint sao obrigatorios para o placar.")
        parse_gemini_review(review)
        rewards = gemini_rewards(review)
        digest = self._review_digest(review)
        now = datetime.now().isoformat(timespec="seconds")
        sources = {"worker_4b": worker_source or "unknown", "reviewer_9b": reviewer_source or "unknown"}
        scored = [agent for agent in AGENTS if sources[agent] in SCORED_SOURCES[agent]]
        with _score_lock(self.root):
            board = self._load()
            record_id = f"{job_id}:{fingerprint}"
            existing = board["sprints"].get(record_id)
            old_id = record_id if existing else None
            if existing and existing.get("review_sha256") == digest:
                return False
            if existing and not replace:
                raise ValueError("Sprint ja possui uma avaliacao diferente no placar.")
            if not existing and replace:
                # A fonte pode ter mudado entre a reabertura e a nota nova: a
                # anterior e a mais recente do mesmo job, com outro fingerprint.
                same_job = [key for key, item in board["sprints"].items() if item.get("job_id") == job_id]
                if same_job:
                    old_id = max(same_job, key=lambda key: board["sprints"][key].get("recorded_at", ""))
                    existing = board["sprints"][old_id]
            history = []
            if existing:
                board["sprints"].pop(old_id)
                for agent in existing.get("scored", AGENTS):
                    old = existing.get("rewards", {}).get(agent, {})
                    board["agents"][agent]["score"] -= int(old.get("delta", 0))
                    board["agents"][agent]["reviews"] -= 1
                history = list(existing.get("superseded", [])) + [{
                    key: existing.get(key) for key in
                    ("status", "recorded_at", "review_sha256", "rewards", "verdict", "summary")
                }]
            board["sprints"][record_id] = {
                "job_id": job_id, "fingerprint": fingerprint, "status": status, "recorded_at": now,
                "review_sha256": digest, "rewards": rewards,
                "verdict": review["verdict"], "summary": review["summary"],
                "blocking_findings": review["blocking_findings"],
                "required_tests": review["required_tests"],
                "sources": sources, "scored": scored,
                **({"superseded": history} if history else {}),
            }
            for agent in scored:
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

    def start_new_epoch(self, reason: str) -> Path | None:
        """Arquiva o placar atual e recomeca do zero, sem apagar nada.

        Para quando o proprio pipeline pontuou errado e as notas antigas nao
        medem os modelos (e ensinariam a coisa errada pelo feedback).
        """
        with _score_lock(self.root):
            archived = None
            if self.path.exists():
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                archived = self.path.with_name(f"scoreboard_legado_{stamp}.json")
                os.replace(self.path, archived)
            board = self._empty()
            board["epoch"] = {"reason": reason, "started_at": datetime.now().isoformat(timespec="seconds"),
                              "previous": archived.name if archived else None}
            _atomic_json(self.path, board)
        return archived

    def feedback(self, agent: str, limit: int = 3) -> dict[str, Any]:
        """Resumo curto de avaliações Gemini para orientar a próxima tentativa."""
        if agent not in AGENTS:
            raise ValueError("Agente do placar invalido.")
        with _score_lock(self.root):
            board = self._load()
        recent = sorted(board["sprints"].values(),
                        key=lambda item: item.get("recorded_at", ""), reverse=True)
        examples = []
        for entry in recent:
            if agent not in entry.get("scored", AGENTS):
                continue
            reward = entry.get("rewards", {}).get(agent, {})
            if not isinstance(reward.get("delta"), int):
                continue
            examples.append({
                "sprint": str(entry.get("job_id", ""))[:64],
                "delta": reward["delta"],
                "reason": str(reward.get("reason", ""))[:350],
            })
            if len(examples) >= max(0, min(limit, 5)):
                break
        return {"score": board["agents"][agent]["score"],
                "reviews": board["agents"][agent]["reviews"], "recent": examples}


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
