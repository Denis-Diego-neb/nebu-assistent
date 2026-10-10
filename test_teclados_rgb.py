import unittest
from unittest.mock import Mock

from teclado_attack_shark import AttackSharkError, AttackSharkNotFoundError
from teclado_openrgb import OpenRGBKeyboardError
from teclados_rgb import TecladoIndisponivel, TecladosRGB, abrir_teclados


class TecladoFalso:
    def __init__(self, nome: str | None = None, *, zonas: bool = False, nativo: bool = True) -> None:
        if nome:
            self.nome = nome
        self.ambilight_multizona_seguro = zonas
        self.chamadas: list[tuple] = []
        self.falha: Exception | None = None
        self.falha_ao_fechar: Exception | None = None
        self.fechado = False
        if nativo:
            self.efeito_nativo = lambda efeito, cor: self._registrar("efeito_nativo", efeito, cor)

    def _registrar(self, *chamada) -> None:
        if self.falha is not None:
            raise self.falha
        self.chamadas.append(chamada)

    def enviar_rgb(self, *rgb) -> None:
        self._registrar("enviar_rgb", *rgb)

    def enviar_zonas(self, cores) -> None:
        self._registrar("enviar_zonas", cores)

    def definir_cor_base(self, cor) -> None:
        self._registrar("definir_cor_base", cor)

    def set_boost(self, brilho) -> None:
        self._registrar("set_boost", brilho)

    def restaurar(self) -> None:
        self._registrar("restaurar")

    def close(self) -> None:
        self.fechado = True
        if self.falha_ao_fechar is not None:
            raise self.falha_ao_fechar


class TecladosRGBTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kumara = TecladoFalso(zonas=True)
        self.shark = TecladoFalso("Attack Shark")
        self.grupo = TecladosRGB([self.kumara, self.shark])

    def test_repassa_os_comandos_aos_dois_teclados(self) -> None:
        self.assertEqual(self.grupo.nome, "Kumara e Attack Shark")
        self.grupo.definir_cor_base((0, 80, 255))
        self.grupo.set_boost(60)
        self.grupo.enviar_rgb(10, 20, 30)
        self.grupo.restaurar()
        esperado = [("definir_cor_base", (0, 80, 255)), ("set_boost", 60),
                    ("enviar_rgb", 10, 20, 30), ("restaurar",)]
        self.assertEqual(self.kumara.chamadas, esperado)
        self.assertEqual(self.shark.chamadas, esperado)
        self.grupo.close()
        self.assertTrue(self.kumara.fechado and self.shark.fechado)

    def test_zonas_viram_a_media_no_teclado_sem_zonas(self) -> None:
        self.assertTrue(self.grupo.ambilight_multizona_seguro)
        self.grupo.enviar_zonas([(0, 0, 90), (30, 60, 0), (0, 30, 0)])
        self.assertEqual(self.kumara.chamadas, [("enviar_zonas", ((0, 0, 90), (30, 60, 0), (0, 30, 0)))])
        self.assertEqual(self.shark.chamadas, [("enviar_rgb", 10, 30, 30)])
        self.assertFalse(TecladosRGB([self.shark]).ambilight_multizona_seguro)
        with self.assertRaises(ValueError):
            self.grupo.enviar_zonas([])

    def test_quem_nao_tem_efeito_do_firmware_fica_na_cor_escolhida(self) -> None:
        openrgb = TecladoFalso(nativo=False)
        grupo = TecladosRGB([openrgb, self.shark])
        grupo.efeito_nativo("respirar", (255, 0, 120))
        self.assertEqual(openrgb.chamadas, [("enviar_rgb", 255, 0, 120)])
        self.assertEqual(self.shark.chamadas, [("efeito_nativo", "respirar", (255, 0, 120))])
        with self.assertRaises(TecladoIndisponivel):
            TecladosRGB([TecladoFalso(nativo=False)]).efeito_nativo("onda", (0, 80, 255))

    def test_teclado_que_falha_sai_do_grupo_e_o_outro_continua(self) -> None:
        self.kumara.falha = OpenRGBKeyboardError("O Kumara perdeu a conexao USB.")
        self.grupo.enviar_rgb(1, 2, 3)
        self.assertTrue(self.kumara.fechado)
        self.assertEqual(self.grupo.nome, "Attack Shark")
        self.assertEqual(self.shark.chamadas, [("enviar_rgb", 1, 2, 3)])
        self.assertIn("Kumara", self.grupo.erros[0])
        self.shark.falha = AttackSharkError("O teclado aceitou apenas 0 de 65 bytes.")
        with self.assertRaises(TecladoIndisponivel) as erro:
            self.grupo.set_boost(50)
        # Os modos tratam os dois tipos de erro de teclado; este é dos dois.
        self.assertIsInstance(erro.exception, OpenRGBKeyboardError)
        self.assertIsInstance(erro.exception, AttackSharkError)
        self.assertTrue(self.shark.fechado)

    def test_valor_invalido_nao_tira_ninguem_do_grupo(self) -> None:
        self.kumara.falha = ValueError("A cor do teclado precisa ser um RGB valido.")
        with self.assertRaises(ValueError):
            self.grupo.enviar_rgb(300, 0, 0)
        self.assertEqual(self.grupo.nome, "Kumara e Attack Shark")
        self.assertFalse(self.kumara.fechado)

    def test_fechar_restaura_todos_mesmo_se_um_falhar(self) -> None:
        self.kumara.falha_ao_fechar = OpenRGBKeyboardError("O Kumara perdeu a conexao USB.")
        self.grupo.close()
        self.assertTrue(self.shark.fechado)
        self.grupo.close()
        with self.assertRaises(TecladoIndisponivel):
            self.grupo.enviar_rgb(1, 2, 3)


class AbrirTecladosTests(unittest.TestCase):
    def test_abre_os_dois_sem_iniciar_o_openrgb(self) -> None:
        kumara, shark = TecladoFalso(zonas=True), TecladoFalso("Attack Shark")
        fabrica_kumara = Mock(return_value=kumara)
        grupo = abrir_teclados(lambda: shark, fabrica_kumara)
        self.assertEqual(grupo.nomes, ("Kumara", "Attack Shark"))
        fabrica_kumara.assert_called_once_with(iniciar_openrgb=False)

    def test_sem_attack_shark_procura_o_kumara_como_antes(self) -> None:
        kumara = TecladoFalso(zonas=True)
        fabrica_kumara = Mock(return_value=kumara)
        nao_achou = Mock(side_effect=AttackSharkNotFoundError("Nao encontrei o Attack Shark X98HE."))
        grupo = abrir_teclados(nao_achou, fabrica_kumara)
        self.assertEqual(grupo.nomes, ("Kumara",))
        fabrica_kumara.assert_called_once_with(iniciar_openrgb=True)

    def test_so_o_attack_shark(self) -> None:
        shark = TecladoFalso("Attack Shark")
        grupo = abrir_teclados(lambda: shark, Mock(side_effect=OpenRGBKeyboardError("O Kumara nao esta conectado.")))
        self.assertEqual(grupo.nome, "Attack Shark")

    def test_nenhum_teclado_explica_os_dois_motivos(self) -> None:
        with self.assertRaises(TecladoIndisponivel) as erro:
            abrir_teclados(
                Mock(side_effect=AttackSharkNotFoundError("Nao encontrei o Attack Shark X98HE.")),
                Mock(side_effect=OpenRGBKeyboardError("OpenRGB nao esta instalado.")),
            )
        self.assertIn("Attack Shark", str(erro.exception))
        self.assertIn("OpenRGB", str(erro.exception))

    def test_erro_inesperado_solta_o_attack_shark(self) -> None:
        shark = TecladoFalso("Attack Shark")
        with self.assertRaises(ImportError):
            abrir_teclados(lambda: shark, Mock(side_effect=ImportError("psutil")))
        self.assertTrue(shark.fechado)


if __name__ == "__main__":
    unittest.main()
