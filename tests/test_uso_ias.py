"""Uso real das duas IAs: nada estimado, nada inventado quando falta fonte."""

import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import uso_ias


def credencial(pasta: Path, vence_em_s: float) -> Path:
    arquivo = pasta / ".credentials.json"
    arquivo.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "tok-secreto", "expiresAt": int((time.time() + vence_em_s) * 1000),
        "subscriptionType": "pro"}}), encoding="utf-8")
    return arquivo


class Resposta:
    def __init__(self, corpo): self.corpo = corpo
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.corpo).encode()


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())

    def test_le_as_duas_janelas_da_fonte_oficial(self):
        pedidos = []
        def abrir(pedido, timeout):
            pedidos.append(pedido)
            return Resposta({"five_hour": {"utilization": 29.0, "resets_at": "2026-09-25T04:19:59+00:00"},
                             "seven_day": {"utilization": 4.0, "resets_at": "2026-09-26T01:59:59+00:00"}})
        uso = uso_ias.uso_claude(credencial(self.pasta, 3600), abrir)
        self.assertEqual(uso["janela_5h"]["pct"], 29.0)
        self.assertEqual(uso["semanal"]["pct"], 4.0)
        self.assertEqual(uso["plano"], "pro")
        self.assertEqual(pedidos[0].full_url, uso_ias.URL_USO_CLAUDE)

    def test_token_vencido_nao_e_renovado_nem_usado(self):
        """Renovar por fora trocaria o token e derrubaria a sessão do Claude Code."""
        abrir = mock.Mock()
        uso = uso_ias.uso_claude(credencial(self.pasta, -10), abrir)
        abrir.assert_not_called()
        self.assertIn("vencida", uso["erro"])
        self.assertNotIn("janela_5h", uso)

    def test_falha_da_api_vira_motivo_e_nao_zero(self):
        def abrir(pedido, timeout):
            raise urllib.error.HTTPError(pedido.full_url, 429, "x", {}, None)
        uso = uso_ias.uso_claude(credencial(self.pasta, 3600), abrir)
        self.assertIn("429", uso["erro"])
        self.assertNotIn("janela_5h", uso)

    def test_o_token_nunca_aparece_no_resultado(self):
        abrir = lambda p, timeout: Resposta({"five_hour": {"utilization": 1}, "seven_day": {"utilization": 2}})
        self.assertNotIn("tok-secreto", json.dumps(uso_ias.uso_claude(credencial(self.pasta, 3600), abrir)))

    def test_sem_credencial_diz_o_motivo(self):
        self.assertIn("não encontrada", uso_ias.uso_claude(self.pasta / "nada.json")["erro"])


class CodexTests(unittest.TestCase):
    def sessao(self, eventos):
        raiz = Path(tempfile.mkdtemp())
        pasta = raiz / "2026" / "09" / "24"
        pasta.mkdir(parents=True)
        (pasta / "rollout-x.jsonl").write_text("\n".join(json.dumps(e) for e in eventos), encoding="utf-8")
        return raiz

    def test_janela_se_identifica_pela_duracao_nao_pelo_nome(self):
        raiz = self.sessao([{"timestamp": "2026-09-24T23:00:00Z", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 3.0, "window_minutes": 300, "resets_at": 1790311698},
            "secondary": {"used_percent": 93.0, "window_minutes": 10080, "resets_at": 1790714718},
            "credits": {"has_credits": False, "balance": "0"}, "plan_type": "plus"}}}])
        uso = uso_ias.uso_codex(raiz)
        self.assertEqual(uso["janela_5h"]["pct"], 3.0)
        self.assertEqual(uso["semanal"]["pct"], 93.0)
        self.assertEqual(uso["atualizado_em"], "2026-09-24T23:00:00Z")

    def test_vale_o_registro_mais_recente(self):
        evento = lambda pct: {"payload": {"rate_limits": {"primary": {"used_percent": pct, "window_minutes": 300}}}}
        uso = uso_ias.uso_codex(self.sessao([evento(10), evento(55)]))
        self.assertEqual(uso["janela_5h"]["pct"], 55)

    def test_sem_registro_diz_o_motivo(self):
        self.assertIn("ainda não registrou", uso_ias.uso_codex(Path(tempfile.mkdtemp()))["erro"])


class SomaEResumoTests(unittest.TestCase):
    def test_soma_os_tokens_medidos_de_todos_os_pedidos(self):
        estado = {"budgets": {"a": {"opus": {"measured": 100}, "codex": {"measured": 40}},
                              "b": {"opus": {"measured": 5, "unknown_calls": 2}, "codex": {"measured": 0}}}}
        t = uso_ias.tokens_da_dupla(estado)
        self.assertEqual((t["opus"], t["codex"], t["soma"]), (105, 40, 145))
        self.assertEqual(t["chamadas_sem_medida"]["opus"], 2)

    def test_resumo_para_as_ias_traz_as_duas(self):
        linha = uso_ias.resumo_para_agentes({
            "opus": {"janela_5h": {"pct": 29}, "semanal": {"pct": 4}},
            "codex": {"janela_5h": {"pct": 3}, "semanal": {"pct": 93}}})
        self.assertIn("Claude: 5 h 29%", linha)
        self.assertIn("semana 93%", linha)

    def test_resumo_nao_inventa_quando_falta_fonte(self):
        self.assertIn("indisponível", uso_ias.resumo_para_agentes({"opus": {"erro": "x"}, "codex": {}}))


if __name__ == "__main__":
    unittest.main()
