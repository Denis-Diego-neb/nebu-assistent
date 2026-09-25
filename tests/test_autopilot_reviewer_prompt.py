"""O revisor 9B precisa receber a mesma regra pela qual o Gemini o julga.

Em 41 sprints, 27 revisoes levaram -10 do Gemini por exigir mudancas em
core/registry.py, core/dispatcher.py ou services/tool_server.py -- arquivos
proibidos pelos criterios do exercicio. O worker e o Gemini recebiam os
criterios e a lista de arquivos permitidos; o revisor so via o objetivo e o
nucleo do projeto como "evidencia". O "revise" dele ainda rejeitou 21 patches
que o Gemini aprovou.
"""

import ast
import unittest
from pathlib import Path

from ai_sprints import autopilot
from ai_sprints.orchestrator import load_candidate

RAIZ = Path(__file__).resolve().parents[1]
CANDIDATO = RAIZ / "ai_sprints" / "candidates" / "mcp_train_14_device_discovery.json"
PERMITIDOS = frozenset({"modules/mcp_training_14.py", "tests/test_mcp_training_14.py"})


class PromptDoRevisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidato = load_candidate(CANDIDATO)
        autopilot_feedback = autopilot._score_feedback
        self.addCleanup(setattr, autopilot, "_score_feedback", autopilot_feedback)
        autopilot._score_feedback = lambda papel: "sem feedback"

    def prompt(self, etapa="antes dos testes"):
        return autopilot._review_prompt(
            etapa, self.candidato.objective, "### core/registry.py\nclass Tool: ...",
            "diff --git a/modules/mcp_training_14.py b/modules/mcp_training_14.py",
            acceptance=self.candidato.acceptance, allowed_paths=PERMITIDOS)

    def test_recebe_todos_os_criterios_de_aceite(self) -> None:
        texto = self.prompt()
        for criterio in self.candidato.acceptance:
            self.assertIn(criterio, texto)

    def test_recebe_a_lista_de_arquivos_permitidos(self) -> None:
        texto = self.prompt("apos testes")
        for caminho in PERMITIDOS:
            self.assertIn("- " + caminho, texto)
        self.assertIn("ampliar o", texto)

    def test_evidencia_e_marcada_como_somente_leitura(self) -> None:
        texto = self.prompt()
        rotulo = texto.index("somente leitura")
        self.assertLess(rotulo, texto.index("core/registry.py"))

    def test_a_regra_vem_antes_da_evidencia_e_do_patch(self) -> None:
        """Com o prompt cortado pelo fim, a regra nao pode ser o que sobra por ultimo."""
        texto = self.prompt()
        self.assertLess(texto.index("ARQUIVOS QUE O PATCH PODE"), texto.index("EVIDENCIA RESUMIDA"))
        self.assertLess(texto.index("CRITERIOS DE ACEITE"), texto.index("PATCH REAL"))

    def test_criterios_e_arquivos_sao_obrigatorios(self) -> None:
        with self.assertRaises(TypeError):
            autopilot._review_prompt("apos testes", "objetivo", "", "patch")


class ChamadasDoRevisorTests(unittest.TestCase):
    """Toda chamada, inclusive a reserva do Codex, entrega a regra do exercicio."""

    def chamadas(self, nome):
        arvore = ast.parse((RAIZ / "ai_sprints" / "autopilot.py").read_text(encoding="utf-8"))
        return [no for no in ast.walk(arvore)
                if isinstance(no, ast.Call) and getattr(no.func, "id", None) == nome]

    def test_toda_chamada_do_prompt_passa_criterios_e_arquivos(self) -> None:
        chamadas = self.chamadas("_review_prompt")
        self.assertGreaterEqual(len(chamadas), 3)
        for chamada in chamadas:
            nomes = {k.arg for k in chamada.keywords}
            self.assertTrue({"acceptance", "allowed_paths"} <= nomes, ast.unparse(chamada))

    def test_revisao_reserva_do_codex_tambem_recebe(self) -> None:
        for chamada in self.chamadas("_codex_final_review"):
            nomes = {k.arg for k in chamada.keywords}
            self.assertTrue({"acceptance", "allowed_paths"} <= nomes, ast.unparse(chamada))


if __name__ == "__main__":
    unittest.main()
