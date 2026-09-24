"""Flash sobre o efeito atual; um único escritor mantém a posse de cada USB."""
import threading
import time
from beamng_turbo import SENSOR


FLASH_COLOR = (255, 195, 45)
FLASH_CURVE = (0.18, 0.42, 0.65, 0.42, 0.18)
FLASH_STEP_SECONDS = 0.045


class ExhaustFlash:
    def __init__(self, device, keyboard=False, lamp=False, close_device=True, sensor=SENSOR):
        self.device, self.keyboard, self.lamp, self.close_device, self.sensor = device, keyboard, lamp, close_device, sensor
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._method = "rgb" if lamp else "enviar_rgb" if keyboard else "set_rgb"
        self._base = (self._method, (255, 244, 224) if lamp else (0, 0, 0), {})
        self._flashing = False
        self.error = None
        sensor.start()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Nebula-Exhaust-Flash")
        self._thread.start()

    def __getattr__(self, name):
        return getattr(self.device, name)

    def _output(self, name, *args, **kwargs):
        with self._lock:
            self._base = (name, args, kwargs)
            if not self._flashing:
                getattr(self.device, name)(*args, **kwargs)

    def set_rgb(self, *rgb): self._output("set_rgb", *rgb)
    def enviar_rgb(self, *rgb): self._output("enviar_rgb", *rgb)
    def rgb(self, *rgb): self._output("rgb", *rgb)
    def enviar_rgb_animacao(self, *rgb): self._output("enviar_rgb_animacao", *rgb)
    def enviar_zonas(self, colors): self._output("enviar_zonas", tuple(colors))
    def enviar_ambilight(self, colors):
        name = "enviar_ambilight" if hasattr(self.device, "enviar_ambilight") else "enviar_zonas"
        self._output(name, tuple(colors))
    def set_boost(self, percent): self._output("set_boost", percent)
    def flash(self, *args, **kwargs): self._output("flash", *args, **kwargs)
    def restaurar(self): self._output("restaurar")

    @staticmethod
    def _mix(base, alpha):
        return tuple(
            round(current + (flash - current) * alpha)
            for current, flash in zip(base, FLASH_COLOR)
        )

    def _render_flash(self, alpha):
        name, args, _kwargs = self._base
        if name in {"enviar_zonas", "enviar_ambilight"} and args:
            colors = tuple(self._mix(color, alpha) for color in args[0])
            method = name if hasattr(self.device, name) else "enviar_zonas"
            getattr(self.device, method)(colors)
            return
        if name in {"set_rgb", "enviar_rgb", "rgb", "enviar_rgb_animacao"} and len(args) >= 3:
            getattr(self.device, name)(*self._mix(args[:3], alpha))
            return
        getattr(self.device, self._method)(*FLASH_COLOR)

    def _loop(self):
        previous = None
        last_flash = 0.0
        try:
            while not self._stop.wait(.025):
                count = self.sensor.status().get("afterfire")
                if count is None:
                    previous = None
                    continue
                delta = 0 if previous is None else (count-previous) & 0xffffffff
                previous = count
                if not 0 < delta < 0x80000000 or time.monotonic()-last_flash < .45:
                    continue
                with self._lock:
                    self._flashing = True
                last_flash = time.monotonic()
                for alpha in FLASH_CURVE:
                    with self._lock:
                        self._render_flash(alpha)
                    if self._stop.wait(FLASH_STEP_SECONDS):
                        break
                with self._lock:
                    name, args, kwargs = self._base
                    getattr(self.device, name)(*args, **kwargs)
                    self._flashing = False
        except Exception as exc:
            self.error = str(exc)
            self._flashing = False

    def close(self):
        self._stop.set()
        self._thread.join(timeout=3)
        with self._lock:
            if self.close_device and hasattr(self.device, "close"):
                self.device.close()
