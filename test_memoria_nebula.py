import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
import memoria_nebula
from conversa_local import ConversaLocal
from memoria_nebula import (
    MemoriaNebula,
    encontrar_ultima_interacao,
    interpretar_comando_feedback,
    interpretar_comando_contexto,
    interpretar_comando_correcao,
)


class MemoriaNebulaTests(unittest.TestCase):
    def criar(self, pasta: str) -> MemoriaNebula:
        raiz = Path(pasta)
        base = raiz / "base.md"
        base.write_text("Contexto de base", encoding="utf-8")
        return MemoriaNebula(
            contexto_usuario=raiz / "usuario.md",
            correcoes_file=raiz / "correcoes.json",
            contexto_base=base,
            feedback_file=raiz / "feedbacks.json",
        )

    def test_correcao_e_aplicada_em_frase_completa(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            memoria.registrar_correcao("clipe isso", "clipe isso")
            memoria.registrar_correcao("quibe isso", "clipe isso")
            self.assertEqual(memoria.aplicar_correcoes("Nebu quibe isso agora"), "nebu clipe isso agora")

    def test_contexto_combina_base_usuario_e_correcoes(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            memoria.adicionar_contexto("Prefere respostas diretas")
            memoria.registrar_correcao("nevo", "nebu")
            prompt = memoria.para_prompt()
            self.assertIn("Contexto de base", prompt)
            self.assertIn("Prefere respostas diretas", prompt)
            self.assertIn('"nevo"', prompt)

    def test_interpreta_comandos_de_ensino(self) -> None:
        self.assertEqual(
            interpretar_comando_correcao("quando eu disser nevo entenda como nebu"),
            ("nevo", "nebu"),
        )
        self.assertEqual(
            interpretar_comando_contexto("guarde na sua memória que eu prefiro azul"),
            "eu prefiro azul",
        )
        self.assertEqual(
            interpretar_comando_feedback("não gostei dessa resposta porque ficou robótica"),
            ("negativo", "ficou robotica"),
        )

    def test_correcao_pode_recuperar_a_palavra_nebu(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            memoria.registrar_correcao("nevo", "nebu")
            with patch.object(memoria_nebula, "MEMORIA", memoria):
                chamou, comando = main.extrair_chamada("nevo clipe isso")
            self.assertTrue(chamou)
            self.assertEqual(comando, "clipe isso")

    def test_conversa_local_recebe_memoria_no_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            memoria.adicionar_contexto("Humanize a resposta")
            recebido: dict[str, object] = {}

            class Resposta:
                def raise_for_status(self) -> None: pass
                def json(self) -> dict[str, object]:
                    return {"message": {"content": "Entendido"}}

            def post(*_args, **kwargs):
                recebido.update(kwargs)
                return Resposta()

            conversa = ConversaLocal()
            with patch("conversa_local.MEMORIA", memoria), patch("conversa_local.requests.post", post):
                self.assertEqual(conversa.responder("oi"), "Entendido")
            sistema = recebido["json"]["messages"][0]["content"]  # type: ignore[index]
            self.assertIn("Humanize a resposta", sistema)

    def test_nebula_ensina_correcao_e_contexto_por_comando(self) -> None:
        class Saida:
            def __init__(self) -> None:
                self.mensagens: list[str] = []
            def falar(self, texto: str) -> None:
                self.mensagens.append(texto)

        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            saida = Saida()
            nebula = main.Nebula(saida, abrir_navegador=False)
            with patch("main.MEMORIA", memoria):
                self.assertTrue(nebula.executar("quando eu disser nevo entenda como nebu"))
                self.assertTrue(nebula.executar("guarde na sua memória que eu gosto de azul"))
            self.assertEqual(memoria.listar_correcoes()["nevo"], "nebu")
            self.assertIn("eu gosto de azul", memoria.ler_contexto_usuario())
            self.assertEqual(len(saida.mensagens), 2)

    def test_feedback_fica_local_e_entra_no_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            memoria.registrar_feedback(
                canal="conversa",
                autor="Nebula",
                pergunta="Como faço isso?",
                resposta="Resposta longa e fria.",
                avaliacao="negativo",
                comentario="Seja mais natural e dê um exemplo.",
                alvo_id="resposta-1",
            )
            feedbacks = memoria.listar_feedbacks()
            self.assertEqual(len(feedbacks), 1)
            self.assertEqual(feedbacks[0]["avaliacao"], "negativo")
            prompt = memoria.para_prompt()
            self.assertIn("PRECISA MELHORAR", prompt)
            self.assertIn("Seja mais natural", prompt)

    def test_nova_avaliacao_substitui_a_anterior_da_mesma_resposta(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            dados = dict(
                canal="grupo", autor="Qwen", pergunta="Oi", resposta="Olá",
                alvo_id="qwen-1",
            )
            memoria.registrar_feedback(**dados, avaliacao="negativo")
            memoria.registrar_feedback(**dados, avaliacao="positivo", comentario="Agora ficou bom")
            feedbacks = memoria.listar_feedbacks()
            self.assertEqual(len(feedbacks), 1)
            self.assertEqual(feedbacks[0]["avaliacao"], "positivo")

    def test_encontra_ultima_resposta_e_pergunta_correspondente(self) -> None:
        mensagens = [
            {"autor": "Você", "texto": "Primeira"},
            {"autor": "Qwen", "texto": "Resposta Qwen", "criado_em": 1},
            {"autor": "Codex", "texto": "Resposta Codex", "criado_em": 2},
        ]
        alvo = encontrar_ultima_interacao(mensagens, {"Qwen"})
        self.assertIsNotNone(alvo)
        assert alvo is not None
        self.assertEqual(alvo["autor"], "Qwen")
        self.assertEqual(alvo["pergunta"], "Primeira")
        self.assertEqual(alvo["alvo_id"], "1")

    def test_feedback_pode_ser_dado_por_voz(self) -> None:
        class Saida:
            def __init__(self) -> None:
                self.mensagens: list[str] = []
            def falar(self, texto: str) -> None:
                self.mensagens.append(texto)

        with tempfile.TemporaryDirectory() as pasta:
            memoria = self.criar(pasta)
            saida = Saida()
            nebula = main.Nebula(saida, abrir_navegador=False)
            with patch("main.MEMORIA", memoria):
                self.assertTrue(nebula.executar("oi"))
                self.assertTrue(nebula.executar(
                    "não gostei dessa resposta porque ficou robótica"
                ))
            feedback = memoria.listar_feedbacks()[0]
            self.assertEqual(feedback["pergunta"], "oi")
            self.assertEqual(feedback["avaliacao"], "negativo")
            self.assertEqual(feedback["comentario"], "ficou robotica")


if __name__ == "__main__":
    unittest.main()
