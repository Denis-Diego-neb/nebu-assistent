import json
import unittest
from unittest.mock import Mock, patch

from notebook_power_server.universal_control import HomeAssistant, UniversalController, UniversalError
from notebook_power_server.tv_control import TvManager


class UniversalTests(unittest.TestCase):
    def setUp(self):
        self.brain = Mock(lamp=object())
        self.brain.air.estado.return_value = {"available": True, "temperature": 24}
        self.brain.action.return_value = {"ok": True}
        self.tvs = Mock()
        self.tvs.list.return_value = [{"id": "samsung-sala", "name": "TV Sala", "brand": "samsung",
            "online": True, "paired": True, "can_power_on": True}]
        self.ha = Mock(configured=False)
        self.ha.devices.return_value = []
        self.wake = Mock(return_value={"ok": True})
        self.control = UniversalController(self.brain, self.tvs, self.wake, self.ha)

    def test_catalog_is_cached_and_does_not_probe_pc(self):
        first = self.control.devices()
        first["devices"].clear()
        self.assertEqual(self.control.devices()["count"], 4)
        self.assertEqual(len(self.control.devices()["devices"]), 4)
        self.tvs.list.assert_called_once()
        self.brain.status.assert_not_called()

    def test_advertised_tv_commands_match_driver(self):
        tv = next(d for d in self.control.devices()["devices"] if d["kind"] == "tv")
        self.assertTrue(all(a["id"] in TvManager.ACTIONS for a in tv["actions"]))

    def test_offline_tv_only_offers_wake(self):
        self.tvs.list.return_value[0]["online"] = False
        tv = self.control.devices()["devices"][-1]
        self.assertEqual([a["id"] for a in tv["actions"]], ["power_on"])

    def test_unpaired_tv_offers_pairing(self):
        self.tvs.list.return_value[0]["paired"] = False
        tv = self.control.devices()["devices"][-1]
        self.assertIn("pair", [a["id"] for a in tv["actions"]])
        self.assertNotIn("volume_up", [a["id"] for a in tv["actions"]])

    def test_temperature_uses_current_value_and_stays_in_range(self):
        self.control.action("local:air", "temp_up")
        self.brain.action.assert_called_with("air.temperature", 25)
        self.brain.air.estado.return_value["temperature"] = 16
        self.control.action("local:air", "temp_down")
        self.brain.action.assert_called_with("air.temperature", 16)

    def test_wake_and_lamp_route_to_existing_controls(self):
        self.control.action("pc:main", "wake")
        self.wake.assert_called_once()
        self.control.action("local:lamp", "turn_off")
        self.brain.action.assert_called_with("lamp.power", False)

    def test_rejects_arbitrary_commands(self):
        for key, action in (("pc:main", "shutdown"), ("local:lamp", "exec"), ([], "wake")):
            with self.subTest(key=key), self.assertRaises(UniversalError):
                self.control.action(key, action)
        self.wake.assert_not_called()
        self.brain.action.assert_not_called()

    def test_failed_optional_provider_keeps_local_devices(self):
        self.ha.devices.side_effect = RuntimeError("secret token")
        result = self.control.devices()
        self.assertEqual(result["count"], 4)
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(len(result["errors"]), 1)


class HomeAssistantTests(unittest.TestCase):
    def setUp(self):
        self.ha = HomeAssistant("http://homeassistant.local:8123", "private-secret")
        self.raw = [{"entity_id": "light.sala", "state": "off", "attributes": {"friendly_name": "Sala"}},
                    {"entity_id": "sensor.pulse", "state": "75", "attributes": {}},
                    {"entity_id": "lock.door", "state": "locked", "attributes": {}}]

    def test_catalog_omits_unsupported_entities_and_token(self):
        with patch.object(self.ha, "_request", return_value=self.raw):
            result = self.ha.devices()
        self.assertEqual([d["id"] for d in result], ["ha:light.sala"])
        self.assertNotIn("private-secret", json.dumps(result))

    def test_service_call_targets_only_registered_entity(self):
        with patch.object(self.ha, "_request", return_value=self.raw) as request:
            self.ha.devices()
            self.ha.action("light.sala", "turn_on")
            request.assert_called_with("/api/services/light/turn_on", {"entity_id": "light.sala"})
            with self.assertRaises(UniversalError): self.ha.action("light.sala", "toggle")
            with self.assertRaises(UniversalError): self.ha.action("lock.door", "unlock")

    def test_media_play_feature_is_distinct_from_play_media(self):
        entity = {"entity_id": "media_player.tv", "attributes": {"supported_features": 512}}
        self.assertNotIn("media_play", self.ha._commands(entity))
        entity["attributes"]["supported_features"] = 16384
        self.assertIn("media_play", self.ha._commands(entity))

    def test_unavailable_entity_cannot_receive_action(self):
        self.raw[0]["state"] = "unavailable"
        with patch.object(self.ha, "_request", return_value=self.raw):
            self.assertEqual(self.ha.devices()[0]["actions"], [])
            with self.assertRaises(UniversalError): self.ha.action("light.sala", "turn_on")

    def test_invalid_url_rejected_without_request(self):
        self.ha.url = "file:///etc/passwd"
        with self.assertRaises(UniversalError): self.ha.devices()


if __name__ == "__main__": unittest.main()
