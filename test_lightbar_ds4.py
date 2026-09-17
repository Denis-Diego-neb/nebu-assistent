import unittest

from lightbar_ds4 import (
    DS4ClosedError,
    DS4Lightbar,
    DS4NotFoundError,
    DS4WriteError,
    HIDUnavailableError,
    USB_OUTPUT_REPORT_SIZE,
    build_usb_output_report,
)


class FakeDevice:
    def __init__(self) -> None:
        self.opened_path: object | None = None
        self.writes: list[bytes] = []
        self.closed = False
        self.write_result: int | None = None

    def open_path(self, path: object) -> None:
        self.opened_path = path

    def write(self, report: bytes) -> int:
        packet = bytes(report)
        self.writes.append(packet)
        if self.write_result is not None:
            return self.write_result
        return len(packet)

    def close(self) -> None:
        self.closed = True


class FakeHid:
    BUS_USB = 1
    BUS_BLUETOOTH = 2

    def __init__(self, devices: list[dict[str, object]]) -> None:
        self.devices = devices
        self.handle = FakeDevice()

    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]:
        return [
            info
            for info in self.devices
            if info.get("vendor_id") == vendor_id
            and info.get("product_id") == product_id
        ]

    def device(self) -> FakeDevice:
        return self.handle


def sony_device(path: bytes, product_id: int, bus_type: int | None) -> dict[str, object]:
    result: dict[str, object] = {
        "path": path,
        "vendor_id": 0x054C,
        "product_id": product_id,
    }
    if bus_type is not None:
        result["bus_type"] = bus_type
    return result


class PacketBuilderTests(unittest.TestCase):
    def test_builds_exact_usb_report_without_rumble_flag(self) -> None:
        report = build_usb_output_report(255, 128, 1, 5, 7)

        self.assertEqual(len(report), USB_OUTPUT_REPORT_SIZE)
        self.assertEqual(
            report[:11],
            bytes([0x05, 0x06, 0, 0, 0, 0, 255, 128, 1, 5, 7]),
        )
        self.assertEqual(report[11:], bytes(21))
        self.assertEqual(report[1] & 0x01, 0, "o report nao pode validar rumble")

    def test_accepts_byte_boundaries(self) -> None:
        report = build_usb_output_report(0, 255, 0, 0, 255)
        self.assertEqual((report[6], report[7], report[8]), (0, 255, 0))
        self.assertEqual((report[9], report[10]), (0, 255))

    def test_rejects_invalid_fields(self) -> None:
        with self.assertRaises(ValueError):
            build_usb_output_report(256, 0, 0)
        with self.assertRaises(ValueError):
            build_usb_output_report(0, 0, 0, -1, 0)
        with self.assertRaises(TypeError):
            build_usb_output_report(True, 0, 0)


class DS4LightbarTests(unittest.TestCase):
    def make_backend(self) -> FakeHid:
        return FakeHid(
            [sony_device(b"hid#vid_054c&pid_09cc&mi_03#usb", 0x09CC, 1)]
        )

    def test_prefers_usb_over_bluetooth(self) -> None:
        bluetooth_path = b"hid#bthenum#{00001124-0000-1000-8000-00805f9b34fb}"
        usb_path = b"hid#vid_054c&pid_09cc&mi_03#usb"
        backend = FakeHid(
            [
                sony_device(bluetooth_path, 0x05C4, 2),
                sony_device(usb_path, 0x09CC, 1),
            ]
        )

        lightbar = DS4Lightbar(hid_backend=backend)
        self.assertEqual(backend.handle.opened_path, usb_path)
        self.assertEqual(backend.handle.writes, [])
        lightbar.close()

    def test_legacy_enumeration_uses_windows_usb_path(self) -> None:
        bluetooth_path = b"hid#{00001124-0000-1000-8000-00805f9b34fb}_vid&0002054c_pid&09cc"
        usb_path = b"hid#vid_054c&pid_09cc&mi_03"
        backend = FakeHid(
            [
                sony_device(bluetooth_path, 0x09CC, None),
                sony_device(usb_path, 0x09CC, None),
            ]
        )

        lightbar = DS4Lightbar(hid_backend=backend)
        self.assertEqual(backend.handle.opened_path, usb_path)
        lightbar.close()

    def test_rejects_bluetooth_only_and_missing_backend(self) -> None:
        backend = FakeHid(
            [sony_device(b"hid#bthenum#controller", 0x09CC, 2)]
        )
        with self.assertRaises(DS4NotFoundError):
            DS4Lightbar(hid_backend=backend)
        with self.assertRaises(HIDUnavailableError):
            DS4Lightbar(hid_backend=None)

    def test_set_rgb_writes_steady_color(self) -> None:
        backend = self.make_backend()
        lightbar = DS4Lightbar(hid_backend=backend)

        lightbar.set_rgb(255, 160, 0)

        report = backend.handle.writes[-1]
        self.assertEqual((report[6], report[7], report[8]), (255, 160, 0))
        self.assertEqual((report[9], report[10]), (0, 0))
        self.assertEqual(lightbar.rgb, (255, 160, 0))
        self.assertFalse(lightbar.is_flashing)
        lightbar.close()

    def test_flash_converts_milliseconds_and_can_use_current_color(self) -> None:
        backend = self.make_backend()
        lightbar = DS4Lightbar(hid_backend=backend)
        lightbar.set_rgb(255, 0, 0)

        lightbar.flash(on_ms=50, off_ms=70)

        report = backend.handle.writes[-1]
        self.assertEqual((report[6], report[7], report[8]), (255, 0, 0))
        self.assertEqual((report[9], report[10]), (5, 7))
        self.assertTrue(lightbar.is_flashing)
        lightbar.close()

    def test_flash_can_replace_color_and_clear_keeps_it(self) -> None:
        backend = self.make_backend()
        lightbar = DS4Lightbar(hid_backend=backend)

        lightbar.flash(255, 32, 0, on_ms=100, off_ms=120)
        lightbar.clear_flash()

        self.assertEqual(lightbar.rgb, (255, 32, 0))
        self.assertEqual((backend.handle.writes[-1][9], backend.handle.writes[-1][10]), (0, 0))
        self.assertFalse(lightbar.is_flashing)
        lightbar.close()

    def test_flash_validates_complete_rgb_and_native_granularity(self) -> None:
        backend = self.make_backend()
        lightbar = DS4Lightbar(hid_backend=backend)
        with self.assertRaises(ValueError):
            lightbar.flash(255, None, 0)
        with self.assertRaises(ValueError):
            lightbar.flash(on_ms=55, off_ms=50)
        with self.assertRaises(ValueError):
            lightbar.flash(on_ms=0, off_ms=50)
        self.assertEqual(backend.handle.writes, [])
        lightbar.close()

    def test_close_stops_active_flash_and_is_idempotent(self) -> None:
        backend = self.make_backend()
        lightbar = DS4Lightbar(hid_backend=backend)
        lightbar.flash(255, 0, 0)

        lightbar.close()
        lightbar.close()

        self.assertEqual(len(backend.handle.writes), 2)
        self.assertEqual((backend.handle.writes[-1][9], backend.handle.writes[-1][10]), (0, 0))
        self.assertTrue(backend.handle.closed)
        self.assertFalse(lightbar.is_open)
        with self.assertRaises(DS4ClosedError):
            lightbar.set_rgb(1, 2, 3)

    def test_short_write_has_clear_error_and_does_not_commit_state(self) -> None:
        backend = self.make_backend()
        backend.handle.write_result = 12
        lightbar = DS4Lightbar(hid_backend=backend)

        with self.assertRaisesRegex(DS4WriteError, "12 de 32 bytes"):
            lightbar.set_rgb(10, 20, 30)

        self.assertEqual(lightbar.rgb, (0, 0, 0))
        lightbar.close()


if __name__ == "__main__":
    unittest.main()
