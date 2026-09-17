import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from abajur_wifi import (
    ComandoAbajur,
    ControleAbajurElgin,
    ErroAbajur,
    interpretar_comando_abajur,
    interpretar_comandos_abajur,
    resolver_cor,
)
from main import Nebula, comando_de_clipe, extrair_chamada
from ritmo_navegador import DetectorRitmoMusical, TITULOS_FALA


class InterpretacaoAbajurTest(unittest.TestCase):
    def test_ligar_e_desligar(self) -> None:
        self.assertEqual(interpretar_comando_abajur("ligue o abajur"), ComandoAbajur("energia", True))
        self.assertEqual(interpretar_comando_abajur("apague a luz"), ComandoAbajur("energia", False))

    def test_cor_tem_precedencia_sobre_ligar(self) -> None:
        self.assertEqual(
            interpretar_comando_abajur("acenda a lampada azul"),
            ComandoAbajur("cor", "azul"),
        )

    def test_paleta_ampliada_inclui_rosa_avermelhado(self) -> None:
        self.assertEqual(resolver_cor("rosa avermelhado"), (199, 21, 133))
        self.assertEqual(resolver_cor("magenta"), (255, 0, 170))
        self.assertEqual(
            interpretar_comando_abajur("deixe o abajur rosa avermelhado"),
            ComandoAbajur("cor", "rosa avermelhado"),
        )

    def test_temperatura_e_brilho(self) -> None:
        self.assertEqual(interpretar_comando_abajur("deixe a luz quente"), ComandoAbajur("temperatura", "quente"))
        self.assertEqual(
            interpretar_comando_abajur("coloque o brilho do abajur em 40 por cento"),
            ComandoAbajur("brilho", 40),
        )

    def test_percentual_com_simbolo_e_comando_composto(self) -> None:
        self.assertEqual(
            interpretar_comandos_abajur(
                "mude a temperatura da luz para mais baixa e diminua o brilho 20%"
            ),
            [
                ComandoAbajur("temperatura", "quente"),
                ComandoAbajur("brilho_relativo", -20),
            ],
        )
        self.assertEqual(
            interpretar_comandos_abajur(
                "deixe a luz fria e coloque o brilho em 20%"
            ),
            [
                ComandoAbajur("temperatura", "fria"),
                ComandoAbajur("brilho", 20),
            ],
        )
        self.assertEqual(
            interpretar_comandos_abajur("diminua o brilho da luz em 20%"),
            [ComandoAbajur("brilho_relativo", -20)],
        )
        self.assertEqual(
            interpretar_comandos_abajur("diminua o brilho da luz para 20%"),
            [ComandoAbajur("brilho", 20)],
        )

    def test_ignora_outros_dispositivos(self) -> None:
        self.assertIsNone(interpretar_comando_abajur("ligue o computador"))

    def test_musica_rgb_e_cor_salva(self) -> None:
        self.assertEqual(
            interpretar_comando_abajur("ative o modo musica do abajur"),
            ComandoAbajur("musica_pc"),
        )
        self.assertEqual(
            interpretar_comando_abajur("modo ritmo"),
            ComandoAbajur("musica_pc"),
        )
        self.assertEqual(
            interpretar_comando_abajur("modo ritimo em 90% de intensidade"),
            ComandoAbajur("intensidade_ritmo", 90),
        )
        self.assertEqual(
            interpretar_comando_abajur("faca o abajur piscar azul com a musica"),
            ComandoAbajur("musica_pc", (0, 0, 255)),
        )
        self.assertEqual(
            interpretar_comando_abajur("modo musica do abajur rgb 255 20 147"),
            ComandoAbajur("musica_pc", (255, 20, 147)),
        )
        self.assertEqual(
            interpretar_comando_abajur("deixe o abajur rgb 255 20 147"),
            ComandoAbajur("rgb", (255, 20, 147)),
        )
        self.assertEqual(
            interpretar_comando_abajur("salve a cor rgb 255 20 147 como neon"),
            ComandoAbajur("salvar_cor", ("rgb 255 20 147", "neon")),
        )
        self.assertEqual(
            interpretar_comando_abajur("use a cor salva neon no abajur"),
            ComandoAbajur("usar_cor_salva", "neon"),
        )

    def test_salva_cor_em_disco(self) -> None:
        with TemporaryDirectory() as pasta:
            controle = ControleAbajurElgin(adb="adb-falso", pasta_dados=Path(pasta))
            self.assertEqual(controle.salvar_cor("neon", "rgb 255 20 147"), "#FF1493")
            self.assertEqual(controle._carregar_cores(), {"neon": "#FF1493"})
        self.assertEqual(resolver_cor("hex 00ffaa"), (0, 255, 170))

    def test_comando_salva_cor_atual(self) -> None:
        self.assertEqual(
            interpretar_comando_abajur("salve a cor atual como por do sol"),
            ComandoAbajur("salvar_cor_atual", "por do sol"),
        )
        self.assertEqual(
            interpretar_comando_abajur("salve essa cor como gamer"),
            ComandoAbajur("salvar_cor_atual", "gamer"),
        )

    def test_ajuste_relativo_de_brilho_adb(self) -> None:
        controle = ControleAbajurElgin(adb="adb-falso")
        with (
            patch.object(controle, "_brilho_atual", return_value=50),
            patch.object(controle, "brilho") as aplicar,
        ):
            novo = controle.ajustar_brilho(-20)
        self.assertEqual(novo, 30)
        aplicar.assert_called_once_with(30)

    def test_brilho_composto_preserva_modo_branco(self) -> None:
        controle = ControleAbajurElgin(adb="adb-falso")
        controle._modo_ativo = "white"
        with (
            patch.object(controle, "_preparar"),
            patch.object(controle, "_abrir_painel"),
            patch.object(controle, "_toque") as toque,
            patch("abajur_wifi.time.sleep"),
        ):
            controle.brilho(30)
        self.assertEqual(toque.call_args_list, [call(220, 305), call(404, 1645)])

    def test_le_brilho_no_primeiro_percentual_do_status(self) -> None:
        self.assertEqual(
            ControleAbajurElgin._extrair_brilho_status("ON 100% 48% 0s"),
            100,
        )

    def test_apenas_nebu_ativa(self) -> None:
        self.assertEqual(extrair_chamada("Nebu, ligue o abajur"), (True, "ligue o abajur"))
        self.assertEqual(extrair_chamada("Nébú, luz azul"), (True, "luz azul"))
        self.assertEqual(extrair_chamada("Nebula, ligue o abajur"), (False, "nebula, ligue o abajur"))

    def test_detector_recusa_silencio_e_aceita_pulso_regular(self) -> None:
        silencio = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
        musica = DetectorRitmoMusical(amostras_por_segundo=10, segundos=6)
        for indice in range(60):
            silencio.adicionar(0)
            fase = indice % 5
            musica.adicionar(0.75 * math.exp(-fase / 1.4) + 0.02)
        self.assertFalse(silencio.parece_musica())
        self.assertTrue(musica.parece_musica())
        self.assertIn("whatsapp", TITULOS_FALA)
        self.assertIn("discord", TITULOS_FALA)

    def test_clipe_curto_e_variacoes_do_microfone(self) -> None:
        for frase in ("clipe", "clip", "clipa", "clipe isso", "clipe agora", "clipee"):
            with self.subTest(frase=frase):
                self.assertTrue(comando_de_clipe(frase))
        self.assertFalse(comando_de_clipe("minha equipe ganhou"))
        self.assertFalse(comando_de_clipe("abra um videoclipe no youtube"))

    def test_clipe_chega_ao_atalho_nvidia(self) -> None:
        class SaidaTeste:
            def falar(self, _texto: str) -> None:
                pass

        with patch("main.salvar_replay_nvidia") as salvar:
            self.assertTrue(Nebula(SaidaTeste(), abrir_navegador=False).executar("clipe"))
            salvar.assert_called_once_with()

    def test_nebula_executa_todas_as_acoes_do_abajur_em_ordem(self) -> None:
        class SaidaTeste:
            mensagens: list[str] = []

            def falar(self, texto: str) -> None:
                self.mensagens.append(texto)

        class ControleTeste:
            chamadas: list[tuple[str, object]] = []

            def temperatura(self, valor: str) -> None:
                self.chamadas.append(("temperatura", valor))

            def ajustar_brilho(self, valor: int) -> int:
                self.chamadas.append(("brilho_relativo", valor))
                return 35

        saida = SaidaTeste()
        controle = ControleTeste()
        nebula = Nebula(saida, abrir_navegador=False)
        nebula._controle_abajur = controle  # type: ignore[assignment]

        self.assertTrue(nebula.executar(
            "mude a temperatura da luz para mais baixa e diminua o brilho 20%"
        ))
        self.assertEqual(
            controle.chamadas,
            [("temperatura", "quente"), ("brilho_relativo", -20)],
        )
        self.assertIn("agora em 35 por cento", saida.mensagens[-1])

    def test_novo_ritmo_adb_substitui_cor_da_thread_anterior(self) -> None:
        class RitmoAnterior:
            erro = None

            def __init__(self) -> None:
                self.parado = False

            def parar(self) -> None:
                self.parado = True

        class RitmoNovo:
            instancias: list["RitmoNovo"] = []

            def __init__(self, _controle: object, cor_fixa: object = None) -> None:
                self.cor_fixa = cor_fixa
                self.erro = None
                self.ativo = False
                type(self).instancias.append(self)

            def iniciar(self) -> None:
                self.ativo = True

            def parar(self) -> None:
                self.ativo = False

        controle = ControleAbajurElgin(adb="adb-falso")
        anterior = RitmoAnterior()
        controle._ritmo_navegador = anterior
        with (
            patch("abajur_wifi._validar_dependencias_ritmo"),
            patch.object(controle, "_preparar"),
            patch("ritmo_navegador.RitmoNavegador", RitmoNovo),
            patch("abajur_wifi.time.sleep"),
        ):
            controle.iniciar_ritmo_navegador((0, 0, 255))

        self.assertTrue(anterior.parado)
        self.assertEqual(RitmoNovo.instancias[0].cor_fixa, (0, 0, 255))
        self.assertIs(controle._ritmo_navegador, RitmoNovo.instancias[0])

    def test_falha_imediata_da_thread_adb_nao_e_confirmada(self) -> None:
        class RitmoFalho:
            def __init__(self, _controle: object, cor_fixa: object = None) -> None:
                self.erro = "falha interna"
                self.ativo = False

            def iniciar(self) -> None:
                pass

            def parar(self) -> None:
                pass

        controle = ControleAbajurElgin(adb="adb-falso")
        with (
            patch("abajur_wifi._validar_dependencias_ritmo"),
            patch.object(controle, "_preparar"),
            patch("ritmo_navegador.RitmoNavegador", RitmoFalho),
            patch("abajur_wifi.time.sleep"),
            self.assertRaises(ErroAbajur),
        ):
            controle.iniciar_ritmo_navegador((255, 20, 147))
        self.assertIsNone(controle._ritmo_navegador)

    def test_falha_do_handshake_adb_e_convertida(self) -> None:
        class RitmoFalho:
            erro = None
            ativo = False

            def __init__(self, _controle: object, cor_fixa: object = None) -> None:
                pass

            def iniciar(self) -> None:
                raise RuntimeError("Falha clara do handshake.")

            def parar(self) -> None:
                pass

        controle = ControleAbajurElgin(adb="adb-falso")
        controle._modo_ativo = "color"
        with (
            patch("abajur_wifi._validar_dependencias_ritmo"),
            patch.object(controle, "_preparar"),
            patch("ritmo_navegador.RitmoNavegador", RitmoFalho),
            self.assertRaises(ErroAbajur) as contexto,
        ):
            controle.iniciar_ritmo_navegador()

        self.assertEqual(str(contexto.exception), "Falha clara do handshake.")
        self.assertIsNone(controle._ritmo_navegador)

    def test_ritmo_adb_falha_clara_quando_pycaw_nao_foi_incluido(self) -> None:
        controle = ControleAbajurElgin(adb="adb-falso")
        with (
            patch(
                "abajur_wifi.importlib.import_module",
                side_effect=ModuleNotFoundError("pycaw ausente"),
            ),
            patch.object(controle, "_preparar") as preparar,
            self.assertRaises(ErroAbajur) as contexto,
        ):
            controle.iniciar_ritmo_navegador()

        self.assertIn("pycaw", str(contexto.exception).lower())
        preparar.assert_not_called()
        self.assertIsNone(controle._ritmo_navegador)


if __name__ == "__main__":
    unittest.main()
