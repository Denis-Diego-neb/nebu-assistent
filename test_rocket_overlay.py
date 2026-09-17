import unittest
from unittest.mock import Mock, patch
from rocket_overlay import OverlayBridge, overlay_snapshot


class OverlayTests(unittest.TestCase):
    def test_absent_and_stale_values_are_hidden(self):
        self.assertIsNone(overlay_snapshot({})["bpm"])
        result = overlay_snapshot({"status": "experimental_estimate", "bpm": 72, "last_sample_age_seconds": 10})
        self.assertIsNone(result["bpm"])

    def test_live_experimental_pulse(self):
        result = overlay_snapshot({"status": "experimental_estimate", "bpm": 72, "last_sample_age_seconds": 1})
        self.assertEqual(result["bpm"], 72)
        self.assertIsNone(result["boost_percent"])

    def test_boost_bar_requires_live_telemetry_and_preserves_zero(self):
        control = {"mode": "boost", "receiving": True, "telemetry_valid": True, "boost_percent": 0}
        self.assertEqual(overlay_snapshot({}, control)["boost_percent"], 0)
        control["boost_percent"] = 63
        self.assertEqual(overlay_snapshot({}, control)["boost_percent"], 63)
        control["receiving"] = False
        self.assertIsNone(overlay_snapshot({}, control)["boost_percent"])

    def test_invalid_numbers_and_untrusted_status_hidden(self):
        for value in (float("nan"), float("inf"), True, 250, -1):
            result = overlay_snapshot({"status": "experimental_estimate", "bpm": value, "last_sample_age_seconds": 0})
            self.assertIsNone(result["bpm"])
        self.assertIsNone(overlay_snapshot({"status": "poor_signal", "bpm": 72, "last_sample_age_seconds": 0})["bpm"])

    def test_remote_bridge_queues_and_rejects_concurrent_commands(self):
        bridge = OverlayBridge()
        callback = Mock()
        with patch("rocket_overlay.sys.platform", "win32"): bridge.register(callback)
        self.assertTrue(bridge.request("start")["ok"])
        callback.assert_called_once_with("start", None)
        self.assertTrue(bridge.status()["pending"])
        with self.assertRaises(RuntimeError): bridge.request("start")
        bridge.publish(pending=False, enabled=True)
        self.assertTrue(bridge.status()["running"])
        bridge.unregister()
        self.assertFalse(bridge.status()["running"])
        with self.assertRaises(RuntimeError): bridge.request("start")

    def test_invalid_actions_raise_value_error(self):
        bridge = OverlayBridge()
        for action in (None, [], {}, "exec"):
            with self.assertRaises(ValueError): bridge.request(action)
        for nickname in (None, "x" * 21, "a\nb"):
            with self.assertRaises(ValueError): bridge.request("nickname", nickname)


if __name__ == "__main__": unittest.main()
