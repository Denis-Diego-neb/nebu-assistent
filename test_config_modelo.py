import os
import unittest
from unittest.mock import patch

from config_modelo import OLLAMA_URL_PADRAO, obter_url_ollama, qwen_ativa
from conversa_local import ConversaLocal
from grupo_chat import PonteGrupo


class ConfiguracaoModeloTests(unittest.TestCase):
    def test_padrao_aponta_somente_para_o_notebook(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(OLLAMA_URL_PADRAO, "http://192.168.15.86:11434")
            self.assertEqual(obter_url_ollama(), OLLAMA_URL_PADRAO)
            self.assertEqual(ConversaLocal().url, OLLAMA_URL_PADRAO)
            self.assertEqual(PonteGrupo().url_ollama, OLLAMA_URL_PADRAO)
            self.assertFalse(qwen_ativa())

    def test_qwen_precisa_ser_ativada_explicitamente(self) -> None:
        with patch.dict(os.environ, {"NEBULA_QWEN_ENABLED": "sim"}, clear=True):
            self.assertTrue(qwen_ativa())

    def test_url_ollama_configura_as_duas_interfaces(self) -> None:
        with patch.dict(
            os.environ,
            {"NEBULA_OLLAMA_URL": "http://notebook-nebula:11434/"},
            clear=True,
        ):
            self.assertEqual(obter_url_ollama(), "http://notebook-nebula:11434")


if __name__ == "__main__":
    unittest.main()
