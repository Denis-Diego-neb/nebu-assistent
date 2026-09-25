"""Reabrir sprints julgadas sem a regra do exercicio, sem somar nota duas vezes.

O revisor 9B foi julgado pelo Gemini por criterios que nunca recebeu. Refazer
essas revisoes exige que o placar troque a nota antiga pela nova -- antes ele
recusava ("avaliacao diferente") e a sprint ficava presa em waiting_gemini.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_sprints import autopilot
from ai_sprints.scoreboard import SprintScoreboard
from tests.test_scoreboard import review


class SubstituicaoNoPlacarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.board = SprintScoreboard(Path(self.pasta.name))
        self.board.record(worker_source="qwen_4b", reviewer_source="qwen_9b", job_id="mcp", fingerprint="a", status="rejected", review=review(10, -10))
        self.board.record(worker_source="qwen_4b", reviewer_source="qwen_9b", job_id="outra", fingerprint="z", status="rejected", review=review(3, 2))

    def pontos(self):
        return {item["agent"]: (item["score"], item["reviews"]) for item in self.board.ranking()}

    def test_sem_permissao_continua_recusando(self) -> None:
        with self.assertRaisesRegex(ValueError, "diferente"):
            self.board.record(worker_source="qwen_4b", reviewer_source="qwen_9b", job_id="mcp", fingerprint="a", status="ready_for_human_review", review=review(10, 8))

    def test_nota_nova_substitui_a_antiga_sem_somar_duas_vezes(self) -> None:
        self.assertTrue(self.board.record(worker_source="qwen_4b", reviewer_source="qwen_9b", job_id="mcp", fingerprint="a", status="ready_for_human_review",
                                          review=review(10, 8), replace=True))
        self.assertEqual(self.pontos(), {"worker_4b": (13, 2), "reviewer_9b": (10, 2)})

    def test_a_nota_antiga_fica_no_historico(self) -> None:
        self.board.record(worker_source="qwen_4b", reviewer_source="qwen_9b", job_id="mcp", fingerprint="a", status="ready_for_human_review",
                          review=review(10, 8), replace=True)
        placar = json.loads(self.board.path.read_text(encoding="utf-8"))
        registro = placar["sprints"]["mcp:a"]
        self.assertEqual(registro["superseded"][0]["rewards"]["reviewer_9b"]["delta"], -10)
        self.assertEqual(registro["superseded"][0]["status"], "rejected")

    def test_fonte_mudada_substitui_pelo_mesmo_job(self) -> None:
        self.board.record(worker_source="qwen_4b", reviewer_source="qwen_9b", job_id="mcp", fingerprint="b", status="ready_for_human_review",
                          review=review(10, 8), replace=True)
        placar = json.loads(self.board.path.read_text(encoding="utf-8"))
        self.assertNotIn("mcp:a", placar["sprints"])
        self.assertEqual(self.pontos(), {"worker_4b": (13, 2), "reviewer_9b": (10, 2)})

    def test_repeticao_identica_continua_inofensiva(self) -> None:
        self.assertFalse(self.board.record(worker_source="qwen_4b", reviewer_source="qwen_9b", job_id="mcp", fingerprint="a", status="rejected",
                                           review=review(10, -10), replace=True))
        self.assertEqual(self.pontos(), {"worker_4b": (13, 2), "reviewer_9b": (-8, 2)})


class ReaberturaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        raiz = Path(self.pasta.name)
        self.runs = raiz / "ai_sprints" / "autopilot_runs"
        self.run = self.runs / "mcp_x"
        self.run.mkdir(parents=True)
        (self.run / "candidate.patch").write_text("diff", encoding="utf-8")
        for nome in ("pre_review.json", "final_review.json", "gemini_review.json"):
            (self.run / nome).write_text("{}", encoding="utf-8")
        (self.run / "state.json").write_text(json.dumps(
            {"status": "rejected", "fingerprint": "f1", "stage": "gemini_review"}), encoding="utf-8")
        self.resultado = raiz / "ai_sprints" / "gemini_results" / "mcp_x.json"
        self.resultado.parent.mkdir(parents=True)
        self.resultado.write_text("{}", encoding="utf-8")
        for alvo, valor in (("PROJECT_ROOT", raiz), ("RUNS_DIR", self.runs)):
            p = mock.patch.object(autopilot, alvo, valor)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(autopilot, "_global_state", return_value={})
        p.start()
        self.addCleanup(p.stop)

    def test_reabre_para_revisao_nova_com_o_patch_salvo(self) -> None:
        self.assertEqual(autopilot.reopen_for_review(["mcp_x"], "teste"), ["mcp_x"])
        estado = json.loads((self.run / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(estado, {**estado, "status": "reopened", "resume_stage": "pre_review", "fingerprint": "f1"})
        self.assertTrue((self.run / "candidate.patch").exists())
        for nome in ("pre_review.json", "final_review.json", "gemini_review.json"):
            self.assertFalse((self.run / nome).exists(), nome)
        self.assertTrue((self.run / autopilot.REOPEN_MARKER).exists())

    def test_nada_se_perde_no_arquivo(self) -> None:
        autopilot.reopen_for_review(["mcp_x"], "teste")
        arquivo = self.run / autopilot.REOPEN_ARCHIVE
        self.assertTrue((arquivo / "final_review.json").exists())
        self.assertTrue((arquivo / "gemini_result_mcp_x.json").exists())
        self.assertFalse(self.resultado.exists(), "resposta antiga do Gemini nao pode ser reaproveitada")

    def test_reaberta_nao_cai_no_caminho_de_recuperacao_sem_revisor(self) -> None:
        """status 'requeued' desliga o 9B e reusa a revisao velha; 'reopened' nao."""
        autopilot.reopen_for_review(["mcp_x"], "teste")
        estado = json.loads((self.run / "state.json").read_text(encoding="utf-8"))
        self.assertNotEqual(estado["status"], "requeued")

    def test_recusa_com_o_watcher_rodando(self) -> None:
        with mock.patch.object(autopilot, "_global_state", return_value={"watcher_pid": 1}), \
                mock.patch.object(autopilot, "_pid_alive", return_value=True):
            with self.assertRaises(RuntimeError):
                autopilot.reopen_for_review(["mcp_x"], "teste")

    def test_so_reabre_sprint_ja_decidida(self) -> None:
        (self.run / "state.json").write_text(json.dumps({"status": "waiting_gemini", "fingerprint": "f1"}),
                                             encoding="utf-8")
        self.assertEqual(autopilot.reopen_for_review(["mcp_x"], "teste"), [])


class ReavaliacaoDePontaAPontaTests(unittest.TestCase):
    """Nota injusta -> reabre -> 9B revisa com a regra -> Gemini -> placar trocado."""

    def test_reavaliacao_troca_a_nota_e_o_9b_ve_a_regra(self) -> None:
        import subprocess
        from contextlib import ExitStack
        from types import SimpleNamespace

        from integrations.gemini import GeminiBrowserReviewGate
        from tests.test_sprint_recovery import PATCH, REVIEW

        aprovado = dict(verdict="approved", risk_level="low", blocking_findings=[],
                        evidence=[dict(path="example.py", line=1, reason="Constante.")],
                        required_tests=[], summary="Dentro do escopo.")
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            worktree = root / "worktree"
            worktree.mkdir()
            for args in (["init"], ["-c", "user.name=T", "-c", "user.email=t@e.invalid",
                                    "commit", "--allow-empty", "-m", "base"]):
                subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True)
            runs = root / "ai_sprints" / "autopilot_runs"
            run = runs / "test_job"
            run.mkdir(parents=True)
            # Patch do proprio 4B ja salvo; as duas revisoes do 9B rodam de verdade.
            (run / "candidate.patch").write_text(PATCH, encoding="utf-8")
            autopilot._save_state(run, "pre_review", "fingerprint", resume_stage="pre_review",
                                  worker_source="qwen_4b")
            job = autopilot.Job("test_job", root / "candidate.json", frozenset({"example.py"}), (), 30)
            candidate = SimpleNamespace(objective="Crie constante", evidence=(),
                                        acceptance=("Somente example.py pode ser alterado.",))
            for nome, valor in [("PROJECT_ROOT", root), ("RUNS_DIR", runs),
                                ("GLOBAL_STATE", root / "global.json")]:
                stack.enter_context(mock.patch.object(autopilot, nome, valor))
            for nome, valor in [("load_job", job), ("load_candidate", candidate),
                                ("build_evidence", "### core/registry.py"),
                                ("_source_fingerprint", "fingerprint"),
                                ("_create_worktree", worktree), ("_assert_sources_clean", None),
                                ("_remove_worktree", None), ("run_tests", "exit=0 OK"),
                                ("_gemini_required", True)]:
                stack.enter_context(mock.patch.object(autopilot, nome, return_value=valor))
            clientes = stack.enter_context(mock.patch.object(autopilot, "SprintOllamaClient"))
            gate = GeminiBrowserReviewGate(root)

            def nota(worker, revisor, base):
                return {**base, "rewards": {"worker_4b": {"delta": worker, "reason": "w"},
                                            "reviewer_9b": {"delta": revisor, "reason": "r"}}}

            # 1a rodada: o 9B pede revisao e o Gemini o pune.
            clientes.return_value.chat.return_value = json.dumps(REVIEW)
            autopilot.process(root / "job.json")
            gate.record("test_job", nota(10, -10, {**aprovado}))
            autopilot.process(root / "job.json")
            antes = SprintScoreboard(root)._load()["agents"]
            self.assertEqual((antes["worker_4b"]["score"], antes["reviewer_9b"]["score"]), (10, -10))
            clientes.return_value.chat.reset_mock()

            # Reabre e o 9B revisa de novo, agora vendo a regra do exercicio.
            clientes.return_value.chat.return_value = json.dumps(aprovado)
            self.assertEqual(autopilot.reopen_for_review(["test_job"], "regra ausente"), ["test_job"])
            autopilot.process(root / "job.json")
            prompts = [c.args[0] for c in clientes.return_value.chat.call_args_list]
            self.assertTrue(prompts, "o 9B precisa revisar de novo")
            self.assertTrue(all("- example.py" in texto and "Somente example.py" in texto for texto in prompts))
            self.assertEqual(autopilot._read_json(run / "state.json")["status"], "waiting_gemini")

            gate.record("test_job", nota(10, 8, aprovado))
            autopilot.process(root / "job.json")
            placar = SprintScoreboard(root)._load()
            # Nota nova no lugar da antiga: nada somado duas vezes.
            self.assertEqual(placar["agents"]["reviewer_9b"], {**placar["agents"]["reviewer_9b"],
                                                               "score": 8, "reviews": 1})
            self.assertEqual(placar["agents"]["worker_4b"], {**placar["agents"]["worker_4b"],
                                                             "score": 10, "reviews": 1})
            registro = next(iter(placar["sprints"].values()))
            self.assertEqual(registro["superseded"][0]["rewards"]["reviewer_9b"]["delta"], -10)
            self.assertEqual(registro["sources"], {"worker_4b": "qwen_4b", "reviewer_9b": "qwen_9b"})
            self.assertFalse((run / autopilot.REOPEN_MARKER).exists(), "marcador consumido")
            self.assertTrue((run / "reavaliacao_concluida.json").exists())


if __name__ == "__main__":
    unittest.main()
