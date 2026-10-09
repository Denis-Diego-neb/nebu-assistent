import re
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
NOTEBOOK = RAIZ / "notebook_power_server"


class ProtecaoOllamaTests(unittest.TestCase):
    def test_ollama_so_escuta_a_rede_com_a_regra_do_firewall(self):
        protecao = (NOTEBOOK / "proteger_ollama.ps1").read_text(encoding="utf-8")
        regra = re.search(r'\$regraBloqueio = "([^"]+)"', protecao).group(1)
        inicio = (NOTEBOOK / "iniciar_servicos_notebook.ps1").read_text(encoding="utf-8")
        self.assertIn(f'"{regra}"', inicio)
        for script in NOTEBOOK.glob("*.ps1"):
            for linha in script.read_text(encoding="utf-8").splitlines():
                if "OLLAMA_HOST" in linha and "0.0.0.0" in linha:
                    with self.subTest(script=script.name):
                        self.assertIn("$protegido", linha)

    def test_scripts_chamados_pelo_instalador_entram_no_pacote(self):
        instalador = (NOTEBOOK / "instalar_no_notebook.ps1").read_text(encoding="utf-8")
        chamados = set(re.findall(r'Join-Path \$PSScriptRoot "([^"]+\.ps1)"', instalador))
        self.assertIn("proteger_ollama.ps1", chamados)
        pacote = (RAIZ / "build_release.ps1").read_text(encoding="utf-8")
        for script in chamados | {"PROTEGER-OLLAMA.cmd"}:
            with self.subTest(script=script):
                self.assertTrue((NOTEBOOK / script).is_file())
                self.assertIn(f"'{script}'", pacote)


if __name__ == "__main__":
    unittest.main()
