import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from beamng_turbo import BeamngTurbo, PACKET, decode_packet


def packet(seq=1, flags=3, pressure=1.2, maximum=3, rpm=4000):
    return PACKET.pack(b'NBTG',1,seq,flags,pressure,maximum,rpm)


class BeamngTurboTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.sensor = BeamngTurbo(clock=lambda:self.now)

    def test_pressure_units_zero_and_absent_turbo_are_distinct(self):
        self.sensor.ingest(packet(pressure=0))
        self.assertEqual(self.sensor.status()['turbo_bar'],0)
        self.sensor.ingest(packet(seq=2,flags=1))
        self.assertEqual(self.sensor.status()['status'],'no_turbo')
        self.assertIsNone(self.sensor.status()['turbo_bar'])

    def test_stale_sequence_restart_and_nonlocal_origin(self):
        self.assertTrue(self.sensor.ingest(packet(seq=100)))
        self.assertFalse(self.sensor.ingest(packet(seq=99)))
        self.assertFalse(self.sensor.ingest(packet(seq=101),origin='192.168.1.2'))
        self.now = 1.1
        self.assertIsNone(self.sensor.status()['turbo_bar'])
        self.assertTrue(self.sensor.ingest(packet(seq=0)))
        self.assertTrue(self.sensor.status()['valid'])

    def test_sequence_wrap_and_invalid_data(self):
        self.assertTrue(self.sensor.ingest(packet(seq=0xffffffff)))
        self.assertTrue(self.sensor.ingest(packet(seq=0)))
        for data in (b'',packet()+b'x',packet(flags=8),packet(pressure=float('nan')),packet(maximum=100)):
            self.assertFalse(self.sensor.ingest(data))

    def test_real_udp_receiver_on_loopback(self):
        sensor = BeamngTurbo(port=0)
        sensor.start()
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sender:
                sender.sendto(packet(pressure=1.75),sensor._socket.getsockname())
            deadline=time.monotonic()+1
            while not sensor.status()['valid'] and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertAlmostEqual(sensor.status()['turbo_bar'],1.75)
        finally:
            sensor.close()

    def test_endpoint_requires_auth_and_returns_no_fake_pressure(self):
        from remote_server import Handler, POWER_TOKEN
        with patch('remote_server.BEAMNG_TURBO',self.sensor), patch.object(self.sensor,'start'):
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            url=f'http://127.0.0.1:{server.server_port}/api/beamng/turbo'
            try:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(url)
                self.assertEqual(caught.exception.code,401)
                caught.exception.close()
                request=urllib.request.Request(url,headers={'X-Nebula-Power-Token':POWER_TOKEN})
                with urllib.request.urlopen(request) as response:
                    self.assertIsNone(json.load(response)['turbo_bar'])
            finally:
                server.shutdown();server.server_close()

    def test_installer_keeps_existing_settings_and_simhub(self):
        from integracoes.beamng.install import install
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'settings').mkdir();(root/'mods').mkdir()
            settings=root/'settings'/'settings.json'
            settings.write_text('{"volume":0.25,"protocols_others_enabled":false}')
            (root/'mods'/'simhubextras.zip').write_bytes(b'existing')
            target=install(root)
            self.assertEqual((root/'mods'/'simhubextras.zip').read_bytes(),b'existing')
            self.assertEqual(json.loads(settings.read_text())['volume'],.25)
            self.assertTrue(json.loads(settings.read_text())['protocols_others_enabled'])
            self.assertEqual(len(list((root/'settings').glob('*backup*'))),1)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.namelist(),['lua/vehicle/protocols/nebulaTurbo.lua'])


if __name__ == '__main__': unittest.main()
