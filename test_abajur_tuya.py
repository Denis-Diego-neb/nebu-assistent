from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from abajur_tuya import ConfiguracaoTuya, ControleAbajurTuya, _RitmoTuya
from abajur_wifi import ErroAbajur
from ritmo_navegador import INTENSIDADE_RITMO_PADRAO
from configurar_abajur import _dispositivos_snapshot, _salvar_configuracao


CHAVE_TESTE = "0123456789abcdef"


class BulboFalso:
    instancias: list["BulboFalso"] = []
    proxima_resposta: object | None = None

    def __init__(self, **opcoes: object) -> None:
        self.opcoes = opcoes
        self.eventos: list[object] = []
        self.dps = {
            "20": True,
            "21": "white",
            "22": 650,
            "23": 480,
            "24": "000003e803e8",
            "26": 0,
        }
        self.dpset = {"value_max": 1000}
        self.bulb_configured = False
        self.bulb_type: str | None = None
        self.socket_persistent = bool(opcoes.get("persist", False))
        type(self).instancias.append(self)

    def set_socketPersistent(self, persistir: bool) -> None:
        self.socket_persistent = persistir
        self.eventos.append(("persist", persistir))

    def _resposta(self, alteracoes: dict[str, object] | None = None) -> object:
        if type(self).proxima_resposta is not None:
            resposta = type(self).proxima_resposta
            type(self).proxima_resposta = None
            return resposta
        if alteracoes:
            self.dps.update(alteracoes)
        return {"dps": dict(self.dps)}

    def status(self) -> object:
        self.eventos.append("status")
        self.bulb_configured = True
        self.bulb_type = "B"
        return self._resposta()

    def set_bulb_type(self, tipo: str) -> None:
        self.eventos.append(("tipo", tipo))
        self.bulb_type = tipo
        self.bulb_configured = True

    def turn_on(self) -> object:
        self.eventos.append("turn_on")
        return self._resposta({"20": True})

    def turn_off(self) -> object:
        self.eventos.append("turn_off")
        return self._resposta({"20": False})

    def set_brightness_percentage(self, percentual: int) -> object:
        self.eventos.append(("brilho", percentual))
        return self._resposta({"22": percentual * 10})

    def set_colourtemp_percentage(self, percentual: int) -> object:
        self.eventos.append(("temperatura", percentual))
        return self._resposta({"21": "white", "23": percentual * 10})

    def set_white_percentage(self, brilho: int, temperatura: int) -> object:
        self.eventos.append(("white", brilho, temperatura))
        return self._resposta({"21": "white", "22": brilho * 10, "23": temperatura * 10})

    def set_colour(self, vermelho: int, verde: int, azul: int) -> object:
        self.eventos.append(("rgb", vermelho, verde, azul))
        return self._resposta({"21": "colour"})

    def set_hsv(self, matiz: float, saturacao: float, valor: float) -> object:
        self.eventos.append(("hsv", matiz, saturacao, valor))
        return self._resposta({"21": "colour"})

    def state(self) -> dict[str, object]:
        self.eventos.append("state")
        return {
            "mode": "colour",
            "colour": self.dps["24"],
            "brightness": self.dps["22"],
        }

    def colour_rgb(self, state: dict[str, object] | None = None) -> tuple[int, int, int]:
        self.eventos.append("colour_rgb")
        return 255, 20, 147


class ControleTuyaTest(unittest.TestCase):
    def setUp(self) -> None:
        BulboFalso.instancias.clear()
        BulboFalso.proxima_resposta = None
        self.tinytuya_falso = SimpleNamespace(BulbDevice=BulboFalso)
        self.config = ConfiguracaoTuya(
            device_id="dispositivo-de-teste",
            address="192.0.2.10",
            local_key=CHAVE_TESTE,
            version=3.5,
        )

    def test_ritmo_tuya_inicia_com_sensibilidade_maior(self) -> None:
        controle = ControleAbajurTuya(self.config)
        self.assertEqual(controle._intensidade_ritmo, INTENSIDADE_RITMO_PADRAO)

    def test_ritmo_tuya_usa_vinte_e_cinco_quadros_por_segundo(self) -> None:
        self.assertEqual(_RitmoTuya._QUADROS_POR_SEGUNDO, 25)
        self.assertEqual(_RitmoTuya._INTERVALO, 0.04)

    def test_status_ocorre_antes_do_primeiro_comando(self) -> None:
        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle = ControleAbajurTuya(self.config)
            controle.energia(True)

        bulbo = BulboFalso.instancias[0]
        self.assertEqual(bulbo.eventos[:2], ["status", "turn_on"])
        self.assertEqual(bulbo.bulb_type, "B")
        self.assertEqual(bulbo.opcoes["version"], 3.5)
        self.assertFalse(bulbo.opcoes["persist"])

    def test_comando_comum_nao_reserva_a_lampada_para_nebula(self) -> None:
        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle = ControleAbajurTuya(self.config)
            controle.energia(True)

        bulbo = BulboFalso.instancias[0]
        self.assertFalse(bulbo.socket_persistent)
        self.assertNotIn(("persist", True), bulbo.eventos)

    def test_reconexao_da_animacao_descarta_socket_anterior(self) -> None:
        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle = ControleAbajurTuya(self.config)
            controle.status()
            anterior = controle._dispositivo
            controle._reconectar_animacao()

        self.assertIsNotNone(anterior)
        self.assertIsNot(controle._dispositivo, anterior)
        assert anterior is not None
        self.assertIn(("persist", False), anterior.eventos)
        self.assertTrue(controle._dispositivo.socket_persistent)

    def test_ajuste_relativo_usa_dp_atual_e_limita_faixa(self) -> None:
        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle = ControleAbajurTuya(self.config)
            self.assertEqual(controle.ajustar_brilho(-20), 45)
            self.assertEqual(controle.ajustar_brilho(90), 100)

        bulbo = BulboFalso.instancias[0]
        self.assertIn(("brilho", 45), bulbo.eventos)
        self.assertIn(("brilho", 100), bulbo.eventos)

    def test_temperatura_rgb_e_validacao_de_faixa(self) -> None:
        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle = ControleAbajurTuya(self.config)
            controle.temperatura("quente")
            controle.rgb(255, 20, 147)
            with self.assertRaises(ErroAbajur):
                controle.brilho(0)
            with self.assertRaises(ErroAbajur):
                controle.rgb(256, 0, 0)

        eventos = BulboFalso.instancias[0].eventos
        self.assertIn(("temperatura", 0), eventos)
        self.assertIn(("rgb", 255, 20, 147), eventos)

    def test_brilho_base_do_ritmo_respeita_modo_branco_e_cor(self) -> None:
        controle = ControleAbajurTuya(self.config)
        controle._dispositivo = BulboFalso()
        self.assertEqual(
            controle._brilho_percentual_do_estado(
                {"dps": {"21": "white", "22": 650}}
            ),
            65,
        )
        self.assertEqual(
            controle._brilho_percentual_do_estado(
                {"dps": {"21": "colour", "24": "000003e801f4"}}
            ),
            50,
        )

    def test_ritmo_branco_congela_modo_e_temperatura_sem_alternar_para_cor(self) -> None:
        controle = ControleAbajurTuya(self.config)
        bulbo = BulboFalso()
        controle._dispositivo = bulbo
        estado = {"dps": {"20": True, "21": "white", "22": 10, "23": 170}}

        controle._configurar_perfil_ritmo(estado, None)
        controle._enviar_brilho_ritmo(25)

        self.assertEqual(controle._modo_ritmo, "white")
        self.assertEqual(bulbo.eventos, [("white", 25, 17)])

    def test_ritmo_colorido_congela_matiz_sem_consultar_modo_a_cada_quadro(self) -> None:
        controle = ControleAbajurTuya(self.config)
        bulbo = BulboFalso()
        controle._dispositivo = bulbo
        estado = {"dps": {"20": True, "21": "colour", "24": "000003e803e8"}}

        controle._configurar_perfil_ritmo(estado, None)
        controle._enviar_brilho_ritmo(25)

        self.assertEqual(controle._modo_ritmo, "colour")
        self.assertEqual(bulbo.eventos, [("hsv", 0.0, 1.0, 0.25)])

    def test_restauracao_publica_reaplica_perfil_branco_congelado(self) -> None:
        controle = ControleAbajurTuya(self.config)
        bulbo = BulboFalso()
        controle._dispositivo = bulbo
        estado = {"dps": {"20": True, "21": "white", "22": 420, "23": 730}}

        controle._configurar_perfil_ritmo(estado, None)
        controle.enviar_rgb_animacao(20, 80, 190)
        controle.restaurar_perfil_animacao(42)

        self.assertEqual(bulbo.eventos[-1], ("white", 42, 73))

    def test_erro_tinytuya_e_traduzido_sem_vazar_segredo(self) -> None:
        with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
            controle = ControleAbajurTuya(self.config)
            controle.status()
            BulboFalso.proxima_resposta = {
                "Error": "Check device key or version",
                "Err": "914",
                "Payload": CHAVE_TESTE,
            }
            with self.assertRaises(ErroAbajur) as contexto:
                controle.energia(True)

        self.assertIn("chave local", str(contexto.exception).lower())
        self.assertNotIn(CHAVE_TESTE, str(contexto.exception))

    def test_cores_salvas_sao_compativeis_com_backend_anterior(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            with patch("abajur_tuya.tinytuya", self.tinytuya_falso):
                controle = ControleAbajurTuya(self.config, pasta_dados=pasta)
                self.assertEqual(
                    controle.salvar_cor("neon", "rgb 255 20 147"),
                    "#FF1493",
                )
                controle.usar_cor_salva("neon")
                self.assertEqual(
                    controle.salvar_cor_atual("atual"),
                    "#FF1493",
                )

            dados = json.loads((pasta / "cores_abajur.json").read_text(encoding="utf-8"))
            self.assertEqual(dados, {"neon": "#FF1493", "atual": "#FF1493"})

    @staticmethod
    def _modulos_ritmo_falsos() -> dict[str, object]:
        class MedidorFalso:
            def pico(self) -> float:
                return 0.8

        class MedidorGravesFalso:
            def __init__(self, _quadros_por_segundo: int) -> None:
                pass

            def pico(self) -> float:
                return 0.8

            def fechar(self) -> None:
                pass

        class DetectorFalso:
            def __init__(self, **_opcoes: object) -> None:
                self.amostras = [0.0, 0.8]

            def adicionar(self, _pico: float) -> None:
                pass

            def parece_musica(self) -> bool:
                return True

        return {
            "comtypes": SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None),
            "ritmo_navegador": SimpleNamespace(
                atividade_indica_musica=(
                    lambda indicacao, detector: indicacao is True
                    or detector.parece_musica()
                ),
                DetectorRitmoMusical=DetectorFalso,
                MedidorGravesLoopback=MedidorGravesFalso,
                MedidorNavegador=MedidorFalso,
                # Um título negativo de outra aba não deve vetar o envelope
                # rítmico positivo da sessão que realmente está tocando.
                titulo_navegador_indica_musica=lambda: False,
            ),
        }

    def test_ritmo_tuya_confirma_cor_fixa_e_restaura_ao_parar(self) -> None:
        class ControleRitmoFalso:
            def __init__(self) -> None:
                self.envios_hsv: list[tuple[float, float, float]] = []
                self.envios_brilho: list[int] = []
                self.pulsou = threading.Event()

            def _enviar_hsv_ritmo(self, h: float, s: float, v: float) -> None:
                self.envios_hsv.append((h, s, v))

            def _enviar_brilho_ritmo(self, brilho: int) -> None:
                self.envios_brilho.append(brilho)
                if len(self.envios_brilho) >= 2:
                    self.pulsou.set()

        controle = ControleRitmoFalso()
        ritmo = _RitmoTuya(controle, cor_fixa=(0, 0, 255))  # type: ignore[arg-type]
        ritmo._INTERVALO = 0.001
        with patch.dict(sys.modules, self._modulos_ritmo_falsos()):
            ritmo.iniciar()
            self.assertTrue(controle.pulsou.wait(1))
            ritmo.parar()

        self.assertEqual(controle.envios_hsv, [(2 / 3, 1.0, 1.0)])
        self.assertGreaterEqual(len(controle.envios_brilho), 3)
        self.assertEqual(controle.envios_brilho[0], 100)
        self.assertEqual(controle.envios_brilho[-1], 100)
        self.assertTrue(any(brilho < 100 for brilho in controle.envios_brilho[1:-1]))
        self.assertIsNone(ritmo.erro)

    def test_ritmo_tuya_padrao_pulsa_so_brilho_e_restaura_base(self) -> None:
        class ControleRitmoFalso:
            def __init__(self) -> None:
                self.envios_hsv: list[tuple[float, float, float]] = []
                self.envios_brilho: list[int] = []
                self.pulsou = threading.Event()

            def _enviar_hsv_ritmo(self, h: float, s: float, v: float) -> None:
                self.envios_hsv.append((h, s, v))

            def _enviar_brilho_ritmo(self, brilho: int) -> None:
                self.envios_brilho.append(brilho)
                if len(self.envios_brilho) >= 2:
                    self.pulsou.set()

        controle = ControleRitmoFalso()
        ritmo = _RitmoTuya(  # type: ignore[arg-type]
            controle,
            cor_fixa=None,
            brilho_base=65,
        )
        ritmo._INTERVALO = 0.001
        with patch.dict(sys.modules, self._modulos_ritmo_falsos()):
            ritmo.iniciar()
            self.assertTrue(controle.pulsou.wait(1))
            ritmo.parar()

        self.assertEqual(controle.envios_hsv, [])
        self.assertEqual(controle.envios_brilho[0], 65)
        self.assertEqual(controle.envios_brilho[-1], 65)
        self.assertTrue(any(brilho < 65 for brilho in controle.envios_brilho[1:-1]))

    def test_ritmo_tuya_recupera_um_quadro_perdido_sem_encerrar(self) -> None:
        class ControleInstavel:
            def __init__(self) -> None:
                self.envios = 0
                self.reconexoes = 0
                self.falhou = False
                self.pulsou = threading.Event()
                self.falhas_registradas: list[str] = []

            def _enviar_brilho_ritmo(self, _brilho: int) -> None:
                self.envios += 1
                if self.envios == 2 and not self.falhou:
                    self.falhou = True
                    raise OSError("socket fechado")
                if self.envios >= 3:
                    self.pulsou.set()

            def _reconectar_animacao(self) -> None:
                self.reconexoes += 1

            def _registrar_falha_ritmo(self, etapa: str, _exc: Exception) -> None:
                self.falhas_registradas.append(etapa)

        controle = ControleInstavel()
        ritmo = _RitmoTuya(controle, cor_fixa=None, brilho_base=65)  # type: ignore[arg-type]
        ritmo._INTERVALO = 0.001
        ritmo._intervalo_atual = 0.001
        with patch.dict(sys.modules, self._modulos_ritmo_falsos()):
            ritmo.iniciar()
            self.assertTrue(controle.pulsou.wait(1))
            self.assertTrue(ritmo.ativo)
            ritmo.parar()

        self.assertEqual(controle.reconexoes, 1)
        self.assertIn("quadro perdido", controle.falhas_registradas)
        self.assertIsNone(ritmo.erro)

    def test_ritmo_tuya_sobrevive_a_recriacao_da_sessao_de_audio(self) -> None:
        class MedidorIntermitente:
            instancias = 0

            def __init__(self) -> None:
                type(self).instancias += 1
                self.chamadas = 0

            def pico(self) -> float:
                self.chamadas += 1
                if type(self).instancias == 1 and self.chamadas == 2:
                    raise OSError("sessao WASAPI recriada")
                return 0.8

        class ControleRitmoFalso:
            def __init__(self) -> None:
                self.envios = 0
                self.pulsou = threading.Event()
                self.falhas: list[str] = []

            def _enviar_brilho_ritmo(self, _brilho: int) -> None:
                self.envios += 1
                if self.envios >= 2:
                    self.pulsou.set()

            def _registrar_falha_ritmo(self, etapa: str, _exc: Exception) -> None:
                self.falhas.append(etapa)

        modulos = self._modulos_ritmo_falsos()
        modulos["ritmo_navegador"].MedidorNavegador = MedidorIntermitente
        controle = ControleRitmoFalso()
        ritmo = _RitmoTuya(controle, cor_fixa=None, brilho_base=65)  # type: ignore[arg-type]
        ritmo._INTERVALO = 0.001
        ritmo._intervalo_atual = 0.001
        with patch.dict(sys.modules, modulos):
            ritmo.iniciar()
            self.assertTrue(controle.pulsou.wait(1))
            self.assertTrue(ritmo.ativo)
            ritmo.parar()

        self.assertGreaterEqual(MedidorIntermitente.instancias, 2)
        self.assertIn("medidor do navegador reiniciado", controle.falhas)
        self.assertIsNone(ritmo.erro)

    def test_falha_de_inicio_do_ritmo_tuya_e_sincrona(self) -> None:
        class ControleRitmoFalho:
            def _enviar_hsv_ritmo(self, _h: float, _s: float, _v: float) -> None:
                raise ErroAbajur("falha simulada")

        ritmo = _RitmoTuya(ControleRitmoFalho(), cor_fixa=(255, 0, 0))  # type: ignore[arg-type]
        with (
            patch.dict(sys.modules, self._modulos_ritmo_falsos()),
            self.assertRaises(ErroAbajur) as contexto,
        ):
            ritmo.iniciar()
        self.assertIn("animação local", str(contexto.exception).lower())

    def test_falha_do_medidor_tuya_acontece_antes_de_alterar_lampada(self) -> None:
        class ControleRitmoFalso:
            def __init__(self) -> None:
                self.envios: list[tuple[float, float, float]] = []

            def _enviar_hsv_ritmo(self, h: float, s: float, v: float) -> None:
                self.envios.append((h, s, v))

        class MedidorFalho:
            def pico(self) -> float:
                raise OSError("falha simulada no Core Audio")

        controle = ControleRitmoFalso()
        ritmo = _RitmoTuya(controle, cor_fixa=(255, 0, 0))  # type: ignore[arg-type]
        modulos = self._modulos_ritmo_falsos()
        modulos["ritmo_navegador"].MedidorNavegador = MedidorFalho
        with (
            patch.dict(sys.modules, modulos),
            self.assertRaises(ErroAbajur) as contexto,
        ):
            ritmo.iniciar()

        self.assertIn("animação local", str(contexto.exception).lower())
        self.assertEqual(controle.envios, [])

    def test_ritmo_tuya_faz_preflight_pycaw_antes_de_acessar_lampada(self) -> None:
        controle = ControleAbajurTuya(self.config)
        with (
            patch(
                "abajur_tuya._validar_dependencias_ritmo",
                side_effect=ErroAbajur("A biblioteca pycaw está ausente."),
            ),
            self.assertRaises(ErroAbajur) as contexto,
        ):
            controle.iniciar_ritmo_navegador((255, 0, 0))

        self.assertIn("pycaw", str(contexto.exception).lower())
        self.assertEqual(BulboFalso.instancias, [])
        self.assertIsNone(controle._ritmo_navegador)


class ConfiguracaoTuyaTest(unittest.TestCase):
    def test_arquivo_e_variaveis_de_ambiente(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            (pasta / "abajur_tuya.json").write_text(
                json.dumps(
                    {
                        "device_id": "id-arquivo",
                        "address": "192.0.2.1",
                        "local_key": "aaaaaaaaaaaaaaaa",
                        "version": 3.4,
                    }
                ),
                encoding="utf-8",
            )
            ambiente = {
                "NEBULA_TUYA_DEVICE_ID": "id-env",
                "NEBULA_TUYA_ADDRESS": "Auto",
                "NEBULA_TUYA_LOCAL_KEY": CHAVE_TESTE,
                "NEBULA_TUYA_VERSION": "3.5",
            }
            with patch.dict(os.environ, ambiente, clear=True):
                config = ConfiguracaoTuya.carregar(pasta)

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.device_id, "id-env")
        self.assertEqual(config.address, "Auto")
        self.assertEqual(config.local_key, CHAVE_TESTE)
        self.assertEqual(config.version, 3.5)
        self.assertNotIn(CHAVE_TESTE, repr(config))

    def test_configuracao_sem_chave_preserva_fallback_adb(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            (pasta / "abajur_tuya.json").write_text(
                json.dumps({"device_id": "id", "address": "Auto", "version": 3.5}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(ConfiguracaoTuya.carregar(pasta))

    def test_ausencia_total_de_configuracao_preserva_fallback_adb(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(ConfiguracaoTuya.carregar(Path(temporario)))

    def test_snapshot_ignora_qualquer_chave(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            caminho = Path(temporario) / "snapshot.json"
            caminho.write_text(
                json.dumps(
                    {
                        "devices": [
                            {
                                "id": "id-descoberto",
                                "ip": "192.0.2.20",
                                "ver": 3.5,
                                "key": CHAVE_TESTE,
                                "token": "nao-usar",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            dispositivo = _dispositivos_snapshot(caminho)[0]
        self.assertEqual(
            dispositivo,
            {
                "device_id": "id-descoberto",
                "address": "192.0.2.20",
                "version": 3.5,
            },
        )

    def test_configurador_salva_fora_do_repositorio(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario) / "Nebula"
            config = ConfiguracaoTuya("id", "Auto", CHAVE_TESTE, 3.5)
            caminho = _salvar_configuracao(config, pasta)
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(caminho.name, "abajur_tuya.json")
        self.assertEqual(dados["local_key"], CHAVE_TESTE)

    def test_configurador_faz_apenas_consulta_de_status(self) -> None:
        chamadas: list[str] = []

        class ControleFalso:
            def __init__(self, config: ConfiguracaoTuya, pasta_dados: Path) -> None:
                chamadas.append("construir")

            def status(self) -> dict[str, object]:
                chamadas.append("status")
                return {"dps": {"20": True, "21": "white"}}

        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario) / "Nebula"
            with (
                patch("configurar_abajur.pasta_dados_nebula", return_value=pasta),
                patch("configurar_abajur._dispositivos_snapshot", return_value=[]),
                patch("builtins.input", side_effect=["id-manual", "", ""]),
                patch("configurar_abajur.getpass", return_value=CHAVE_TESTE),
                patch("configurar_abajur.ControleAbajurTuya", ControleFalso),
                patch("builtins.print") as imprimir,
            ):
                from configurar_abajur import main

                resultado = main()

        self.assertEqual(resultado, 0)
        self.assertEqual(chamadas, ["construir", "status"])
        saida = " ".join(
            str(argumento)
            for chamada in imprimir.call_args_list
            for argumento in chamada.args
        )
        self.assertNotIn(CHAVE_TESTE, saida)


if __name__ == "__main__":
    unittest.main()
