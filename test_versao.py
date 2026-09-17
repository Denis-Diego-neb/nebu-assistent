from pathlib import Path
import unittest

from versao import VERSAO_NEBULA


class VersaoCompartilhadaTests(unittest.TestCase):
    def test_gradle_obtem_versao_do_mesmo_arquivo_do_desktop(self) -> None:
        gradle = Path("android/app/build.gradle").read_text(encoding="utf-8")
        self.assertRegex(VERSAO_NEBULA, r"^\d+\.\d+\.\d+$")
        self.assertIn("../../versao.py", gradle)
        self.assertIn("versionName nebulaVersionName", gradle)
        self.assertNotRegex(gradle, r"versionName\s+['\"]\d")


if __name__ == "__main__":
    unittest.main()
