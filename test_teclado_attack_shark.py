import unittest

from teclado_attack_shark import (
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
    def test_boost_usa_modo_dinamico_e_restaura_perfil(self) -> None:
        backend = BackendFalso()
        teclado = AttackSharkX98HE(hid_backend=backend)
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
        backend = BackendFalso()
        teclado = AttackSharkX98HE(hid_backend=backend)
        envios = backend.dispositivo.envios
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
        backend = BackendFalso()
        teclado = AttackSharkX98HE(hid_backend=backend)
        teclado.definir_cor_base((10, 210, 245))
        teclado.set_boost(100)
        self.assertEqual(backend.dispositivo.envios[-1][4], 5)
        teclado.close()

    def test_recusa_dispositivo_de_familia_desconhecida(self) -> None:
        backend = BackendFalso(device_id=9999)
        with self.assertRaises(AttackSharkProtocolError):
            AttackSharkX98HE(hid_backend=backend)
        self.assertFalse(backend.dispositivo.aberto)


if __name__ == "__main__":
    unittest.main()
