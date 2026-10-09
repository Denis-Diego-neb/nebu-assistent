import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import front_window


class NavegadorTests(unittest.TestCase):
    def test_brave_vem_antes_de_chrome_e_edge(self):
        instalados = {"chrome.exe": "/bin/chrome", "msedge.exe": "/bin/edge", "brave.exe": "/bin/brave"}
        with patch("front_window.shutil.which", side_effect=instalados.get):
            self.assertEqual(front_window.encontrar_navegador(), "/bin/brave")
        del instalados["brave.exe"]
        with patch("front_window.shutil.which", side_effect=instalados.get):
            self.assertEqual(front_window.encontrar_navegador(), "/bin/chrome")

    def test_brave_instalado_por_usuario_ganha_do_chrome_no_path(self):
        with tempfile.TemporaryDirectory() as pasta:
            brave = Path(pasta) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"
            brave.parent.mkdir(parents=True)
            brave.write_bytes(b"")
            vazia = str(Path(pasta) / "sem-programas")
            # O Windows visto pelo módulo: pastas de instalação isoladas do PC real.
            windows = SimpleNamespace(name="nt", environ={
                "LOCALAPPDATA": pasta, "PROGRAMFILES": vazia, "PROGRAMFILES(X86)": vazia})
            with patch.object(front_window, "os", windows), patch(
                "front_window.shutil.which", side_effect={"chrome.exe": "C:/chrome.exe"}.get
            ):
                self.assertEqual(front_window.encontrar_navegador(), str(brave))

    def test_janela_de_midia_libera_som_e_nao_mexe_em_perfil_existente(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(
            front_window, "PERFIL_MIDIA", Path(pasta) / "midia"
        ), patch("front_window.encontrar_navegador", return_value="/bin/brave"), patch(
            "front_window.subprocess.Popen"
        ) as popen:
            front_window.abrir_midia("http://127.0.0.1:8766/hub/chuva.html?k=x")
            preferencias = Path(pasta) / "midia" / "Default" / "Preferences"
            dados = json.loads(preferencias.read_text(encoding="utf-8"))
            self.assertEqual(dados["profile"]["default_content_setting_values"]["autoplay"], 1)
            argumentos = popen.call_args.args[0]
            self.assertEqual(argumentos[0], "/bin/brave")
            self.assertIn("--kiosk", argumentos)
            self.assertIn("--autoplay-policy=no-user-gesture-required", argumentos)
            preferencias.write_text('{"meu": true}', encoding="utf-8")
            front_window.abrir_midia("http://127.0.0.1:8766/hub/chuva.html?k=x")
            self.assertEqual(json.loads(preferencias.read_text(encoding="utf-8")), {"meu": True})


if __name__ == "__main__":
    unittest.main()
