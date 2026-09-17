import json
import unittest
from unittest.mock import patch

from conversa_local import AcaoQwen, ConversaLocal, ResultadoQwen


class RespostaFalsa:
    def __init__(self, conteudo: str) -> None:
        self.conteudo = conteudo

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"message": {"content": self.conteudo}}


class ConversaLocalEstruturadaTests(unittest.TestCase):
    def test_modo_ritmo_explicito_vira_ligar_e_iniciar(self) -> None:
        resultado = ConversaLocal().interpretar_ou_responder(
            "acenda a lampada no modo ritimo com a musica do youtube"
        )
        self.assertEqual(
            resultado,
            ResultadoQwen(
                "comando",
                (
                    AcaoQwen("abajur_ligar"),
                    AcaoQwen("abajur_musica_iniciar"),
                ),
            ),
        )

    def test_modo_ritmo_com_cor_preserva_a_ordem_das_acoes(self) -> None:
        resultado = ConversaLocal().interpretar_ou_responder(
            "acenda a lampada vermelha no modo ritmo com a musica"
        )
        self.assertEqual(
            resultado,
            ResultadoQwen(
                "comando",
                (
                    AcaoQwen("abajur_ligar"),
                    AcaoQwen("abajur_cor", "vermelho"),
                    AcaoQwen("abajur_musica_iniciar"),
                ),
            ),
        )

    def test_intensidade_do_ritmo_em_percentual(self) -> None:
        resultado = ConversaLocal().interpretar_ou_responder(
            "modo ritimo em 90% de intensidade"
        )

        self.assertEqual(
            resultado,
            ResultadoQwen(
                "comando",
                (AcaoQwen("abajur_musica_intensidade", "90"),),
            ),
        )

    def test_ativa_ritmo_com_intensidade_preserva_ordem(self) -> None:
        resultado = ConversaLocal().interpretar_ou_responder(
            "ative o modo ritmo em 75% de intensidade"
        )

        self.assertEqual(
            resultado,
            ResultadoQwen(
                "comando",
                (
                    AcaoQwen("abajur_musica_iniciar"),
                    AcaoQwen("abajur_musica_intensidade", "75"),
                ),
            ),
        )

    @staticmethod
    def resposta(dados: object) -> RespostaFalsa:
        return RespostaFalsa(json.dumps(dados, ensure_ascii=False))

    @patch("conversa_local.MEMORIA.para_prompt", return_value="")
    @patch("conversa_local.requests.post")
    def test_comando_composto_valido(self, post, _memoria) -> None:
        post.return_value = self.resposta({
            "tipo": "comando",
            "acoes": [
                {"acao": "abajur_temperatura", "argumento": "quente"},
                {"acao": "abajur_diminuir_brilho", "argumento": "20"},
            ],
            "resposta": "",
        })

        resultado = ConversaLocal().interpretar_ou_responder(
            "mude a temperatura da luz para mais baixa e diminua o brilho 20%"
        )

        self.assertEqual(
            resultado,
            ResultadoQwen(
                tipo="comando",
                acoes=(
                    AcaoQwen("abajur_temperatura", "quente"),
                    AcaoQwen("abajur_diminuir_brilho", "20"),
                ),
            ),
        )
        post.assert_called_once()
        requisicao = post.call_args.kwargs["json"]
        self.assertEqual(requisicao["options"]["temperature"], 0)
        self.assertEqual(requisicao["format"], "json")
        self.assertIn('"acoes"', requisicao["messages"][0]["content"])
        self.assertIn("Temperatura mais baixa", requisicao["messages"][0]["content"])
        self.assertIn("seria legal", requisicao["messages"][0]["content"])

    @patch("conversa_local.MEMORIA.para_prompt", return_value="")
    @patch("conversa_local.requests.post")
    def test_composto_corrige_musica_parar_para_iniciar(self, post, _memoria) -> None:
        post.return_value = self.resposta({
            "tipo": "comando",
            "acoes": [
                {"acao": "abajur_temperatura", "argumento": "fria"},
                {"acao": "abajur_musica_parar", "argumento": ""},
            ],
            "resposta": "",
        })

        resultado = ConversaLocal().interpretar_ou_responder(
            "deixe a luz o mais gelada que der, e deixe no ritimo do navegador"
        )

        self.assertEqual(
            resultado,
            ResultadoQwen(
                "comando",
                (
                    AcaoQwen("abajur_temperatura", "fria"),
                    AcaoQwen("abajur_musica_iniciar"),
                ),
            ),
        )
        post.assert_called_once()
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("ritimo do navegador", prompt)
        self.assertIn("nunca significa parar", prompt)

    @patch("conversa_local.MEMORIA.para_prompt", return_value="")
    @patch("conversa_local.requests.post")
    def test_ativa_animacao_musical_sem_alvo_explicito(self, post, _memoria) -> None:
        # Mesmo que o modelo trate a frase como conversa, a validação semântica
        # recupera o comando explícito e permitido sem executar texto livre.
        post.return_value = self.resposta({
            "tipo": "conversa",
            "acoes": [],
            "resposta": "Posso ativar a animação musical.",
        })

        resultado = ConversaLocal().interpretar_ou_responder(
            "ative a animação musical"
        )

        self.assertEqual(
            resultado,
            ResultadoQwen("comando", (AcaoQwen("abajur_musica_iniciar"),)),
        )
        post.assert_called_once()

    @patch("conversa_local.MEMORIA.para_prompt", return_value="")
    @patch("conversa_local.requests.post")
    def test_conversa_valida_atualiza_historico(self, post, _memoria) -> None:
        post.return_value = self.resposta({
            "tipo": "conversa",
            "acoes": [],
            "resposta": "Boa noite! Como posso ajudar?",
        })
        conversa = ConversaLocal()

        resultado = conversa.interpretar_ou_responder("boa noite")

        self.assertEqual(
            resultado,
            ResultadoQwen("conversa", (), "Boa noite! Como posso ajudar?"),
        )
        self.assertEqual(
            list(conversa.historico),
            [
                {"role": "user", "content": "boa noite"},
                {"role": "assistant", "content": "Boa noite! Como posso ajudar?"},
            ],
        )
        post.assert_called_once()

    @patch("conversa_local.MEMORIA.para_prompt", return_value="")
    @patch("conversa_local.requests.post")
    def test_rejeita_acao_alucinada_e_json_invalido(self, post, _memoria) -> None:
        casos = (
            self.resposta({
                "tipo": "comando",
                "acoes": [{"acao": "formatar_computador", "argumento": ""}],
                "resposta": "",
            }),
            RespostaFalsa("isto não é json"),
        )
        conversa = ConversaLocal()
        for resposta in casos:
            with self.subTest(conteudo=resposta.conteudo):
                post.return_value = resposta
                with self.assertRaises(RuntimeError):
                    conversa.interpretar_ou_responder("faça algo")

    @patch("conversa_local.MEMORIA.para_prompt", return_value="")
    @patch("conversa_local.requests.post")
    def test_rejeita_argumentos_invalidos(self, post, _memoria) -> None:
        casos = (
            {"acao": "abajur_temperatura", "argumento": "baixa"},
            {"acao": "abajur_brilho", "argumento": "0"},
            {"acao": "abajur_brilho", "argumento": "101"},
            {"acao": "abajur_brilho", "argumento": "20%"},
            {"acao": "abajur_diminuir_brilho", "argumento": "100"},
            {"acao": "abajur_aumentar_brilho", "argumento": "0"},
            {"acao": "abajur_cor", "argumento": "ultravioleta"},
            {"acao": "abrir_aplicativo", "argumento": ""},
            {"acao": "capturar_tela", "argumento": "agora"},
        )
        conversa = ConversaLocal()
        for acao in casos:
            with self.subTest(acao=acao):
                post.return_value = self.resposta({
                    "tipo": "comando",
                    "acoes": [acao],
                    "resposta": "",
                })
                with self.assertRaises(RuntimeError):
                    conversa.interpretar_ou_responder("pedido")


if __name__ == "__main__":
    unittest.main()
