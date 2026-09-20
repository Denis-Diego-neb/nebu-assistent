import unittest

from ai_sprints.autopilot import _extract_patch, validate_patch
from ai_sprints.orchestrator import compact_evidence, valid_review


PATCH = """diff --git a/modules/example.py b/modules/example.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/modules/example.py
@@ -0,0 +1 @@
+VALUE = 1
"""


class AutopilotSafetyTests(unittest.TestCase):
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
