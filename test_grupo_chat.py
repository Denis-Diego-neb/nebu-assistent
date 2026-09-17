import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from grupo_chat import PonteGrupo, extrair_resposta_codex


class RespostaFalsa:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"message": {"content": "Resposta da Qwen"}}


class GrupoChatTests(unittest.TestCase):
    def test_rodada_persiste_usuario_qwen_e_codex(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "grupo.json"
            prompts_codex: list[str] = []

            def codex(prompt: str) -> str:
                prompts_codex.append(prompt)
                return "Resposta do Codex"

            ponte = PonteGrupo(
                caminho_historico=caminho,
                post_http=lambda *args, **kwargs: RespostaFalsa(),
                executar_codex=codex,
            )
            with patch.dict("os.environ", {"NEBULA_QWEN_ENABLED": "1"}):
                ponte.enviar("Olá, grupo")
            self.assertTrue(ponte.aguardar(2))
            historico = ponte.historico()
            self.assertEqual([m["autor"] for m in historico], ["Você", "Qwen", "Codex"])
            self.assertIn("[Qwen] Resposta da Qwen", prompts_codex[0])
            salvo = json.loads(caminho.read_text(encoding="utf-8"))
            self.assertEqual(salvo[-1]["texto"], "Resposta do Codex")

    def test_qwen_desativada_nao_e_consultada_no_grupo(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, patch.dict(
            "os.environ", {"NEBULA_QWEN_ENABLED": "0"}
        ):
            post = Mock()
            ponte = PonteGrupo(
                caminho_historico=Path(pasta) / "grupo.json",
                post_http=post,
                executar_codex=lambda _prompt: "Somente Codex",
            )
            ponte.enviar("Olá", ("qwen", "codex"))
            self.assertTrue(ponte.aguardar(2))
            self.assertEqual(
                [item["autor"] for item in ponte.historico()],
                ["Você", "Codex"],
            )
            post.assert_not_called()

    def test_historico_e_recarregado(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "grupo.json"
            caminho.write_text(
                json.dumps([{"autor": "Você", "texto": "Memória"}]),
                encoding="utf-8",
            )
            ponte = PonteGrupo(caminho_historico=caminho)
            self.assertEqual(ponte.historico()[0]["texto"], "Memória")

    def test_extrai_ultima_resposta_do_codex(self) -> None:
        saida = "\n".join((
            '{"type":"item.completed","item":{"type":"agent_message","text":"primeira"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"final"}}',
        ))
        self.assertEqual(extrair_resposta_codex(saida), "final")


if __name__ == "__main__":
    unittest.main()
