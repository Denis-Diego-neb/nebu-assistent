"""Cada Qwen so e avaliado e pontuado pelo proprio trabalho, desta versao.

A auditoria de 25/09 achou: os +301 do worker_4b eram todos de patches do
Codex; o patch do 4B morria na contagem do hunk e era trocado pelo do Codex;
20 de 32 notas julgaram candidate.patch e pre_review.json de outra versao,
mandados ao Gemini pelo caminho de excecao.
"""

import json
import tempfile
import unittest
from pathlib import Path

from ai_sprints import autopilot
from ai_sprints.autopilot import normalize_hunk_counts, validate_patch
from ai_sprints.scoreboard import SprintScoreboard
from tests.test_scoreboard import review

NOVO = frozenset({"modules/novo.py"})


def arquivo_novo(corpo: str, contagem: int) -> str:
    return ("diff --git a/modules/novo.py b/modules/novo.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/modules/novo.py\n"
            f"@@ -0,0 +1,{contagem} @@\n" + corpo)


class NormalizacaoDoHunkTests(unittest.TestCase):
    def test_contagem_errada_do_4b_e_corrigida_pelo_corpo(self) -> None:
        patch = arquivo_novo("+A = 1\n+B = 2\n+C = 3\n", 2)
        with self.assertRaisesRegex(ValueError, "Contagem"):
            validate_patch(patch, NOVO)
        novo, mudou = normalize_hunk_counts(patch)
        self.assertTrue(mudou)
        self.assertIn("@@ -0,0 +1,3 @@", novo)
        validate_patch(novo, NOVO)

    def test_linha_sem_mais_em_arquivo_novo_ganha_o_mais(self) -> None:
        """Caso real da sprint 19: 'class MockNetwork:' veio sem o '+'."""
        patch = arquivo_novo("+A = 1\n\nclass Rede:\n+    pass\n", 4)
        novo, mudou = normalize_hunk_counts(patch)
        self.assertTrue(mudou)
        self.assertIn("\n+\n+class Rede:\n+    pass\n", novo)
        validate_patch(novo, NOVO)

    def test_patch_correto_sai_identico(self) -> None:
        patch = arquivo_novo("+A = 1\n+B = 2\n", 2)
        self.assertEqual(normalize_hunk_counts(patch), (patch, False))

    def test_linha_vazia_em_alteracao_e_contexto(self) -> None:
        patch = ("diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
                 "@@ -1,2 +1,3 @@\n x = 1\n\n+y = 2\n")
        novo, mudou = normalize_hunk_counts(patch)
        self.assertTrue(mudou)
        self.assertIn("@@ -1,2 +1,3 @@\n x = 1\n \n+y = 2\n", novo)
        validate_patch(novo, frozenset({"m.py"}))

    def test_dois_arquivos_cada_hunk_com_sua_conta(self) -> None:
        patch = (arquivo_novo("+A = 1\n+B = 2\n", 5)
                 + "diff --git a/tests/t.py b/tests/t.py\nnew file mode 100644\n"
                   "--- /dev/null\n+++ b/tests/t.py\n@@ -0,0 +1,1 @@\n+import unittest\n+X = 1\n")
        novo, _ = normalize_hunk_counts(patch)
        self.assertIn("@@ -0,0 +1,2 @@\n+A = 1", novo)
        self.assertIn("@@ -0,0 +1,2 @@\n+import unittest", novo)
        validate_patch(novo, frozenset({"modules/novo.py", "tests/t.py"}))

    def test_validacao_continua_estrita_para_escopo(self) -> None:
        patch = arquivo_novo("+A = 1\n", 9)
        novo, _ = normalize_hunk_counts(patch)
        with self.assertRaisesRegex(ValueError, "fora do escopo"):
            validate_patch(novo, frozenset({"outro.py"}))


class ArtefatosDeOutraVersaoTests(unittest.TestCase):
    def test_mudanca_de_fonte_arquiva_patch_e_revisoes_antigas(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            run = Path(pasta)
            for nome in ("candidate.patch", "pre_review.json", "final_review.json", "tests.txt"):
                (run / nome).write_text("velho", encoding="utf-8")
            (run / "codex_worker_abc.json").write_text("{}", encoding="utf-8")
            autopilot._archive_stale_artifacts(run, "b777cbde14ed00")
            for nome in ("candidate.patch", "pre_review.json", "final_review.json", "tests.txt"):
                self.assertFalse((run / nome).exists(), nome)
                self.assertTrue((run / "versao_b777cbde14ed" / nome).exists(), nome)
            self.assertTrue((run / "codex_worker_abc.json").exists(), "historico por hash fica")


class CaminhoDeExcecaoTests(unittest.TestCase):
    """Patch invalido nesta rodada nao leva o candidate.patch velho ao Gemini."""

    def test_patch_invalido_nao_manda_nada_velho_ao_gemini(self) -> None:
        import subprocess
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest import mock

        from integrations.gemini import GeminiBrowserReviewGate

        fora = ("diff --git a/core/x.py b/core/x.py\nnew file mode 100644\n--- /dev/null\n"
                "+++ b/core/x.py\n@@ -0,0 +1,1 @@\n+X = 1\n")
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            worktree = root / "worktree"
            worktree.mkdir()
            for args in (["init"], ["-c", "user.name=T", "-c", "user.email=t@e.invalid",
                                    "commit", "--allow-empty", "-m", "base"]):
                subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True)
            runs = root / "ai_sprints" / "autopilot_runs"
            run = runs / "job"
            run.mkdir(parents=True)
            (run / "candidate.patch").write_text(arquivo_novo("+VELHO = 1\n", 1), encoding="utf-8")
            (run / "pre_review.json").write_text('{"summary": "de 21/09"}', encoding="utf-8")
            autopilot._save_state(run, "waiting_agents", "fp")
            job = autopilot.Job("job", root / "c.json", NOVO, (), 30)
            candidate = SimpleNamespace(objective="o", evidence=(), acceptance=("a",))
            for nome, valor in [("PROJECT_ROOT", root), ("RUNS_DIR", runs),
                                ("GLOBAL_STATE", root / "global.json")]:
                stack.enter_context(mock.patch.object(autopilot, nome, valor))
            for nome, valor in [("load_job", job), ("load_candidate", candidate),
                                ("build_evidence", ""), ("_source_fingerprint", "fp"),
                                ("_create_worktree", worktree), ("_assert_sources_clean", None),
                                ("_remove_worktree", None), ("run_tests", "exit=0 OK"),
                                ("_gemini_required", True), ("_codex_worker_patch", fora)]:
                stack.enter_context(mock.patch.object(autopilot, nome, return_value=valor))
            clientes = stack.enter_context(mock.patch.object(autopilot, "SprintOllamaClient"))
            clientes.return_value.chat.return_value = json.dumps({"patch": fora})
            with self.assertRaisesRegex(ValueError, "fora do escopo"):
                autopilot.process(root / "job.json")
            self.assertFalse(GeminiBrowserReviewGate(root).request_path("job").exists())
            self.assertEqual(autopilot._read_json(run / "state.json")["status"], "failed")


class OrigemNoPlacarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.board = SprintScoreboard(Path(self.pasta.name))

    def pontos(self):
        return {item["agent"]: (item["score"], item["reviews"]) for item in self.board.ranking()}

    def test_patch_do_codex_nao_pontua_o_4b(self) -> None:
        self.board.record(job_id="a", fingerprint="1", status="rejected", review=review(10, 4),
                          worker_source="codex_terra", reviewer_source="qwen_9b")
        self.assertEqual(self.pontos(), {"reviewer_9b": (4, 1), "worker_4b": (0, 0)})

    def test_revisao_reaproveitada_ou_ausente_nao_pontua_o_9b(self) -> None:
        for fonte, job in (("qwen_9b_saved", "a"), ("none", "b"), ("unknown", "c"), (None, "d")):
            self.board.record(job_id=job, fingerprint="1", status="rejected", review=review(3, -10),
                              worker_source="qwen_4b", reviewer_source=fonte)
        self.assertEqual(self.pontos(), {"worker_4b": (12, 4), "reviewer_9b": (0, 0)})

    def test_nota_guarda_a_origem_mesmo_sem_pontuar(self) -> None:
        self.board.record(job_id="a", fingerprint="1", status="rejected", review=review(10, -10),
                          worker_source="codex_terra", reviewer_source="unknown")
        registro = json.loads(self.board.path.read_text(encoding="utf-8"))["sprints"]["a:1"]
        self.assertEqual(registro["sources"], {"worker_4b": "codex_terra", "reviewer_9b": "unknown"})
        self.assertEqual(registro["scored"], [])

    def test_feedback_so_mostra_notas_do_proprio_trabalho(self) -> None:
        self.board.record(job_id="do_codex", fingerprint="1", status="rejected", review=review(10, 1),
                          worker_source="codex_terra", reviewer_source="qwen_9b")
        self.board.record(job_id="do_4b", fingerprint="1", status="rejected", review=review(-3, 1),
                          worker_source="qwen_4b", reviewer_source="qwen_9b")
        exemplos = self.board.feedback("worker_4b")["recent"]
        self.assertEqual([e["sprint"] for e in exemplos], ["do_4b"])

    def test_substituir_desconta_so_o_que_tinha_pontuado(self) -> None:
        self.board.record(job_id="a", fingerprint="1", status="rejected", review=review(10, -10),
                          worker_source="codex_terra", reviewer_source="qwen_9b")
        self.board.record(job_id="a", fingerprint="1", status="ready_for_human_review",
                          review=review(10, 6), worker_source="codex_terra",
                          reviewer_source="qwen_9b", replace=True)
        self.assertEqual(self.pontos(), {"reviewer_9b": (6, 1), "worker_4b": (0, 0)})

    def test_nova_epoca_arquiva_e_zera(self) -> None:
        self.board.record(job_id="a", fingerprint="1", status="rejected", review=review(10, -10),
                          worker_source="qwen_4b", reviewer_source="qwen_9b")
        antigo = self.board.start_new_epoch("pontuado sem origem")
        self.assertTrue(antigo.exists())
        self.assertEqual(json.loads(antigo.read_text(encoding="utf-8"))["agents"]["reviewer_9b"]["score"], -10)
        self.assertEqual(self.pontos(), {"reviewer_9b": (0, 0), "worker_4b": (0, 0)})
        placar = json.loads(self.board.path.read_text(encoding="utf-8"))
        self.assertEqual(placar["epoch"]["previous"], antigo.name)
        self.assertEqual(placar["sprints"], {})


if __name__ == "__main__":
    unittest.main()
