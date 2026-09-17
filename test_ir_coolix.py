import base64
import struct
import unittest
from ir_coolix import decode, supports_temperature, temperature_code


def captured_frame():
    # Quadro capturado do controle fisico, ligado/frio/17 C.
    frame = bytes.fromhex('b24d5fa000ff')
    pulses = []
    for gap in (5220, 64464):
        pulses.extend((4367, 4367))
        for byte in frame:
            for bit in range(7, -1, -1):
                pulses.extend((536, 1618 if byte & (1 << bit) else 536))
        pulses.extend((536, gap))
    return base64.b64encode(struct.pack('<200H', *pulses)).decode()


class CoolixTests(unittest.TestCase):
    def test_temperatura_preserva_modo_fan_e_paridade(self):
        code = captured_frame()
        for temperature, expected in ((17, 'b24d5fa000ff'), (18, 'b24d5fa010ef'), (24, 'b24d5fa040bf'), (30, 'b24d5fa0b04f')):
            with self.subTest(temperature=temperature):
                updated = temperature_code(code, temperature)
                self.assertEqual(bytes(decode(updated)[1]).hex(), expected)

    def test_recusa_sinais_desconhecidos_e_limites(self):
        for code in (None, '', 'AQACAAMA', '%%%%'):
            self.assertFalse(supports_temperature(code))
        for value in (16, 31, True, '18'):
            with self.assertRaises(ValueError):
                temperature_code(captured_frame(), value)


if __name__ == '__main__':
    unittest.main()
