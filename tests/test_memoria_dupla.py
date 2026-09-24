"""Memória comprimida entregue entre as duas IAs.

Cada rodada é uma instância nova de CLI, sem memória. Quando uma fica sem
crédito por horas e a outra continua, a que volta precisa saber o que perdeu —
senão recomeça propondo trabalho já concluído.
"""

import unittest

import memoria_dupla as md


def evento(seq, actor, kind, texto="", **extra):
    return {"seq": seq, "actor": actor, "kind": kind, "idea": "i1",
            "at": f"2026-09-23T21:{seq:02d}:00+00:00",
            "data": {"text": texto, **extra}}


class FaltaDeCotaTests(unittest.TestCase):
    def test_reconhece_limite_de_uso_do_codex(self) -> None:
        self.assertTrue(md.sem_cota("You have hit your usage limit. Try again at 7:55 PM."))

    def test_reconhece_saldo_de_credito_do_claude(self) -> None:
        self.assertTrue(md.sem_cota("Credit balance too low"))

    def test_nao_confunde_falha_de_login_com_falta_de_credito(self) -> None:
        """Quem errou a chave não volta sozinha às 19:55; a diferença importa."""
        self.assertFalse(md.sem_cota("invalid api key"))
        self.assertFalse(md.sem_cota("connection refused"))

    def test_extrai_a_hora_em_que_a_cota_volta(self) -> None:
        self.assertEqual(md.volta_em("Try again at 7:55 PM."), "19:55")
        self.assertEqual(md.volta_em("try again at 11:30 AM"), "11:30")
        self.assertEqual(md.volta_em("tente novamente às 08:05"), "08:05")

    def test_meia_noite_e_meio_dia_nao_se_confundem(self) -> None:
        self.assertEqual(md.volta_em("again at 12:00 AM"), "00:00")
        self.assertEqual(md.volta_em("again at 12:00 PM"), "12:00")

    def test_sem_hora_na_mensagem_nao_inventa_uma(self) -> None:
        self.assertEqual(md.volta_em("You have hit your usage limit."), "")


class DigestaoTests(unittest.TestCase):
    def estado(self, eventos, tarefas=()):
        return {"messages": eventos, "tasks": list(tarefas)}

    def test_entrega_o_que_passou_depois_da_ultima_fala_da_agente(self) -> None:
        estado = self.estado([
            evento(1, "codex", "chat_reply", "ja vou nessa"),
            evento(2, "opus", "note", "consertei a rota do chat"),
            evento(3, "user", "user_message", "otimo"),
        ])
        memoria = md.digerir(estado, "codex")
        self.assertIn("consertei a rota do chat", memoria)
        self.assertIn("otimo", memoria)
        self.assertNotIn("ja vou nessa", memoria, "o que ela mesma disse nao e novidade")

    def test_sem_lacuna_nao_gasta_contexto(self) -> None:
        """Na última fala da própria agente não há nada a recuperar."""
        estado = self.estado([evento(1, "opus", "note", "acabei")])
        self.assertEqual(md.digerir(estado, "opus"), "")

    def test_agente_que_nunca_falou_nao_recebe_o_diario_inteiro(self) -> None:
        estado = self.estado([evento(1, "opus", "note", "x"), evento(2, "user", "user_message", "y")])
        self.assertEqual(md.digerir(estado, "codex"), "")

    def test_contabilidade_de_token_fica_de_fora(self) -> None:
        estado = self.estado([
            evento(1, "codex", "chat_reply", "oi"),
            evento(2, "opus", "tokens_reserved", "reserva"),
            evento(3, "opus", "tokens_used", "medido"),
            evento(4, "opus", "note", "decisao que importa"),
        ])
        memoria = md.digerir(estado, "codex")
        self.assertIn("decisao que importa", memoria)
        self.assertNotIn("reserva", memoria)
        self.assertNotIn("medido", memoria)

    def test_secao_de_codigo_leva_arquivos_e_prova(self) -> None:
        estado = self.estado([
            evento(1, "codex", "chat_reply", "oi"),
            evento(2, "opus", "code_section", "", title="Rota do chat",
                   paths=["remote_server.py"], summary="liguei em /chat",
                   evidence="479 testes OK"),
        ])
        memoria = md.digerir(estado, "codex")
        self.assertIn("Rota do chat", memoria)
        self.assertIn("remote_server.py", memoria)
        self.assertIn("479 testes OK", memoria)

    def test_o_que_ainda_esta_aberto_vai_junto(self) -> None:
        estado = self.estado(
            [evento(1, "codex", "chat_reply", "oi"), evento(2, "opus", "note", "segui")],
            [{"title": "Versao mobile", "owner": "codex", "status": "queued",
              "paths": ["nebula_front/style.css"]},
             {"title": "Ja feita", "owner": "opus", "status": "completed", "paths": ["x.py"]}],
        )
        memoria = md.digerir(estado, "codex")
        self.assertIn("Versao mobile", memoria)
        self.assertIn("nebula_front/style.css", memoria)
        self.assertNotIn("Ja feita", memoria, "concluida nao esta em aberto")

    def test_corte_de_tamanho_preserva_o_mais_recente(self) -> None:
        """Estourar o contexto de quem volta seria pior que perder história antiga."""
        eventos = [evento(1, "codex", "chat_reply", "oi")]
        eventos += [evento(i, "opus", "note", f"antigo {i} " + "z" * 500) for i in range(2, 40)]
        eventos.append(evento(90, "opus", "note", "o mais recente de todos"))
        memoria = md.digerir(eventos and self.estado(eventos), "codex", limite=2000)
        self.assertIn("o mais recente de todos", memoria)
        self.assertIn("omitidos", memoria)
        self.assertLess(len(memoria), 4000)

    def test_deixa_claro_que_e_passado_e_nao_pedido_novo(self) -> None:
        estado = self.estado([evento(1, "codex", "chat_reply", "oi"),
                              evento(2, "user", "user_message", "faz isso")])
        memoria = md.digerir(estado, "codex")
        self.assertIn("já ocorrido", memoria)
        self.assertIn("Não refaça", memoria)


class AnotacaoNoDiarioTests(unittest.TestCase):
    class LojaFalsa:
        def __init__(self, ideias=(("i1",),)):
            self.registros = []
            self._ideias = [{"id": i[0]} for i in ideias]

        def snapshot(self):
            return {"ideas": self._ideias}

        def message(self, ideia, ator, texto, tipo):
            self.registros.append((ideia, ator, texto, tipo))

    def test_falta_de_cota_vira_passagem_de_bastao_com_a_hora(self) -> None:
        loja = self.LojaFalsa()
        md.anotar_falta_de_cota(loja, "codex", "You have hit your usage limit. Try again at 7:55 PM.")
        self.assertEqual(len(loja.registros), 1)
        _, ator, texto, tipo = loja.registros[0]
        self.assertEqual((ator, tipo), ("system", "handoff"))
        self.assertIn("19:55", texto)
        self.assertIn("codex", texto)

    def test_falha_comum_nao_vira_passagem_de_bastao(self) -> None:
        loja = self.LojaFalsa()
        md.anotar_falta_de_cota(loja, "codex", "connection refused")
        self.assertEqual(loja.registros, [])

    def test_sem_pedido_aberto_nao_quebra(self) -> None:
        loja = self.LojaFalsa(ideias=())
        md.anotar_falta_de_cota(loja, "opus", "usage limit")
        self.assertEqual(loja.registros, [])

    def test_diario_indisponivel_nao_derruba_a_rodada_que_esta_de_pe(self) -> None:
        class Quebrada(self.LojaFalsa):
            def message(self, *_):
                raise RuntimeError("banco travado")

        md.anotar_falta_de_cota(Quebrada(), "codex", "usage limit")  # não levanta


if __name__ == "__main__":
    unittest.main()
