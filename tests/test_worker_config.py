"""Configuracao do worker: so interfaces privadas, token forte e Ollama local."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from nebula_worker.config import ConfigError, load_config, parse_config
from tests.worker_fixtures import make_signer

TOKEN = "k" * 40


class ConfigTests(unittest.TestCase):
    def setUp(self):
        signer = make_signer()
        self.base = {
            "bind_host": "100.78.67.81",
            "allowed_clients": ["100.92.82.41/32", "192.168.15.12/32"],
            "host_names": ["note.tail46f27e.ts.net"],
            "trusted_keys": {signer.key_id: signer.public_key_text},
            "models": {"qwen_edge": {"model": "qwen3.5:9b", "options": {"num_thread": 8}}},
        }
        self.env = {"NEBULA_WORKER_TOKEN": TOKEN}

    def parse(self, **changes):
        data = copy.deepcopy(self.base)
        data.update(changes)
        return parse_config(data, self.env)

    def assertInvalid(self, **changes):
        with self.assertRaises(ConfigError):
            self.parse(**changes)

    def test_configuracao_valida_do_notebook(self):
        config = self.parse()
        self.assertEqual((config.bind_host, config.port), ("100.78.67.81", 8790))
        self.assertEqual(config.allowed_scopes, frozenset({"model:qwen_edge:generate"}))
        self.assertEqual(config.allowed_host_headers,
                         ["100.78.67.81:8790", "note.tail46f27e.ts.net:8790"])
        self.assertEqual(config.models[0].base_url, "http://127.0.0.1:11434")

    def test_interface_explicita_e_privada(self):
        for host in ("0.0.0.0", "::", "8.8.8.8", "notebook", ""):
            self.assertInvalid(bind_host=host)
        for host in ("127.0.0.1", "192.168.15.4", "10.0.0.2", "100.100.1.1", "::1"):
            self.parse(bind_host=host)

    def test_clientes_so_de_redes_privadas(self):
        self.assertInvalid(allowed_clients=["0.0.0.0/0"])
        self.assertInvalid(allowed_clients=["8.8.8.0/24"])
        self.assertInvalid(allowed_clients=[])
        self.assertInvalid(allowed_clients=["192.168.15.12/24"])

    def test_token_forte_e_fora_do_arquivo(self):
        with self.assertRaises(ConfigError):
            parse_config(copy.deepcopy(self.base), {"NEBULA_WORKER_TOKEN": "curto"})
        with self.assertRaises(ConfigError):
            parse_config(copy.deepcopy(self.base), {})
        self.assertInvalid(token="colocar-o-token-aqui-nao-vale")

    def test_chave_publica_confere_com_o_id(self):
        outro = make_signer()
        self.assertInvalid(trusted_keys={outro.key_id: self.base["trusted_keys"][next(iter(self.base["trusted_keys"]))]})
        self.assertInvalid(trusted_keys={})
        self.assertInvalid(trusted_keys={"k_0000000000000000": "curta"})

    def test_ollama_so_na_propria_maquina(self):
        self.assertInvalid(models={"qwen_edge": {"model": "m", "base_url": "http://192.168.15.12:11434"}})
        self.assertInvalid(models={"qwen_edge": {"model": "m", "provider": "openai"}})
        self.assertInvalid(models={"qwen_edge": {"model": "m", "options": {"host": "x"}}})
        self.assertInvalid(models={"Qwen Edge": {"model": "m"}})
        self.assertInvalid(models={"qwen_edge": {"model": "m", "enabled": False}})

    def test_limites_e_campos_desconhecidos(self):
        self.assertInvalid(limits={"max_queue": 0})
        self.assertInvalid(limits={"max_queue": True})
        self.assertInvalid(limits={"sem_limite": 1})
        self.assertInvalid(allowed_client=["127.0.0.1/32"])
        config = self.parse(limits={"max_queue": 3, "max_timeout_ms": 60_000})
        self.assertEqual((config.limits.max_queue, config.limits.max_timeout_ms), (3, 60_000))

    def test_arquivo_de_exemplo_do_repositorio_e_valido(self):
        example = Path(__file__).resolve().parents[1] / "nebula_worker" / "worker.example.json"
        data = json.loads(example.read_text(encoding="utf-8"))
        signer = make_signer()
        data["trusted_keys"] = {signer.key_id: signer.public_key_text}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "worker.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            config = load_config(path, self.env)
        self.assertEqual(config.models[0].alias, "qwen_edge")


class LogDeServicoTests(unittest.TestCase):
    def test_bibliotecas_de_terceiros_nao_levam_payload_ao_disco(self):
        import logging
        import sys

        from nebula_worker.__main__ import _OmitPayload

        record = logging.LogRecord("mcp.server.runner", logging.ERROR, __file__, 1,
                                   "dropped %r: %s", ("tools/call", "PROMPT-SECRETO"), None)
        try:
            raise ValueError("input_value={'payload': 'PROMPT-SECRETO'}")
        except ValueError:
            record.exc_info = sys.exc_info()
        self.assertTrue(_OmitPayload().filter(record))
        text = logging.Formatter("%(message)s").format(record)
        self.assertNotIn("PROMPT-SECRETO", text)
        self.assertIn("ValueError", text)
        own = logging.LogRecord("nebula_worker", logging.INFO, __file__, 1, "porta %s", (8790,), None)
        _OmitPayload().filter(own)
        self.assertEqual(own.getMessage(), "porta 8790")


if __name__ == "__main__":
    unittest.main()
