import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_sprints.autopilot import (
    _approved,
    _agent_circuit_open,
    _codex_fallback_response,
    _extract_patch,
    _open_agent_circuit,
    _parse_supervisor_guidance,
    _remove_orphan_worktree_directory,
    _reviewer_thinking_enabled,
    validate_patch,
)
from ai_sprints.orchestrator import compact_evidence, valid_review
from ai_sprints.review_contract import parse_review, review_safe_to_test
from integrations.gemini import GeminiBrowserReviewGate


PATCH = """diff --git a/modules/example.py b/modules/example.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/modules/example.py
@@ -0,0 +1 @@
+VALUE = 1
"""


class AutopilotSafetyTests(unittest.TestCase):
    def test_circuit_breaker_persiste_falha_do_agente(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state.json"
            with patch("ai_sprints.autopilot.GLOBAL_STATE", state):
                _open_agent_circuit("worker_4b", "gpu travou")
                self.assertTrue(_agent_circuit_open("worker_4b"))
                saved = json.loads(state.read_text(encoding="utf-8"))
                self.assertIn("gpu travou", saved["agent_circuits"]["worker_4b"]["error"])

    def test_fallback_codex_reutiliza_resposta_da_mesma_etapa(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            artifact = run_dir / "codex_worker_abcdef123456.json"
            artifact.write_text('{"patch":"valor"}\n', encoding="utf-8")
            with patch("ai_sprints.autopilot.ensure_local_app_server") as ensure:
                response = _codex_fallback_response(
                    run_dir=run_dir,
                    fingerprint="abcdef1234567890",
                    stage="worker",
                    prompt="prompt",
                    output_schema={"type": "object"},
                    developer_instructions="somente json",
                )
            self.assertEqual(response, '{"patch":"valor"}')
            ensure.assert_not_called()

    def test_extrai_e_limita_patch_a_lista_permitida(self) -> None:
        extracted = _extract_patch("PATCH_START\n" + PATCH + "PATCH_END")
        self.assertEqual(
            validate_patch(extracted, frozenset({"modules/example.py"})),
            {"modules/example.py"},
        )
        with self.assertRaisesRegex(ValueError, "fora do escopo"):
            validate_patch(extracted, frozenset({"main.py"}))

    def test_bloqueia_operacao_perigosa_adicionada(self) -> None:
        unsafe = PATCH.replace("VALUE = 1", "os.system('comando')")
        with self.assertRaisesRegex(ValueError, "bloqueada"):
            validate_patch(unsafe, frozenset({"modules/example.py"}))

    def test_bloqueia_arquivo_repetido_no_diff(self) -> None:
        repeated = PATCH + PATCH
        with self.assertRaisesRegex(ValueError, "repetiu o arquivo"):
            validate_patch(repeated, frozenset({"modules/example.py"}))

    def test_bloqueia_hunk_sem_intervalos_numericos(self) -> None:
        invalid = PATCH.replace("@@ -0,0 +1 @@", "@@")
        with self.assertRaisesRegex(ValueError, "hunk"):
            validate_patch(invalid, frozenset({"modules/example.py"}))

    def test_extrai_patch_de_resposta_estruturada(self) -> None:
        self.assertEqual(_extract_patch(json.dumps({"patch": PATCH})), PATCH)
        fenced = json.dumps({"patch": f"```diff\n{PATCH}```"})
        self.assertEqual(_extract_patch(fenced), PATCH)

    def test_aprovacao_estrita_exige_baixo_risco_e_evidencia(self) -> None:
        review = {
            "verdict": "approved",
            "risk_level": "low",
            "blocking_findings": [],
            "evidence": [{"path": "modules/example.py", "line": 1, "reason": "Mudanca isolada."}],
            "required_tests": [],
            "summary": "Patch pequeno e coberto.",
        }
        self.assertTrue(_approved(review))
        review["required_tests"] = ["Executar teste da tool."]
        self.assertFalse(_approved(review))
        self.assertTrue(review_safe_to_test(review))
        review["required_tests"] = []
        review["risk_level"] = "medium"
        self.assertFalse(_approved(review))
        with self.assertRaisesRegex(ValueError, "Campos"):
            parse_review({"verdict": "approved"})

    def test_gate_gemini_vincula_resposta_ao_fingerprint(self) -> None:
        review = {
            "verdict": "approved",
            "risk_level": "low",
            "blocking_findings": [],
            "evidence": [{"path": "modules/example.py", "line": 1, "reason": "Validado."}],
            "required_tests": [],
            "summary": "Aprovado.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            gate = GeminiBrowserReviewGate(Path(temporary))
            request_path = gate.prepare(
                job_id="sprint_test",
                fingerprint="abc123",
                objective="Extrair funcao.",
                patch=PATCH,
                tests="1 passed",
                qwen_review=review,
            )
            self.assertTrue(request_path.exists())
            gemini_review = dict(review, rewards={
                name: {"delta": 4, "reason": "Validado."}
                for name in ("worker_4b", "reviewer_9b")
            })
            gate.record("sprint_test", json.dumps(gemini_review))
            self.assertTrue(gate.approved(gate.load_result("sprint_test", "abc123")))
            with self.assertRaisesRegex(ValueError, "outra versao"):
                gate.load_result("sprint_test", "fingerprint-novo")

    def test_gate_gemini_bloqueia_segredo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            gate = GeminiBrowserReviewGate(Path(temporary))
            with self.assertRaisesRegex(ValueError, "sensivel"):
                gate.prepare(
                    job_id="sprint_test",
                    fingerprint="abc123",
                    objective="Refactor.",
                    patch="+API_KEY='segredo-super-secreto'",
                    tests="ok",
                    qwen_review={},
                )

    def test_gate_gemini_recusa_job_com_travessia(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            gate = GeminiBrowserReviewGate(Path(temporary))
            with self.assertRaisesRegex(ValueError, "ID de job"):
                gate.request_path("../fora")

    def test_thinking_local_fica_desligado_por_padrao(self) -> None:
        with patch("ai_sprints.autopilot.os.getenv", return_value="0"):
            self.assertFalse(_reviewer_thinking_enabled())

    def test_limpeza_de_worktree_recusa_caminho_externo(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "fora da raiz"):
            _remove_orphan_worktree_directory(Path(__file__).resolve().parent)

    def test_valida_orientacao_do_codex(self) -> None:
        response = json.dumps({
            "action": "retry_worker",
            "guidance": "Retorne apenas o objeto com patch.",
            "reason": "A resposta anterior continha Markdown.",
        })
        self.assertEqual(_parse_supervisor_guidance(response)["action"], "retry_worker")
        with self.assertRaisesRegex(ValueError, "invalida"):
            _parse_supervisor_guidance('{"action":"approve"}')

    def test_review_curta_ou_sem_secoes_nao_libera(self) -> None:
        self.assertFalse(valid_review("VEREDITO: APROVADO"))
        review = (
            "VEREDITO: APROVADO\n\nRISCOS\n" + "baixo " * 80
            + "\n\nPLANO\nEscopo preservado.\n\nTESTES\nTodos passaram."
        )
        self.assertTrue(valid_review(review))

    def test_compacta_cada_simbolo_sem_apagar_cabecalho(self) -> None:
        evidence = "### a.py::f\n" + "x" * 4000 + "\n\n### b.py::g\n" + "y" * 4000
        compacted = compact_evidence(evidence, per_section=500)
        self.assertIn("### a.py::f", compacted)
        self.assertIn("### b.py::g", compacted)
        self.assertIn("trecho omitido", compacted)


if __name__ == "__main__":
    unittest.main()
