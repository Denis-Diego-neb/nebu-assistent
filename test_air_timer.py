from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from notebook_power_server.air_timer import AirTimer


class AirTimerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'timer.json'
        self.now = 1000
        self.air = Mock()
        self.timer = AirTimer(self.air, self.path, lambda: self.now)

    def test_dispara_uma_vez_so_no_prazo_e_sobrevive_reinicio(self):
        self.timer.set(30)
        self.now += 1799
        self.timer.tick()
        self.air.executar.assert_not_called()
        recovered = AirTimer(self.air, self.path, lambda: self.now)
        self.now += 1
        recovered.tick()
        recovered.tick()
        self.air.executar.assert_called_once_with('power', False)
        self.assertEqual(recovered.status()['status'], 'sent')

    def test_cancelamento_e_substituicao(self):
        self.timer.set(30)
        self.timer.set(60)
        self.now += 1800
        self.timer.tick()
        self.air.executar.assert_not_called()
        self.timer.set(0)
        self.now += 3600
        self.timer.tick()
        self.air.executar.assert_not_called()

    def test_aceita_minutos_quebrados(self):
        for minutes in (1, 10, 45, 1440):
            with self.subTest(minutes=minutes):
                self.assertEqual(self.timer.set(minutes)['timer']['remaining_minutes'], minutes)
        self.timer.set(10)
        self.now += 599
        self.timer.tick()
        self.air.executar.assert_not_called()
        self.now += 1
        self.timer.tick()
        self.air.executar.assert_called_once_with('power', False)

    def test_limites_e_falha_sem_sucesso_falso(self):
        for value in (-30, -1, 1441, 1470, True, '30', 30.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.timer.set(value)
        self.timer.set(30)
        self.air.executar.side_effect = RuntimeError('offline')
        self.now += 1800
        self.timer.tick()
        self.assertEqual(self.timer.status()['status'], 'failed')
        self.timer.tick()
        self.air.executar.assert_called_once()


if __name__ == '__main__':
    unittest.main()
