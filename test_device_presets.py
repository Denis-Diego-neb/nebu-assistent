import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from device_presets import Presets, defaults, voice_preset
from main import Nebula
from test_control_panel import SaidaFalsa


class IndependentModesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        self.env.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.env.stop)
        self.nebula = Nebula(SaidaFalsa(), abrir_navegador=False)
        self.lamp = Mock()
        self.patchlamp = patch.object(self.nebula, "_obter_controle_abajur", return_value=self.lamp)
        self.patchlamp.start(); self.addCleanup(self.patchlamp.stop)
        self.engines = {}
        for mode in ("rpm", "ambilight", "boost"):
            def start(m=mode):
                engine = Mock(ativo=True, erro=None)
                engine.status.return_value = {"rpm": 3210, "recebendo": True, "telemetria_valida": True}
                setattr(self.nebula, "_modo_"+m, engine)
                self.engines[m] = engine
            p = patch.object(self.nebula, "_iniciar_modo_"+mode, side_effect=start)
            p.start();self.addCleanup(p.stop)

    def select(self, device, mode):
        return self.nebula.executar_controle("device.mode", {"device": device, "mode": mode})

    def test_music_lamp_keyboard_ambilight_and_phone_rpm_are_independent(self):
        self.select("keyboard", "ambilight")
        keyboard = self.engines["ambilight"]
        self.select("mobile", "rpm")
        rpm = self.engines["rpm"]
        result = self.select("lamp", "music")
        keyboard.parar.assert_not_called();rpm.parar.assert_not_called()
        self.lamp.iniciar_ritmo_navegador.assert_called_once()
        self.assertEqual(result["state"]["rpm"], 3210)
        self.nebula.executar_controle("lamp.color", "#ff8800")
        keyboard.parar.assert_not_called();rpm.parar.assert_not_called()
        self.lamp.rgb.assert_called_with(255,136,0)
        self.select("mobile", "turbo")
        rpm.parar.assert_called_once();keyboard.parar.assert_not_called()

    def test_invalid_mode_never_stops_any_running_output(self):
        self.select("keyboard", "ambilight")
        keyboard = self.engines["ambilight"]
        with self.assertRaises(ValueError):self.select("keyboard", "music")
        keyboard.parar.assert_not_called()
        self.assertEqual(self.nebula._devices["keyboard"]["mode"], "ambilight")

    def test_preset_roundtrip_and_voice_apply_restore_colors_modes_and_flash(self):
        self.select("keyboard", "ambilight")
        self.select("mobile", "turbo")
        self.nebula.executar_controle("lamp.color", "#ff8800")
        self.nebula.executar_controle("lamp.brightness", 35)
        self.nebula._devices["keyboard"]["afterfire"] = True
        self.nebula.executar_controle("preset.save", "Corrida")
        reloaded = Presets(Path(self.temp.name)/"Nebula"/"device_presets.json")
        saved = reloaded.get("CORRIDA")
        self.assertEqual(saved["lamp"]["brightness"], 35)
        self.assertTrue(saved["keyboard"]["afterfire"])
        self.nebula.executar_controle("lamp.color", "verde")
        self.nebula.executar("Nebula, ative o preset Corrida")
        self.assertEqual(self.nebula._devices["lamp"]["color"], "#ff8800")
        self.assertEqual(self.nebula._active_preset,"Corrida")

    def test_missing_device_is_reported_without_stopping_other_modes(self):
        self.select("keyboard", "ambilight")
        keyboard=self.engines["ambilight"]
        self.lamp.iniciar_ritmo_navegador.side_effect=OSError("offline")
        state=self.select("lamp", "music")["state"]
        self.assertEqual(state["devices"]["lamp"]["error"],"offline")
        keyboard.parar.assert_not_called()

    def test_idempotent_apply_does_not_restart_and_invalid_preset_does_not_write(self):
        self.select("keyboard", "ambilight")
        keyboard=self.engines["ambilight"]
        self.nebula.executar_controle("preset.save","Um")
        self.nebula.executar_controle("preset.apply","um")
        keyboard.parar.assert_not_called()
        before=self.nebula._presets.path.read_bytes()
        bad=defaults();bad["lamp"]["brightness"]=500
        with self.assertRaises(ValueError):self.nebula._presets.save("Inválido",bad)
        self.assertEqual(self.nebula._presets.path.read_bytes(),before)
        self.assertEqual(voice_preset("troque para o preset Corrida"),("preset.apply","Corrida"))


class ExhaustTelemetryTests(unittest.TestCase):
    def test_counter_freshness_protocol_compatibility_and_patch_scope(self):
        from beamng_turbo import BeamngTurbo, PACKET_V2
        from integracoes.beamng.install import afterfire_patch
        now=[0.0];sensor=BeamngTurbo(clock=lambda:now[0])
        self.assertTrue(sensor.ingest(PACKET_V2.pack(b"NBTG",2,1,1,0,0,5000,42)))
        self.assertEqual(sensor.status()["afterfire"],42)
        now[0]=2
        self.assertIsNone(sensor.status()["afterfire"])
        source="\n".join(f"  obj:playSFXOnceCT(afterFire.{x}, n.finish)" for x in ("instantAudioSample","shiftAudioSample","sustainedAudioSample"))
        patched=afterfire_patch(source)
        self.assertEqual(patched.count("electrics.values.nebulaAfterfire ="),3)
        self.assertEqual(patched.count("obj:playSFXOnceCT"),3)
        with self.assertRaises(ValueError):afterfire_patch("unknown version")

    def test_flash_restores_newest_base_not_old_ambilight_color(self):
        import time
        from exhaust_flash import ExhaustFlash
        count=[0];sensor=Mock();sensor.status.side_effect=lambda:{"afterfire":count[0]}
        output=Mock();flash=ExhaustFlash(output,sensor=sensor)
        try:
            flash.set_rgb(0,255,0)
            time.sleep(.06);count[0]=1
            deadline=time.monotonic()+1
            while not flash._flashing and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(flash._flashing)
            flash.set_rgb(0,0,255)
            time.sleep(.3)
            output.set_rgb.assert_called_with(0,0,255)
            self.assertIn(((255,220,170),),[(c.args,) for c in output.set_rgb.call_args_list])
        finally:flash.close()
        output.close.assert_called_once()


if __name__ == "__main__":unittest.main()
