"""Provedor da Dupla com acesso real ao repositório.

O provedor padrão chama os CLIs sem ferramenta nenhuma, e foi isso que fez o
modo Dupla parecer inútil para desenvolver. Aqui se verifica que as ferramentas
realmente chegam à linha de comando, que a guarda do Git continua de pé e que
uma falha de cota aparece com o motivo verdadeiro — sem isso, ninguém sabe que
a outra IA precisa assumir o que faltou.
"""

import json
import unittest
from unittest import mock

import colaboracao_ferramentas as cf
from services.collaboration.providers import CLIProvider

ESQUEMA = {"type": "object", "properties": {"text": {"type": "string"}}}


class MotivoDaFalhaTests(unittest.TestCase):
    def test_limite_de_cota_do_codex_chega_inteiro(self) -> None:
        saida = "\n".join([
            '{"type":"thread.started","thread_id":"x"}',
            '{"type":"turn.failed","error":{"message":"You have hit your usage limit. Try again at 7:55 PM."}}',
        ])
        self.assertIn("usage limit", cf.motivo(saida, ""))
        self.assertIn("7:55 PM", cf.motivo(saida, ""))

    def test_erro_do_claude_vem_do_envelope(self) -> None:
        self.assertEqual(
            cf.motivo('{"is_error":true,"result":"Credit balance too low"}', ""),
            "Credit balance too low",
        )

    def test_sem_json_usavel_cai_no_stderr(self) -> None:
        self.assertEqual(cf.motivo("lixo nao json", "acesso negado\n"), "acesso negado")

    def test_sem_nada_diz_que_nao_ha_explicacao_em_vez_de_inventar(self) -> None:
        self.assertIn("sem explicar", cf.motivo("", ""))

    def test_motivo_e_truncado_para_nao_estourar_o_painel(self) -> None:
        enorme = json.dumps({"type": "error", "message": "x" * 5000})
        self.assertLessEqual(len(cf.motivo(enorme, "")), 600)


class ArgumentosDoCliTests(unittest.TestCase):
    """O ponto da mudança é a linha de comando; é ela que precisa ser checada."""

    def executar(self, agente, retorno='{"type":"x"}'):
        provedor = cf.ProvedorComAcesso()
        concluido = mock.Mock(returncode=0, stdout=retorno, stderr="")
        with mock.patch.object(cf.subprocess, "run", return_value=concluido) as chamada, \
                mock.patch.object(cf, "executable", return_value="C:\\fake\\cli.exe"), \
                mock.patch.object(cf, "parse_codex", side_effect=lambda *a: "codex-ok"), \
                mock.patch.object(cf, "parse_claude", side_effect=lambda *a: "claude-ok"):
            provedor.complete(agente, "pedido do coordenador", ESQUEMA, ".")
        return chamada.call_args

    def test_claude_recebe_ferramentas_de_verdade(self) -> None:
        argumentos = self.executar("opus")[0][0]
        self.assertIn("--tools", argumentos)
        ferramentas = argumentos[argumentos.index("--tools") + 1]
        for nome in ("Read", "Grep", "Bash", "Edit", "Write"):
            self.assertIn(nome, ferramentas)
        self.assertNotEqual(ferramentas, "", "lista vazia era o modo sem acesso")

    def test_codex_pode_escrever_no_espaco_de_trabalho(self) -> None:
        argumentos = self.executar("codex")[0][0]
        self.assertEqual(argumentos[argumentos.index("--sandbox") + 1], "workspace-write")

    def test_codex_nunca_recebe_acesso_total_fora_do_projeto(self) -> None:
        self.assertNotIn("danger-full-access", self.executar("codex")[0][0])

    def test_a_autorizacao_precede_o_pedido_do_coordenador(self) -> None:
        """O prompt do coordenador proíbe ferramentas; a liberação vem antes dele."""
        entrada = self.executar("opus")[1]["input"]
        self.assertLess(entrada.index("AUTORIZAÇÃO DO OPERADOR"),
                        entrada.index("pedido do coordenador"))
        self.assertIn("sem efeito", entrada)

    def test_a_rodada_tem_folga_para_ler_editar_e_rodar_teste(self) -> None:
        self.assertGreaterEqual(cf.ProvedorComAcesso().timeout, 600)
        self.assertGreater(cf.ProvedorComAcesso().timeout, CLIProvider().timeout)

    def test_falha_do_cli_carrega_o_motivo_ate_quem_le(self) -> None:
        provedor = cf.ProvedorComAcesso()
        quebrado = mock.Mock(returncode=1, stderr="",
                             stdout='{"type":"error","message":"usage limit"}')
        with mock.patch.object(cf.subprocess, "run", return_value=quebrado), \
                mock.patch.object(cf, "executable", return_value="C:\\fake\\cli.exe"):
            with self.assertRaises(RuntimeError) as erro:
                provedor.complete("codex", "oi", ESQUEMA, ".")
        self.assertIn("usage limit", str(erro.exception))


class GuardasTests(unittest.TestCase):
    def test_a_exigencia_de_repositorio_git_continua_valendo(self) -> None:
        """Com escrita direta, o Git é a única forma de desfazer.

        ``Coordinator.start`` só exige raiz de repositório quando o provedor é
        um ``CLIProvider``; herdar mantém essa exigência de pé.
        """
        self.assertIsInstance(cf.ProvedorComAcesso(), CLIProvider)

    def test_da_para_voltar_ao_modo_sem_ferramentas_sem_recompilar(self) -> None:
        with mock.patch.dict(cf.os.environ, {"NEBULA_DUPLA_SEM_FERRAMENTAS": "1"}):
            self.assertFalse(cf.ativo())
        with mock.patch.dict(cf.os.environ, {"NEBULA_DUPLA_SEM_FERRAMENTAS": ""}):
            self.assertTrue(cf.ativo())

    def test_o_painel_usa_o_provedor_com_acesso(self) -> None:
        import remote_server

        remote_server._COLABORACAO["api"] = None
        remote_server._COLABORACAO["tentado_em"] = 0.0
        try:
            api = remote_server.colaboracao()
            self.assertIsInstance(api.coordinator.provider, cf.ProvedorComAcesso)
        finally:
            remote_server._COLABORACAO["api"] = None
            remote_server._COLABORACAO["tentado_em"] = 0.0


if __name__ == "__main__":
    unittest.main()
