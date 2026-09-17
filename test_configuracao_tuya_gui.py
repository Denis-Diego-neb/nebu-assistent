import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from configuracao_tuya_gui import (
    DispositivoTuyaDescoberto,
    ErroConfiguracaoTuya,
    carregar_configuracao_inicial,
    criar_configuracao,
    detectar_dispositivos,
    dispositivos_do_snapshot,
    escolher_dispositivo_preferido,
    mensagem_erro_segura,
    salvar_configuracao,
    testar_configuracao,
)


CHAVE = "0123456789abcdef"


class ConfiguracaoInicialTests(unittest.TestCase):
    def test_combina_config_existente_com_campos_ausentes_do_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            pasta = raiz / "dados"
            pasta.mkdir()
            (pasta / "abajur_tuya.json").write_text(
                json.dumps({"local_key": CHAVE, "address": "Auto"}),
                encoding="utf-8",
            )
            snapshot = raiz / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "devices": [
                            {
                                "id": "id-snapshot",
                                "ip": "192.168.1.25",
                                "ver": "3.4",
                                "key": "nao-pode-ser-importada",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = carregar_configuracao_inicial(
                    pasta_dados=pasta,
                    snapshot_path=snapshot,
                )

        self.assertEqual(config.device_id, "id-snapshot")
        self.assertEqual(config.address, "Auto")
        self.assertEqual(config.local_key, CHAVE)
        self.assertEqual(config.version, 3.4)
        self.assertNotIn(CHAVE, repr(config))

    def test_snapshot_nunca_fornece_local_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            snapshot = Path(temporario) / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "devices": [
                            {
                                "id": "id",
                                "ip": "192.168.1.5",
                                "key": CHAVE,
                                "local_key": CHAVE,
                                "token": CHAVE,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            dispositivos = dispositivos_do_snapshot(snapshot)
            with patch.dict(os.environ, {}, clear=True):
                config = carregar_configuracao_inicial(
                    pasta_dados=Path(temporario) / "sem-config",
                    snapshot_path=snapshot,
                )

        self.assertEqual(len(dispositivos), 1)
        self.assertEqual(config.local_key, "")
        self.assertNotIn(CHAVE, repr(dispositivos))


class ValidacaoPersistenciaTests(unittest.TestCase):
    def test_cria_configuracao_com_auto_e_ipv4(self) -> None:
        auto = criar_configuracao(" id ", "auto", "3.5", CHAVE)
        ip = criar_configuracao("id", "192.168.1.8", 3.1, CHAVE)
        self.assertEqual(auto.address, "Auto")
        self.assertEqual(ip.address, "192.168.1.8")

    def test_rejeita_ip_protocolo_e_chave_invalidos_sem_expor_chave(self) -> None:
        with self.assertRaises(ErroConfiguracaoTuya):
            criar_configuracao("id", "lampada.local", 3.5, CHAVE)
        with self.assertRaises(ErroConfiguracaoTuya):
            criar_configuracao("id", "Auto", 3.6, CHAVE)
        chave_ruim = "segredo-curto"
        with self.assertRaises(ErroConfiguracaoTuya) as erro:
            criar_configuracao("id", "Auto", 3.5, chave_ruim)
        self.assertNotIn(chave_ruim, str(erro.exception))

    def test_salva_atomicamente_no_localappdata_nebula(self) -> None:
        config = criar_configuracao("id", "Auto", 3.5, CHAVE)
        with tempfile.TemporaryDirectory() as temporario:
            with patch.dict(os.environ, {"LOCALAPPDATA": temporario}, clear=True):
                caminho = salvar_configuracao(config)
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            temporarios = list(caminho.parent.glob("abajur_tuya.*.tmp"))

        self.assertEqual(caminho, Path(temporario) / "Nebula" / "abajur_tuya.json")
        self.assertEqual(dados["local_key"], CHAVE)
        self.assertEqual(temporarios, [])

    def test_falha_na_troca_atomica_preserva_arquivo_anterior(self) -> None:
        config = criar_configuracao("id-novo", "Auto", 3.5, CHAVE)
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            destino = pasta / "abajur_tuya.json"
            anterior = '{"device_id": "id-anterior"}'
            destino.write_text(anterior, encoding="utf-8")
            with patch(
                "configuracao_tuya_gui.os.replace",
                side_effect=OSError("falha simulada"),
            ):
                with self.assertRaises(ErroConfiguracaoTuya):
                    salvar_configuracao(config, pasta_dados=pasta)
            preservado = destino.read_text(encoding="utf-8")
            temporarios = list(pasta.glob("abajur_tuya.*.tmp"))

        self.assertEqual(preservado, anterior)
        self.assertEqual(temporarios, [])


class DeteccaoETesteTests(unittest.TestCase):
    def test_multiplos_dispositivos_exigem_escolha_salvo_id_ja_conhecido(self) -> None:
        primeiro = DispositivoTuyaDescoberto("id-1", "192.0.2.1", 3.5)
        segundo = DispositivoTuyaDescoberto("id-2", "192.0.2.2", 3.5)
        dispositivos = [primeiro, segundo]
        self.assertIsNone(escolher_dispositivo_preferido(dispositivos))
        self.assertIs(
            escolher_dispositivo_preferido(dispositivos, "id-2"),
            segundo,
        )
        self.assertIs(escolher_dispositivo_preferido([primeiro]), primeiro)

    def test_deteccao_nao_faz_poll_e_descarta_campos_sensiveis(self) -> None:
        class TinyTuyaFalso:
            chamadas: list[dict[str, object]] = []

            @classmethod
            def deviceScan(cls, **opcoes: object) -> dict[str, object]:
                cls.chamadas.append(opcoes)
                print(f"nao registrar {CHAVE}")
                return {
                    "192.168.1.20": {
                        "gwId": "id-detectado",
                        "version": "3.5",
                        "local_key": CHAVE,
                        "key": CHAVE,
                    }
                }

        encontrados = detectar_dispositivos(TinyTuyaFalso)

        self.assertEqual(
            TinyTuyaFalso.chamadas,
            [{"verbose": False, "color": False, "poll": False}],
        )
        self.assertEqual(encontrados[0].device_id, "id-detectado")
        self.assertEqual(encontrados[0].address, "192.168.1.20")
        self.assertNotIn(CHAVE, repr(encontrados))

    def test_teste_executa_somente_status(self) -> None:
        chamadas: list[str] = []

        class ControleFalso:
            def __init__(self, config: object, pasta_dados: Path) -> None:
                chamadas.append("construir")

            def status(self) -> dict[str, object]:
                chamadas.append("status")
                return {"dps": {"20": True, "21": "white"}}

            def turn_on(self) -> None:
                chamadas.append("alterar")

        config = criar_configuracao("id", "Auto", 3.5, CHAVE)
        with tempfile.TemporaryDirectory() as temporario:
            resposta = testar_configuracao(
                config,
                pasta_dados=Path(temporario),
                controle_factory=ControleFalso,
            )

        self.assertEqual(chamadas, ["construir", "status"])
        self.assertIn("dps", resposta)

    def test_mensagem_generica_e_chave_sao_sanitizadas(self) -> None:
        mensagem = mensagem_erro_segura(
            ErroConfiguracaoTuya(f"falha com {CHAVE}"),
            local_key=CHAVE,
        )
        self.assertNotIn(CHAVE, mensagem)
        self.assertIn("chave oculta", mensagem)
        self.assertNotIn(CHAVE, mensagem_erro_segura(RuntimeError(CHAVE), local_key=CHAVE))


if __name__ == "__main__":
    unittest.main()
