import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from notebook_power_server.tv_control import (
    LgWebOsTv,
    SamsungTv,
    TvError,
    TvManager,
)


class TvManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tvs.json"

    def manager_with_devices(self) -> TvManager:
        self.path.write_text(json.dumps({
            "samsung-sala": {
                "id": "samsung-sala",
                "brand": "samsung",
                "host": "192.168.15.21",
                "name": "Samsung Sala",
                "model": "CU8000",
                "mac": "F8:4E:58:8E:A1:36",
                "token": "segredo",
            },
            "lg-quarto": {
                "id": "lg-quarto",
                "brand": "lg",
                "host": "192.168.15.9",
                "name": "LG Quarto",
                "model": "webOS",
                "mac": "F0:86:20:F0:F0:68",
                "client_key": "segredo-lg",
            },
        }), encoding="utf-8")
        return TvManager(self.path)

    @patch("notebook_power_server.tv_control._port_open", return_value=True)
    def test_list_hides_pairing_secrets(self, _port: Mock) -> None:
        items = self.manager_with_devices().list()
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["paired"] for item in items))
        self.assertTrue(all("token" not in item and "client_key" not in item for item in items))

    def test_rejects_unknown_device_and_action(self) -> None:
        manager = self.manager_with_devices()
        with self.assertRaises(TvError):
            manager.action("missing", "volume_up")
        with self.assertRaises(TvError):
            manager.action("samsung-sala", "raw_key")

    @patch("notebook_power_server.tv_control.TvManager._local_networks")
    @patch("notebook_power_server.tv_control.TvManager._probe")
    def test_discovery_persists_supported_tvs(self, probe: Mock, networks: Mock) -> None:
        import ipaddress

        networks.return_value = [ipaddress.ip_network("192.168.15.8/30")]
        probe.side_effect = lambda host: ({
            "brand": "lg",
            "host": host,
            "name": "LG webOS TV",
            "model": "webOS",
            "mac": "AA:BB:CC:DD:EE:FF",
        } if host.endswith(".9") else None)
        manager = TvManager(self.path)
        items = manager.discover()
        self.assertEqual(items[0]["id"], "lg-192-168-15-9")
        self.assertTrue(self.path.is_file())

    @patch("notebook_power_server.tv_control.SamsungTv.action")
    def test_routes_action_to_registered_driver(self, action: Mock) -> None:
        result = self.manager_with_devices().action("samsung-sala", "volume_up")
        self.assertTrue(result["ok"])
        action.assert_called_once_with("volume_up")

    @patch("notebook_power_server.tv_control.SamsungTv.action")
    @patch("notebook_power_server.tv_control.LgWebOsTv.action")
    def test_routes_group_action_to_every_tv(self, lg_action: Mock, samsung_action: Mock) -> None:
        result = self.manager_with_devices().action_all("mute")
        self.assertEqual(result["successes"], 2)
        self.assertEqual(result["failures"], 0)
        samsung_action.assert_called_once_with("mute")
        lg_action.assert_called_once_with("mute")

    @patch("notebook_power_server.tv_control.SamsungTv.action")
    def test_group_reports_power_on_as_unconfirmed(self, samsung_action: Mock) -> None:
        result = self.manager_with_devices().action_all("power_on")
        self.assertEqual(result["delivery"], "unconfirmed")
        self.assertIn("sem confirmação", result["message"])

    @patch("notebook_power_server.tv_control.SamsungTv.action")
    def test_rejects_remote_action_before_pairing(self, action: Mock) -> None:
        self.path.write_text(json.dumps({
            "samsung-sem-token": {
                "id": "samsung-sem-token", "brand": "samsung",
                "host": "192.168.15.22", "name": "Samsung",
                "mac": "AA:BB:CC:DD:EE:FF",
            }
        }), encoding="utf-8")
        with self.assertRaisesRegex(TvError, "pareada"):
            TvManager(self.path).action("samsung-sem-token", "mute")
        action.assert_not_called()

    @patch("notebook_power_server.tv_control.SamsungTv.open_youtube")
    @patch("notebook_power_server.tv_control.LgWebOsTv.open_youtube")
    @patch("notebook_power_server.tv_control.TvManager._youtube_url", return_value="https://youtu.be/teste")
    def test_opens_same_youtube_video_on_every_tv(
        self, resolve: Mock, lg_youtube: Mock, samsung_youtube: Mock
    ) -> None:
        result = self.manager_with_devices().youtube("musica teste")
        self.assertEqual(result["successes"], 2)
        resolve.assert_called_once_with("musica teste")
        lg_youtube.assert_called_once_with("https://youtu.be/teste")
        samsung_youtube.assert_called_once_with("https://youtu.be/teste")


class SamsungTvTests(unittest.TestCase):
    @patch("notebook_power_server.tv_control.websocket.create_connection")
    def test_sends_only_allowlisted_remote_key(self, create: Mock) -> None:
        ws = create.return_value
        ws.recv.return_value = json.dumps({"event": "ms.channel.connect", "data": {"token": "novo"}})
        device = {"host": "192.168.15.21", "brand": "samsung"}
        SamsungTv(device).action("volume_up")
        sent = json.loads(ws.send.call_args.args[0])
        self.assertEqual(sent["params"]["DataOfCmd"], "KEY_VOLUP")
        self.assertEqual(device["token"], "novo")

    @patch.object(SamsungTv, "_connect")
    def test_launches_youtube_deep_link(self, connect: Mock) -> None:
        ws = connect.return_value
        ws.recv.side_effect = TimeoutError
        SamsungTv({"host": "192.168.15.21", "brand": "samsung"}).open_youtube(
            "https://youtu.be/teste"
        )
        sent = [json.loads(call.args[0]) for call in ws.send.call_args_list]
        launch = next(item for item in sent if item["params"]["event"] == "ed.apps.launch")
        self.assertEqual(launch["params"]["data"]["metaTag"], "https://youtu.be/teste")


class LgWebOsTvTests(unittest.TestCase):
    @patch.object(LgWebOsTv, "_connect")
    def test_uses_ssap_for_volume(self, connect: Mock) -> None:
        ws = connect.return_value
        ws.recv.return_value = json.dumps({
            "id": "nebula_1",
            "type": "response",
            "payload": {"returnValue": True},
        })
        LgWebOsTv({"host": "192.168.15.9", "brand": "lg"}).action("volume_down")
        sent = json.loads(ws.send.call_args.args[0])
        self.assertEqual(sent["uri"], "ssap://audio/volumeDown")


if __name__ == "__main__":
    unittest.main()
