import io
import json
import unittest
from unittest.mock import Mock, patch
from phone_usb_panel import UsbPanel


class UsbPanelTests(unittest.TestCase):
    def test_opens_once_per_connection_and_retries_after_disconnect(self):
        panel = UsbPanel('test-token')
        panel.adb = Mock()
        panel.adb.is_file.return_value = True
        panel.command = Mock(return_value='device')
        response = json.dumps({'state': {'devices': {'mobile': {'mode': 'rpm'}}}}).encode()
        with patch('phone_usb_panel.urlopen', side_effect=lambda *a, **kw: io.BytesIO(response)):
            panel.tick()
            panel.tick()
            self.assertEqual(sum(c.args[0] == 'shell' for c in panel.command.call_args_list), 1)
            panel.command.side_effect = OSError('offline')
            panel.tick()
            self.assertFalse(panel.opened)
            panel.command.side_effect = None
            panel.tick()
            self.assertEqual(sum(c.args[0] == 'shell' for c in panel.command.call_args_list), 2)

    def test_manual_mode_does_not_open_the_phone(self):
        panel = UsbPanel('test-token')
        panel.adb = Mock()
        panel.command = Mock(return_value='device')
        response = json.dumps({'devices': {'mobile': {'mode': 'manual'}}}).encode()
        with patch('phone_usb_panel.urlopen', return_value=io.BytesIO(response)):
            panel.tick()
        panel.command.assert_called_once_with('get-state')
        self.assertFalse(panel.opened)
