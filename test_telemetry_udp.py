import socket
import unittest

from telemetry_udp import subscribe
from modo_rpm import ModoRPM, ModoBoost
from test_modo_rpm import amostra, pacote as rpm_packet
from test_modo_boost import esperar, pacote as boost_packet


class SharedTelemetryTests(unittest.TestCase):
    def test_all_subscribers_receive_and_closing_one_keeps_other_alive(self):
        first = subscribe('127.0.0.1', 0)
        self.addCleanup(first.close)
        address = first.getsockname()
        second = subscribe(*address)
        self.addCleanup(second.close)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(b'one', address)
            self.assertEqual(first.recvfrom(4097)[0], b'one')
            self.assertEqual(second.recvfrom(4097)[0], b'one')
            first.close()
            sender.sendto(b'two', address)
            self.assertEqual(second.recvfrom(4097)[0], b'two')
        second.close()
        reopened = subscribe(*address)
        reopened.close()

    def test_real_rpm_and_boost_engines_share_port_and_stop_independently(self):
        rpm = ModoRPM(fabrica_lightbar=None, port=0)
        self.addCleanup(rpm.parar)
        rpm.iniciar()
        address = rpm._socket.getsockname()
        boost = ModoBoost(lambda value: None, port=address[1],
                          fabrica_lightbar=None, fabrica_teclado=None)
        self.addCleanup(boost.parar)
        boost.iniciar()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(rpm_packet(amostra(.5)), address)
            sender.sendto(boost_packet(.75), address)
            self.assertTrue(esperar(lambda: rpm.status()['recebendo'] and boost.status()['recebendo']))
            rpm.parar()
            sender.sendto(boost_packet(.5, seq=2), address)
            self.assertTrue(esperar(lambda: boost._ultima_sequencia == 2))


if __name__ == '__main__':
    unittest.main()
