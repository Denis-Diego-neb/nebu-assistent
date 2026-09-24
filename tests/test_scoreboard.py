import tempfile
import unittest
from pathlib import Path

from ai_sprints.scoreboard import SprintScoreboard


def review(worker: int, reviewer: int) -> dict:
    return {
        "verdict": "approved", "risk_level": "low", "blocking_findings": [],
        "evidence": [{"path": "modules/example.py", "line": 1, "reason": "Coberto."}],
        "required_tests": [], "summary": "Patch avaliado.",
        "rewards": {
            "worker_4b": {"delta": worker, "reason": "Implementacao."},
            "reviewer_9b": {"delta": reviewer, "reason": "Revisao."},
        },
    }


class ScoreboardTests(unittest.TestCase):
    def test_acumula_rewards_e_ordenacao(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            board = SprintScoreboard(Path(temporary))
            self.assertTrue(board.record(job_id="sprint_um", fingerprint="a", status="ready_for_human_review", review=review(4, 2)))
            self.assertTrue(board.record(job_id="sprint_dois", fingerprint="b", status="rejected", review=review(-1, 3)))
            self.assertEqual(board.ranking(), [
                {"agent": "reviewer_9b", "score": 5, "reviews": 2, "last_sprint": "sprint_dois"},
                {"agent": "worker_4b", "score": 3, "reviews": 2, "last_sprint": "sprint_dois"},
            ])

    def test_repeticao_nao_pontua_duas_vezes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            board = SprintScoreboard(Path(temporary))
            payload = review(4, 2)
            self.assertTrue(board.record(job_id="sprint_um", fingerprint="a", status="rejected", review=payload))
            self.assertFalse(board.record(job_id="sprint_um", fingerprint="a", status="ready_for_human_review", review=payload))
            self.assertEqual(board.ranking()[0]["reviews"], 1)
            with self.assertRaisesRegex(ValueError, "diferente"):
                board.record(job_id="sprint_um", fingerprint="a", status="rejected", review=review(5, 2))
            self.assertTrue(board.record(job_id="sprint_um", fingerprint="b", status="rejected", review=review(1, 1)))
