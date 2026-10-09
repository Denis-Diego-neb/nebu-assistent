import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from modo_chuva import CICLO_AR_S, gerar_trovoes
from notebook_power_server.coordenador_chuva import ATRASO_INICIO_S, CoordenadorChuva


VIDEO = "https://www.youtube.com/watch?v=abcdefghijk"


class Relogio:
    def __init__(self) -> None:
        self.agora = 1_000_000.0
        self.eventos: list[tuple[float, str]] = []

    def __call__(self) -> float:
        return self.agora

    def aguardar(self, segundos: float) -> None:
        self.agora += segundos


class CoordenadorChuvaTests(unittest.TestCase):
    def setUp(self) -> None:
        pasta = TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.caminho = Path(pasta.name) / "modo_chuva.json"
        self.relogio = Relogio()
        self.ar = Mock()
        self.timer = Mock()
        self.lampada = Mock()
        self.lampada.relampago.side_effect = lambda _f: self.relogio.eventos.append((self.relogio.agora, "luz"))
        self.tocar = Mock(side_effect=lambda _s: self.relogio.eventos.append((self.relogio.agora, "som")))
        self.tela = Mock()
        self.pc = Mock()
        self.chuva = self.novo()

    def novo(self) -> CoordenadorChuva:
        return CoordenadorChuva(
            caminho=self.caminho, ar=self.ar, timer_ar=self.timer,
            lampada=lambda: self.lampada, tocar=self.tocar, tela=self.tela,
            url_tela=lambda chave: f"http://127.0.0.1:8766/hub/chuva.html?k={chave}",
            avisar_pc=self.pc, url_pc=lambda chave: f"http://192.168.15.4:8766/hub/chuva.html?k={chave}",
            resolver_video=Mock(return_value=None), relogio=self.relogio,
            aguardar=self.relogio.aguardar, em_segundo_plano=lambda tarefa: tarefa(),
        )

    def test_inicio_prepara_casa_e_telas(self) -> None:
        estado = self.chuva.iniciar(VIDEO, "celular")
        self.assertTrue(estado["ativo"])
        self.assertEqual(estado["video_id"], "abcdefghijk")
        self.timer.set.assert_called_once_with(0)
        self.lampada.energia.assert_called_once_with(False)
        chave = json.loads(self.caminho.read_text(encoding="utf-8"))["chave"]
        self.tela.abrir.assert_called_once_with(f"http://127.0.0.1:8766/hub/chuva.html?k={chave}")
        self.pc.assert_called_once_with(
            "chuva.iniciar", {"url": f"http://192.168.15.4:8766/hub/chuva.html?k={chave}"})
        self.assertTrue(self.chuva.autoriza(chave))
        self.assertFalse(self.chuva.autoriza("outra"))
        self.assertEqual(set(self.chuva.estado_tela()), {"ativo", "agora", "inicio", "video_id"})

    def test_sem_link_pesquisa_e_falha_sem_resultado(self) -> None:
        self.chuva.resolver_video = Mock(return_value="https://www.youtube.com/watch?v=chuvachuva1&autoplay=1")
        self.assertEqual(self.chuva.iniciar("", "pc")["video_id"], "chuvachuva1")
        self.chuva.resolver_video.assert_called_once_with("som de chuva para dormir")
        self.chuva.resolver_video = Mock(return_value=None)
        with self.assertRaises(ValueError):
            self.chuva.iniciar("chuva forte", "pc")

    def test_ar_alterna_uma_hora_ligado_uma_desligado(self) -> None:
        self.chuva.iniciar(VIDEO)
        inicio = self.chuva.estado()["inicio"]
        for deslocamento, esperado in ((1, True), (CICLO_AR_S + 1, False), (2 * CICLO_AR_S + 1, True)):
            self.relogio.agora = inicio + deslocamento
            self.chuva.tick()
            self.chuva.tick()
            self.assertEqual(self.ar.executar.call_args_list[-1].args, ("power", esperado))
        self.assertEqual(self.ar.executar.call_count, 3)

    def test_falha_do_ar_tenta_de_novo_depois_de_um_minuto(self) -> None:
        self.chuva.iniciar(VIDEO)
        self.ar.executar.side_effect = [RuntimeError("O Smart IR nao respondeu."), None]
        self.chuva.tick()
        self.assertIn("ar", self.chuva.estado()["erros"])
        self.relogio.agora += 30
        self.chuva.tick()
        self.assertEqual(self.ar.executar.call_count, 1)
        self.relogio.agora += 31
        self.chuva.tick()
        self.assertEqual(self.ar.executar.call_count, 2)
        self.assertNotIn("ar", self.chuva.estado()["erros"])

    def test_relampago_antes_do_trovao_e_trovao_atrasado_nao_toca(self) -> None:
        self.chuva.iniciar(VIDEO)
        dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        primeiro, segundo = gerar_trovoes(dados["semente"], dados["inicio"], dados["inicio"] + 3600)[:2]
        self.relogio.agora = primeiro.instante - 5
        self.chuva.tick()
        (hora_luz, luz), (hora_som, som) = self.relogio.eventos
        self.assertEqual((luz, som), ("luz", "som"))
        self.assertAlmostEqual(hora_luz, primeiro.instante)
        self.assertAlmostEqual(hora_som, primeiro.som)
        self.lampada.relampago.assert_called_once_with(primeiro.flashes)
        self.assertTrue(self.tocar.call_args.args[0].startswith(b"RIFF"))
        # O hub travou e só voltou 10 s depois do segundo trovão: não toca fora de hora.
        self.relogio.agora = segundo.instante + 10
        self.chuva.tick()
        self.assertEqual(self.tocar.call_count, 1)

    def test_parar_fecha_telas_e_encerra_tudo(self) -> None:
        self.chuva.iniciar(VIDEO)
        chave = json.loads(self.caminho.read_text(encoding="utf-8"))["chave"]
        estado = self.chuva.parar("celular")
        self.assertEqual((estado["ativo"], estado["motivo"]), (False, "celular"))
        self.tela.fechar.assert_called_once()
        self.pc.assert_called_with("chuva.parar", "")
        self.assertFalse(self.caminho.exists())
        self.assertFalse(self.chuva.autoriza(chave))
        self.relogio.agora += 3 * CICLO_AR_S
        self.chuva.tick()
        self.ar.executar.assert_not_called()
        self.tocar.assert_not_called()

    def test_retoma_a_mesma_noite_depois_de_reiniciar_o_hub(self) -> None:
        self.chuva.iniciar(VIDEO)
        dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        primeiro = gerar_trovoes(dados["semente"], dados["inicio"], dados["inicio"] + 3600)[0]
        self.relogio.agora = primeiro.instante + 1
        retomado = self.novo()
        self.assertTrue(retomado.ativo)
        self.assertEqual(retomado.estado()["video_id"], "abcdefghijk")
        retomado.tick()
        self.tocar.assert_not_called()
        self.relogio.agora = dados["inicio"] + 17 * 3600
        self.assertFalse(self.novo().ativo)

    def test_estado_lista_os_proximos_trovoes_para_o_celular(self) -> None:
        self.chuva.iniciar(VIDEO)
        self.relogio.agora += ATRASO_INICIO_S
        estado = self.chuva.estado()
        self.assertTrue(estado["trovoes"])
        self.assertTrue(all(t["som"] > estado["agora"] for t in estado["trovoes"]))
        self.assertTrue(all(t["instante"] <= estado["agora"] + 15 * 60 for t in estado["trovoes"]))
        self.assertTrue(estado["ar"]["ligado"])

    def test_trocar_de_video_reabre_as_telas_sem_mandar_o_pc_parar(self) -> None:
        self.chuva.iniciar(VIDEO)
        chave_antiga = json.loads(self.caminho.read_text(encoding="utf-8"))["chave"]
        self.chuva.iniciar("https://youtu.be/zyxwvutsrqp")
        self.assertEqual([chamada.args[0] for chamada in self.pc.call_args_list], ["chuva.iniciar", "chuva.iniciar"])
        self.tela.fechar.assert_not_called()
        self.assertEqual(self.tela.abrir.call_count, 2)
        self.assertFalse(self.chuva.autoriza(chave_antiga))
        self.assertEqual(self.chuva.estado()["video_id"], "zyxwvutsrqp")

    def test_pc_desligado_nao_impede_o_modo(self) -> None:
        self.pc.side_effect = RuntimeError("O PC gamer esta desligado.")
        estado = self.chuva.iniciar(VIDEO)
        self.assertTrue(estado["ativo"])
        self.assertIn("PC fora do modo chuva", self.chuva.estado()["erros"]["pc"])


if __name__ == "__main__":
    unittest.main()
