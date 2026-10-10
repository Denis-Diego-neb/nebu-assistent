import unittest

from device_presets import KEYBOARD_EFFECTS
from teclado_attack_shark import (
    AttackSharkError,
    AttackSharkProtocolError,
    AttackSharkX98HE,
    MODE_STATIC,
    OP_GET_LED,
    OP_IDENTIFY,
    OP_SET_LED,
)


class DispositivoFalso:
    def __init__(self, device_id: int = 2964) -> None:
        self.device_id = device_id
        self.aberto = False
        self.pendente = 0
        self.envios = []
        self.led = bytes([OP_GET_LED, 5, 2, 4, 8, 255, 0, 123]) + bytes(56)

    def open_path(self, _path) -> None:
        self.aberto = True

    def send_feature_report(self, report: bytes) -> int:
        pacote = report[1:]
        self.envios.append(pacote)
        self.pendente = pacote[0]
        if pacote[0] == OP_SET_LED:
            self.led = bytes([OP_GET_LED]) + pacote[1:8] + bytes(56)
        return len(report)

    def get_feature_report(self, _report_id: int, _size: int) -> bytes:
        if self.pendente == OP_IDENTIFY:
            resposta = bytes([OP_IDENTIFY]) + self.device_id.to_bytes(4, "little") + bytes(59)
        else:
            resposta = self.led
        return bytes([0]) + resposta

    def close(self) -> None:
        self.aberto = False


class BackendFalso:
    def __init__(self, device_id: int = 2964) -> None:
        self.dispositivo = DispositivoFalso(device_id)

    def enumerate(self, _vid: int, pid: int):
        if pid != 0x5029:
            return []
        return [{"path": b"fake", "usage_page": 0xFFFF, "usage": 2}]

    def device(self):
        return self.dispositivo


class AttackSharkTests(unittest.TestCase):
    def abrir(self) -> tuple[AttackSharkX98HE, list[bytes]]:
        backend = BackendFalso()
        teclado = AttackSharkX98HE(hid_backend=backend)
        self.addCleanup(teclado.close)
        return teclado, backend.dispositivo.envios

    def test_boost_usa_modo_dinamico_e_restaura_perfil(self) -> None:
        backend = BackendFalso()
        teclado = AttackSharkX98HE(hid_backend=backend)
        self.addCleanup(teclado.close)
        original = backend.dispositivo.led[1:8]

        teclado.set_boost(50)
        dinamico = backend.dispositivo.envios[-1]
        self.assertEqual(dinamico[0], OP_SET_LED)
        self.assertEqual(dinamico[1], MODE_STATIC)
        self.assertEqual(dinamico[3], 2)
        self.assertEqual(dinamico[4], 0)
        self.assertEqual(dinamico[5:8], bytes([255, 255, 255]))
        self.assertEqual(dinamico[8], (0xFF - sum(dinamico[:8])) & 0xFF)

        teclado.close()
        restauracao = backend.dispositivo.envios[-1]
        self.assertEqual(restauracao[0], OP_SET_LED)
        self.assertEqual(restauracao[1:8], original)
        self.assertFalse(backend.dispositivo.aberto)

    def test_ambilight_escolhe_cor_pronta_e_so_envia_quando_muda(self) -> None:
        teclado, envios = self.abrir()
        antes = len(envios)
        teclado.enviar_rgb(20, 30, 90)        # chuva escura e azulada
        self.assertEqual(envios[-1][3:5], bytes([2, 2]))  # nível 2, preset azul
        teclado.enviar_rgb(22, 31, 92)        # quadro quase igual: nada vai ao teclado
        self.assertEqual(len(envios), antes + 1)
        teclado.enviar_rgb(250, 240, 20)      # relâmpago amarelado na tela
        self.assertEqual(envios[-1][3:5], bytes([4, 3]))
        teclado.enviar_rgb(0, 0, 0)
        self.assertEqual(envios[-1][3], 1)
        with self.assertRaises(ValueError):
            teclado.enviar_rgb(300, 0, 0)

    def test_cor_base_escolhe_preset_real_do_firmware(self) -> None:
        teclado, envios = self.abrir()
        teclado.definir_cor_base((10, 210, 245))
        teclado.set_boost(100)
        self.assertEqual(envios[-1][4], 5)

    def test_ambilight_nao_pisca_na_divisa_entre_cores_nem_entre_niveis(self) -> None:
        teclado, envios = self.abrir()
        teclado.enviar_rgb(0, 0, 255)
        antes = len(envios)
        for _ in range(3):  # cena entre o azul e o ciano
            teclado.enviar_rgb(0, 112, 255)
            teclado.enviar_rgb(0, 104, 255)
        self.assertEqual(len(envios), antes)
        teclado.enviar_rgb(0, 200, 255)
        self.assertEqual(envios[-1][3:5], bytes([4, 5]))

        teclado.enviar_rgb(0, 0, 128)  # 50%: nível 2
        antes = len(envios)
        for _ in range(3):  # brilho oscilando em volta da divisa dos 50%
            teclado.enviar_rgb(0, 0, 135)
            teclado.enviar_rgb(0, 0, 125)
        self.assertEqual(len(envios), antes)
        teclado.enviar_rgb(0, 0, 145)
        self.assertEqual(envios[-1][3], 3)

    def test_cena_quase_preta_so_baixa_o_brilho(self) -> None:
        teclado, envios = self.abrir()
        teclado.enviar_rgb(0, 0, 200)
        teclado.enviar_rgb(20, 4, 3)  # ruído avermelhado numa cena escura
        self.assertEqual(envios[-1][3:5], bytes([1, 2]))

    def test_flash_de_escapamento_volta_para_a_cor_do_boost(self) -> None:
        teclado, envios = self.abrir()
        teclado.definir_cor_base((0, 80, 255))
        teclado.set_boost(80)
        self.assertEqual(envios[-1][3:5], bytes([4, 2]))
        teclado.enviar_rgb(255, 195, 45)
        self.assertEqual(envios[-1][4], 3)
        teclado.set_boost(80)
        self.assertEqual(envios[-1][3:5], bytes([4, 2]))

    def test_efeitos_do_firmware_cobrem_os_do_kumara(self) -> None:
        self.assertEqual(set(AttackSharkX98HE.efeitos_nativos()), set(KEYBOARD_EFFECTS) - {"static"})
        teclado, envios = self.abrir()
        teclado.efeito_nativo("respirar", (255, 0, 120))
        self.assertEqual(envios[-1][:8], bytes([OP_SET_LED, 2, 2, 4, 0, 255, 255, 255]))
        self.assertEqual(envios[-1][8], (0xFF - sum(envios[-1][:8])) & 0xFF)
        antes = len(envios)
        teclado.efeito_nativo("respirar", (255, 0, 120))
        self.assertEqual(len(envios), antes)
        teclado.efeito_nativo("arco_iris_vertical", (0, 80, 255))
        self.assertEqual(envios[-1][:8], bytes([OP_SET_LED, 4, 2, 4, 0x27, 0, 80, 255]))
        teclado.efeito_nativo("onda_curta", (255, 255, 255))
        self.assertEqual(envios[-1][1:8], bytes([4, 0, 4, 7, 250, 250, 250]))
        teclado.enviar_rgb(0, 0, 255)  # depois do efeito, a cor fixa volta ao estático
        self.assertEqual(envios[-1][1], MODE_STATIC)
        with self.assertRaises(ValueError):
            teclado.efeito_nativo("static", (255, 0, 0))

    def test_fechar_depois_de_um_efeito_restaura_o_perfil(self) -> None:
        backend = BackendFalso()
        original = backend.dispositivo.led[1:8]
        teclado = AttackSharkX98HE(hid_backend=backend)
        teclado.efeito_nativo("estrelas", (0, 255, 0))
        teclado.close()
        self.assertEqual(backend.dispositivo.envios[-1][1:8], original)
        self.assertFalse(backend.dispositivo.aberto)

    def test_um_efeito_por_vez_no_teclado(self) -> None:
        primeiro = AttackSharkX98HE(hid_backend=BackendFalso())
        try:
            with self.assertRaises(AttackSharkError):
                AttackSharkX98HE(hid_backend=BackendFalso())
        finally:
            primeiro.close()
        with self.assertRaises(AttackSharkProtocolError):
            AttackSharkX98HE(hid_backend=BackendFalso(device_id=9999))
        segundo, _envios = self.abrir()  # a falha acima não deixou o teclado preso
        self.assertTrue(segundo.is_open)

    def test_recusa_dispositivo_de_familia_desconhecida(self) -> None:
        backend = BackendFalso(device_id=9999)
        with self.assertRaises(AttackSharkProtocolError):
            AttackSharkX98HE(hid_backend=backend)
        self.assertFalse(backend.dispositivo.aberto)


if __name__ == "__main__":
    unittest.main()
