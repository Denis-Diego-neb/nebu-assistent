import copy
import math
import random
import unittest

from wifi_bpm import WifiBpmSensor


class WifiBpmTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        self.sensor = WifiBpmSensor(clock=lambda: self.now)

    def capture(self, bpm=72, seconds=30, rate=16, signal=None):
        samples = []
        count = round(seconds * rate) + 1
        for i in range(count):
            t = i / rate
            values = []
            for carrier in range(8):
                amplitude = (signal(t, carrier) if signal else
                             30 + carrier + 0.45 * math.sin(2 * math.pi * bpm / 60 * t + carrier * 0.12))
                # Test genuine complex pairs, not just one scalar feature.
                values.append([amplitude * 0.8, amplitude * 0.6])
            samples.append({"timestamp": self.now - seconds + t, "csi": values})
        return {"source": "synthetic-test-only", "layout": "channel6/antenna0/ltf-test", "samples": samples}

    def test_no_hardware_never_displays_bpm(self):
        state = self.sensor.status()
        self.assertEqual(state["status"], "hardware_required")
        self.assertIsNone(state["bpm"])

    def test_known_periodic_complex_signal_is_estimated(self):
        for bpm in (54, 72, 97, 132, 168):
            with self.subTest(bpm=bpm):
                self.sensor.reset()
                state = self.sensor.ingest(self.capture(bpm=bpm))
                self.assertEqual(state["status"], "experimental_estimate", state)
                self.assertAlmostEqual(state["bpm"], bpm, delta=1.5)
                self.assertGreater(state["quality"], 0.7)
                self.assertTrue(state["experimental"])

    def test_short_capture_is_collecting(self):
        result = self.sensor.ingest(self.capture(seconds=10))
        self.assertEqual(result["status"], "collecting")
        self.assertIsNone(result["bpm"])

    def test_flat_noise_and_large_motion_are_rejected(self):
        rng = random.Random(812)
        signals = [lambda t, c: 30.0,
                   lambda t, c: 30 + rng.uniform(-1, 1),
                   lambda t, c: 30 + 15 * math.sin(2 * math.pi * 1.2 * t)]
        for signal in signals:
            with self.subTest(signal=signal):
                self.sensor.reset()
                result = self.sensor.ingest(self.capture(signal=signal))
                self.assertEqual(result["status"], "poor_signal", result)
                self.assertIsNone(result["bpm"])

    def test_respiration_and_its_heartbeat_band_harmonic_rejected(self):
        result = self.sensor.ingest(self.capture(signal=lambda t, c:
            30 + c + math.sin(2 * math.pi * 0.3 * t) + 0.8 * math.sin(2 * math.pi * 1.2 * t)))
        self.assertEqual(result["status"], "poor_signal", result)
        self.assertIsNone(result["bpm"])

    def test_frequency_changing_mid_window_is_rejected(self):
        result = self.sensor.ingest(self.capture(signal=lambda t, c:
            30 + c + 0.4 * math.sin(2 * math.pi * (1.0 if t < 15 else 1.5) * t)))
        self.assertEqual(result["status"], "poor_signal", result)

    def test_low_cadence_and_gap_rejected(self):
        result = self.sensor.ingest(self.capture(rate=5))
        self.assertEqual(result["status"], "poor_signal", result)
        self.sensor.reset()
        payload = self.capture()
        payload["samples"] = [s for s in payload["samples"]
                              if not self.now - 15 < s["timestamp"] < self.now - 14]
        result = self.sensor.ingest(payload)
        self.assertEqual(result["status"], "poor_signal", result)

    def test_stale_estimate_cannot_survive_cache(self):
        self.assertIsNotNone(self.sensor.ingest(self.capture())["bpm"])
        self.now += 6
        state = self.sensor.status()
        self.assertEqual(state["status"], "stale")
        self.assertIsNone(state["bpm"])
        self.assertEqual(self.sensor.reset()["status"], "hardware_required")

    def test_new_capture_after_outage_restarts_window(self):
        self.sensor.ingest(self.capture())
        self.now += 10
        state = self.sensor.ingest(self.capture(seconds=0))
        self.assertEqual(state["status"], "collecting")
        self.assertEqual(state["samples"], 1)
        self.assertIsNone(state["bpm"])

    def test_rssi_nan_old_future_and_invalid_batches_rejected(self):
        valid = self.capture(seconds=0)
        invalid = [None, [], {}, {"source": "esp32", "timestamp": self.now, "rssi": -55}]
        for timestamp in (True, float("nan"), self.now + 10, self.now - 100):
            payload = copy.deepcopy(valid)
            payload["samples"][0]["timestamp"] = timestamp
            invalid.append(payload)
        for csi in ([1, 2, 3, 4], [[float("inf"), 1]] * 4, [[1, True]] * 4):
            payload = copy.deepcopy(valid)
            payload["samples"][0]["csi"] = csi
            invalid.append(payload)
        invalid.append({"source": "esp32", "samples": [valid["samples"][0]] * 513})
        for payload in invalid:
            with self.subTest(payload=str(payload)[:100]):
                with self.assertRaises(ValueError):
                    self.sensor.ingest(payload)
                self.assertEqual(self.sensor.status()["samples"], 0)

    def test_bad_batch_is_atomic_and_reordered_capture_rejected(self):
        payload = self.capture(seconds=1)
        payload["samples"][-1]["csi"] = [[1, 2]]
        with self.assertRaises(ValueError):
            self.sensor.ingest(payload)
        self.assertEqual(self.sensor.status()["samples"], 0)
        valid = self.capture(seconds=1)
        state = self.sensor.ingest(valid)
        with self.assertRaises(ValueError):
            self.sensor.ingest(valid)
        self.assertEqual(self.sensor.status()["samples"], state["samples"])

    def test_layout_source_and_carrier_count_cannot_mix(self):
        self.sensor.ingest(self.capture(seconds=1))
        self.now += 0.1
        for key, value in (("source", "other-esp32"), ("layout", "channel11")):
            payload = self.capture(seconds=0)
            payload[key] = value
            with self.assertRaises(ValueError):
                self.sensor.ingest(payload)
        payload = self.capture(seconds=0)
        payload["samples"][0]["csi"].pop()
        with self.assertRaises(ValueError):
            self.sensor.ingest(payload)


if __name__ == "__main__":
    unittest.main()
