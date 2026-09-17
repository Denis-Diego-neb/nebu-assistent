"""Controle direto da lightbar de um DualShock 4 Sony conectado por USB.

O modulo pode ser importado sem a dependencia ``hidapi`` instalada. A
dependencia (importada como ``hid``) e o controle fisico so sao necessários
quando :class:`DS4Lightbar` e instanciada.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    import hid as _hid
except ImportError:  # O builder puro deve continuar disponivel sem hidapi.
    _hid = None


SONY_VENDOR_ID = 0x054C
DS4_PRODUCT_IDS = (0x05C4, 0x09CC)

USB_OUTPUT_REPORT_ID = 0x05
USB_OUTPUT_REPORT_SIZE = 32

OUTPUT_FLAG_LED = 0x02
OUTPUT_FLAG_LED_FLASH = 0x04
OUTPUT_FLAGS_LIGHTBAR = OUTPUT_FLAG_LED | OUTPUT_FLAG_LED_FLASH

_DEFAULT_HID_BACKEND = object()


class DS4LightbarError(RuntimeError):
    """Erro base ao acessar ou controlar a lightbar."""


class HIDUnavailableError(DS4LightbarError):
    """O backend Python HID nao esta disponivel."""


class DS4NotFoundError(DS4LightbarError):
    """Nenhum DualShock 4 Sony USB compativel foi encontrado."""


class DS4ConnectionError(DS4LightbarError):
    """Nao foi possivel abrir ou fechar o controle."""


class DS4WriteError(DS4LightbarError):
    """O Windows/HID nao aceitou um report de saida completo."""


class DS4ClosedError(DS4LightbarError):
    """Uma operacao foi solicitada depois que o controle foi fechado."""


def _validate_byte(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} deve ser um numero inteiro entre 0 e 255.")
    if not 0 <= value <= 255:
        raise ValueError(f"{name} deve estar entre 0 e 255; recebido: {value}.")
    return value


def build_usb_output_report(
    red: int,
    green: int,
    blue: int,
    flash_on: int = 0,
    flash_off: int = 0,
) -> bytes:
    """Monta o output report USB de 32 bytes do DualShock 4.

    ``flash_on`` e ``flash_off`` usam a unidade nativa do controle, 10 ms por
    unidade. Os bits de motor nao sao marcados como validos, portanto este
    report nao solicita nem cancela rumble.
    """

    red = _validate_byte(red, "red")
    green = _validate_byte(green, "green")
    blue = _validate_byte(blue, "blue")
    flash_on = _validate_byte(flash_on, "flash_on")
    flash_off = _validate_byte(flash_off, "flash_off")

    report = bytearray(USB_OUTPUT_REPORT_SIZE)
    report[0] = USB_OUTPUT_REPORT_ID
    report[1] = OUTPUT_FLAGS_LIGHTBAR
    # report[2] e valid_flag1; report[3] e reservado. Ambos ficam em zero.
    # report[4:6] sao os motores. Sem o flag 0x01, eles nao sao alterados.
    report[6] = red
    report[7] = green
    report[8] = blue
    report[9] = flash_on
    report[10] = flash_off
    return bytes(report)


def _path_text(path: object) -> str:
    if isinstance(path, bytes):
        return path.decode("utf-8", errors="replace").lower()
    return str(path).lower()


def _constant_values(backend: object, names: tuple[str, ...]) -> set[object]:
    values: set[object] = set()
    for name in names:
        value = getattr(backend, name, None)
        if value is not None:
            try:
                values.add(value)
            except TypeError:
                pass
    return values


def _transport_kind(info: Mapping[str, object], backend: object) -> str:
    """Retorna ``usb``, ``bluetooth`` ou ``unknown`` para uma enumeracao HID."""

    bus_type = info.get("bus_type")
    if bus_type is not None:
        usb_values = {1} | _constant_values(
            backend,
            ("BUS_USB", "HID_API_BUS_USB"),
        )
        bluetooth_values = {2} | _constant_values(
            backend,
            ("BUS_BLUETOOTH", "HID_API_BUS_BLUETOOTH"),
        )
        if bus_type in usb_values:
            return "usb"
        if bus_type in bluetooth_values:
            return "bluetooth"

        bus_name = getattr(bus_type, "name", str(bus_type)).lower()
        if "usb" in bus_name:
            return "usb"
        if "bluetooth" in bus_name or bus_name in {"bt", "bth"}:
            return "bluetooth"

    path = _path_text(info.get("path", ""))
    bluetooth_markers = (
        "bthenum",
        "bluetooth",
        "{00001124-0000-1000-8000-00805f9b34fb}",
        "_vid&0002",
    )
    if any(marker in path for marker in bluetooth_markers):
        return "bluetooth"

    # No Windows, dispositivos HID USB normalmente usam VID_xxxx&PID_xxxx.
    if "vid_" in path and "pid_" in path:
        return "usb"
    if "usb" in path:
        return "usb"
    return "unknown"


def _enumerate_ds4(backend: object) -> list[Mapping[str, object]]:
    enumerate_devices = getattr(backend, "enumerate", None)
    if not callable(enumerate_devices):
        raise HIDUnavailableError(
            "O modulo 'hid' carregado nao oferece hid.enumerate(). "
            "Instale o pacote 'hidapi'."
        )

    candidates: list[Mapping[str, object]] = []
    seen_paths: set[object] = set()
    try:
        for product_id in DS4_PRODUCT_IDS:
            for raw_info in enumerate_devices(SONY_VENDOR_ID, product_id) or ():
                if not isinstance(raw_info, Mapping):
                    continue
                path = raw_info.get("path")
                if path in (None, b"", ""):
                    continue
                try:
                    path_key: object = path if hash(path) is not None else repr(path)
                except TypeError:
                    path_key = repr(path)
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                candidates.append(raw_info)
    except DS4LightbarError:
        raise
    except Exception as exc:
        raise DS4ConnectionError(
            "Falha ao enumerar controles HID. Verifique a instalacao do hidapi "
            "e reconecte o DualShock 4 por USB."
        ) from exc
    return candidates


def _select_usb_ds4(backend: object) -> Mapping[str, object]:
    candidates = _enumerate_ds4(backend)
    ranked = sorted(
        candidates,
        key=lambda item: {"usb": 0, "unknown": 1, "bluetooth": 2}[
            _transport_kind(item, backend)
        ],
    )
    for info in ranked:
        if _transport_kind(info, backend) != "bluetooth":
            return info

    supported = ", ".join(f"{product_id:04X}" for product_id in DS4_PRODUCT_IDS)
    raise DS4NotFoundError(
        "Nenhum DualShock 4 Sony conectado por USB foi encontrado "
        f"(VID {SONY_VENDOR_ID:04X}; PIDs {supported}). Conecte o controle "
        "por cabo e confirme que ele aparece no Windows."
    )


def _open_hid_path(backend: object, path: object) -> Any:
    legacy_factory = getattr(backend, "device", None)
    if callable(legacy_factory):
        device = legacy_factory()
        open_path = getattr(device, "open_path", None)
        if not callable(open_path):
            close = getattr(device, "close", None)
            if callable(close):
                close()
            raise HIDUnavailableError(
                "O objeto criado por hid.device() nao oferece open_path()."
            )
        open_path(path)
        return device

    device_factory = getattr(backend, "Device", None)
    if callable(device_factory):
        try:
            return device_factory(path=path)
        except TypeError:
            return device_factory(path)

    raise HIDUnavailableError(
        "O modulo 'hid' nao oferece hid.device() nem hid.Device(). "
        "Instale o pacote 'hidapi'."
    )


def _milliseconds_to_units(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} deve ser um numero inteiro de milissegundos.")
    if not 10 <= value <= 2550:
        raise ValueError(f"{name} deve estar entre 10 e 2550 ms; recebido: {value}.")
    if value % 10:
        raise ValueError(f"{name} deve ser multiplo de 10 ms; recebido: {value}.")
    return value // 10


class DS4Lightbar:
    """Dono de uma conexao HID com a lightbar de um DualShock 4 USB."""

    def __init__(self, *, hid_backend: object = _DEFAULT_HID_BACKEND) -> None:
        backend = _hid if hid_backend is _DEFAULT_HID_BACKEND else hid_backend
        if backend is None:
            raise HIDUnavailableError(
                "Backend HID indisponivel. Instale 'hidapi' no ambiente Python "
                "(o modulo importado se chama 'hid')."
            )

        info = _select_usb_ds4(backend)
        path = info["path"]
        try:
            device = _open_hid_path(backend, path)
        except DS4LightbarError:
            raise
        except Exception as exc:
            raise DS4ConnectionError(
                "Nao foi possivel abrir o DualShock 4 USB para escrita HID. "
                "Feche Steam/DS4Windows se outro programa estiver controlando "
                f"a lightbar e tente novamente. Caminho: {path!r}."
            ) from exc

        self._backend = backend
        self._device_info = dict(info)
        self._device: Any | None = device
        self._rgb = (0, 0, 0)
        self._flash_units = (0, 0)

    @property
    def is_open(self) -> bool:
        return self._device is not None

    @property
    def rgb(self) -> tuple[int, int, int]:
        return self._rgb

    @property
    def is_flashing(self) -> bool:
        return self._flash_units != (0, 0)

    @property
    def device_info(self) -> dict[str, object]:
        return dict(self._device_info)

    def _write_state(
        self,
        red: int,
        green: int,
        blue: int,
        flash_on: int,
        flash_off: int,
    ) -> None:
        device = self._device
        if device is None:
            raise DS4ClosedError("O DualShock 4 ja foi fechado.")

        report = build_usb_output_report(
            red,
            green,
            blue,
            flash_on,
            flash_off,
        )
        try:
            written = device.write(report)
        except Exception as exc:
            raise DS4WriteError(
                "Falha ao enviar a cor para o DualShock 4. Verifique o cabo e "
                "se Steam/DS4Windows esta disputando o controle."
            ) from exc

        if written != len(report):
            raise DS4WriteError(
                "O report HID foi enviado parcialmente: "
                f"{written!r} de {len(report)} bytes."
            )

        self._rgb = (red, green, blue)
        self._flash_units = (flash_on, flash_off)

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        """Define uma cor fixa e cancela qualquer pisca anterior."""

        self._write_state(red, green, blue, 0, 0)

    def flash(
        self,
        red: int | None = None,
        green: int | None = None,
        blue: int | None = None,
        *,
        on_ms: int = 50,
        off_ms: int = 50,
    ) -> None:
        """Pisca a cor informada, ou a cor atual, usando o temporizador do DS4."""

        supplied = (red is not None, green is not None, blue is not None)
        if any(supplied) and not all(supplied):
            raise ValueError(
                "Informe red, green e blue juntos, ou omita os tres para "
                "piscar a cor atual."
            )

        if all(supplied):
            rgb = (red, green, blue)
        else:
            rgb = self._rgb

        flash_on = _milliseconds_to_units(on_ms, "on_ms")
        flash_off = _milliseconds_to_units(off_ms, "off_ms")
        self._write_state(
            _validate_byte(rgb[0], "red"),
            _validate_byte(rgb[1], "green"),
            _validate_byte(rgb[2], "blue"),
            flash_on,
            flash_off,
        )

    def clear_flash(self) -> None:
        """Cancela o pisca mantendo a ultima cor selecionada."""

        self._write_state(*self._rgb, 0, 0)

    def close(self) -> None:
        """Cancela um pisca ativo e fecha o handle HID; pode ser chamado de novo."""

        device = self._device
        if device is None:
            return

        pending_error: DS4LightbarError | None = None
        if self.is_flashing:
            try:
                self.clear_flash()
            except DS4LightbarError as exc:
                pending_error = exc

        self._device = None
        close = getattr(device, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                if pending_error is None:
                    pending_error = DS4ConnectionError(
                        "Falha ao fechar a conexao HID do DualShock 4."
                    )
                    pending_error.__cause__ = exc

        if pending_error is not None:
            raise pending_error

    def __enter__(self) -> DS4Lightbar:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            self.close()
        except DS4LightbarError:
            if exc_type is None:
                raise
        return False


__all__ = [
    "DS4_PRODUCT_IDS",
    "SONY_VENDOR_ID",
    "USB_OUTPUT_REPORT_ID",
    "USB_OUTPUT_REPORT_SIZE",
    "DS4Lightbar",
    "DS4LightbarError",
    "HIDUnavailableError",
    "DS4NotFoundError",
    "DS4ConnectionError",
    "DS4WriteError",
    "DS4ClosedError",
    "build_usb_output_report",
]
