import unittest
from unittest.mock import patch

from teclado_evision import ErroKumaraUSB, TecladoKumaraUSB, colunas_kumara, pacote_evision


class USBFalso:
    def __init__(self):
        self.writes = []
        self.pending = []
        self.drop_offset = None
        self.closed = False

    def write(self, packet):
        self.writes.append(packet)
        offset = int.from_bytes(packet[5:7], 'little')
        if (packet[3] == 17 or (packet[3] == 6 and offset == 5)) and offset != self.drop_offset:
            self.pending.append(packet)
        return len(packet)

    def read(self, size, timeout):
        return self.pending.pop(0) if self.pending else []

    def close(self):
        self.closed = True


class KumaraUSBTests(unittest.TestCase):
    def setUp(self):
        self.usb = USBFalso()
        self.keyboard = TecladoKumaraUSB({}, device=self.usb)
        self.addCleanup(self.keyboard.close)
        sleeper = patch('teclado_evision.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def frame(self):
        packets = [p for p in self.usb.writes if p[3] == 17][-7:]
        return b''.join(p[8:8+p[4]] for p in packets)

    def test_checksum_confere_com_resposta_capturada_no_hardware(self):
        packet = pacote_evision(17, bytes([0,255,0])*18, 162)
        self.assertEqual(packet[:12].hex(), '04d7ff1136a2000000ff0000')

    def test_modo_sem_resposta_nao_impede_sete_blocos_verdes(self):
        self.keyboard.enviar_zonas([(0,255,0)]*3)
        self.assertEqual(self.frame(), bytes([0,255,0])*126)
        self.assertEqual([int.from_bytes(p[5:7], 'little') for p in self.usb.writes if p[3] == 17],
                         [0,54,108,162,216,270,324])

    def test_falta_de_resposta_interrompe_quadro_e_nao_marca_como_enviado(self):
        self.usb.drop_offset = 108
        with self.assertRaisesRegex(ErroKumaraUSB, 'bloco de LEDs 3'):
            self.keyboard.enviar_zonas([(255,0,0)]*3)
        self.assertIsNone(self.keyboard._last_frame)
        offsets = [int.from_bytes(p[5:7], 'little') for p in self.usb.writes if p[3] == 17]
        self.assertEqual(offsets, [0,54,108,108])
        self.usb.drop_offset = None
        self.keyboard.enviar_zonas([(255,0,0)]*3)
        self.assertEqual(self.frame(), bytes([255,0,0])*126)

    def test_resposta_de_bloco_antigo_nao_e_aceita_como_atual(self):
        self.usb.pending.append(pacote_evision(17, bytes([0,0,255])*18, 54))
        self.keyboard._send_block(bytes([0,255,0])*18, 0)
        self.assertFalse(self.usb.pending)

    def test_usb_desconectado_vira_erro_de_teclado_tratavel_pelo_boost(self):
        from teclado_openrgb import OpenRGBKeyboardError
        with patch.object(self.usb, 'write', side_effect=OSError('desconectado')):
            with self.assertRaises(OpenRGBKeyboardError):
                self.keyboard.enviar_zonas([(0,255,0)]*3)

    def test_zonas_preenchem_todos_os_leds_sem_buracos(self):
        self.assertEqual(set(colunas_kumara()), set(range(126)))
        self.keyboard.enviar_zonas([(0,255,0)]*3)
        self.assertEqual(self.frame(), bytes([0,255,0])*126)
        self.keyboard.enviar_zonas([(255,0,0),(0,255,0),(0,0,255)])
        frame = self.frame()
        self.assertEqual({tuple(frame[i:i+3]) for i in range(0,378,3)},
                         {(255,0,0),(0,255,0),(0,0,255)})

    def test_ambilight_aceita_doze_zonas(self):
        colors = [(index * 10, 255 - index * 10, index) for index in range(12)]
        self.keyboard.enviar_zonas(colors)
        frame = self.frame()
        presentes = {tuple(frame[i:i+3]) for i in range(0, 378, 3)}
        self.assertEqual(presentes, set(colors))

    def test_boost_zero_cinquenta_e_cem(self):
        self.keyboard.definir_cor_base((12,34,56))
        self.keyboard.set_boost(0)
        self.assertEqual(self.frame(), bytes(378))
        self.keyboard.set_boost(50)
        frame = self.frame()
        self.assertIn(bytes([12,34,56]), frame)
        self.assertIn(bytes([0,0,0]), frame)
        self.keyboard.set_boost(100)
        self.assertEqual(self.frame(), bytes([12,34,56])*126)

    def test_ambilight_atualiza_rgb_sem_reiniciar_modo_ou_regravar_leds(self):
        self.keyboard.enviar_ambilight([(0,90,240)]*3)
        self.usb.writes.clear()
        self.keyboard.enviar_ambilight([(0,180,90)]*3)
        self.assertEqual(self.usb.writes, [pacote_evision(6, bytes((0,180,90)), 5)])
        self.keyboard.enviar_ambilight([(0,180,90)]*3)
        self.assertEqual(len(self.usb.writes), 1)

    def test_flash_estatico_retorna_para_barra_custom_mesmo_quadro(self):
        self.keyboard.set_boost(50)
        original = self.frame()
        self.keyboard.enviar_rgb(255,220,170)
        self.usb.writes.clear()
        self.keyboard.set_boost(50)
        self.assertEqual(self.frame(), original)
        self.assertEqual(self.usb.writes[0][8], 20)

    def test_erro_de_cor_permite_reinicializar_no_envio_seguinte(self):
        self.usb.drop_offset = 5
        with self.assertRaisesRegex(ErroKumaraUSB, 'parametro de cor'):
            self.keyboard.enviar_rgb(0,80,255)
        self.usb.drop_offset = None
        self.keyboard.enviar_rgb(0,80,255)
        self.assertTrue(self.keyboard._static_ready)

    def test_close_libera_usb_mesmo_quando_restauracao_falha(self):
        with patch.object(self.keyboard, '_mode', side_effect=OSError('USB desconectado')):
            with self.assertRaises(OSError):
                self.keyboard.close()
        self.assertTrue(self.usb.closed)
        another = TecladoKumaraUSB({}, device=USBFalso())
        another.close()


if __name__ == '__main__':
    unittest.main()
