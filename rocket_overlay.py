"""HUD externo da Nebula: somente dados disponíveis, sem acesso ao processo do jogo.

Mostra barra de boost, nick opcional e cápsula de coração/BPM.
Não captura imagens nem consulta dados da conta do jogo.
Use o jogo em janela ou sem bordas. Software de terceiros não tem suporte oficial
da Epic; este módulo não declara compatibilidade garantida com anti-cheat.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from typing import Callable


POSITIONS = {"middle_left": "Centro esquerdo", "top_left": "Superior esquerdo", "top_right": "Superior direito", "bottom_left": "Inferior esquerdo"}
WIDTH, HEIGHT = 340, 42
DEFAULT_NICKNAME = "Star"


def _number(value: object, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def overlay_snapshot(sensor: dict | None = None, control: dict | None = None) -> dict:
    """Rejeita medidas ausentes, inválidas ou antigas antes de desenhar o HUD."""
    sensor = sensor or {}
    control = control or {}
    boost = None
    if ((control.get("mode") == "boost" and control.get("receiving") is True and control.get("telemetry_valid") is True)
            or (control.get("mode") == "independent" and control.get("boost_receiving") is True and control.get("boost_valid") is True)):
        boost = _number(control.get("boost_percent"), 0, 100)
    age = _number(sensor.get("last_sample_age_seconds"), 0, 3)
    bpm = None
    if sensor.get("status") == "experimental_estimate" and age is not None:
        bpm = _number(sensor.get("bpm"), 30, 220)
    return {
        "boost_percent": round(boost) if boost is not None else None,
        "bpm": round(bpm) if bpm is not None else None,
        "bpm_experimental": True,
        "source": "wifi-csi" if bpm is not None else None,
        "message": "BPM experimental disponível." if bpm is not None else "Aguardando sensor de BPM.",
    }


def wifi_sensor_status() -> dict:
    try:
        from wifi_bpm import SENSOR
    except ImportError:
        return {}
    return SENSOR.status()


class OverlayBridge:
    """Ponte remota; o handler só enfileira ações para a thread da interface."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handler: Callable[[str, object], None] | None = None
        self._state = {
            "available": False, "enabled": False, "running": False,
            "pending": False, "position": "middle_left", "error": None,
            "nickname": DEFAULT_NICKNAME, "boost_percent": None, "bpm": None, "source": None,
            "message": "Abra a Nebula no PC para usar a overlay.",
        }

    def register(self, handler: Callable[[str, object], None]) -> None:
        with self._lock:
            self._handler = handler
            self._state.update(available=sys.platform == "win32", message="Overlay desligada.")

    def unregister(self) -> None:
        with self._lock:
            self._handler = None
            self._state.update(available=False, enabled=False, running=False, pending=False,
                               boost_percent=None, bpm=None, source=None,
                               message="Abra a Nebula no PC para usar a overlay.")

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def publish(self, **values: object) -> None:
        with self._lock:
            self._state.update(values)
            self._state["running"] = bool(self._state["enabled"])

    def request(self, action: str, value: object = None) -> dict:
        if not isinstance(action, str) or action not in {"start", "stop", "toggle", "position", "nickname"}:
            raise ValueError("Ação de overlay desconhecida.")
        if action == "position" and (not isinstance(value, str) or value not in POSITIONS):
            raise ValueError("Posição de overlay inválida.")
        if action == "nickname" and (not isinstance(value, str) or len(value) > 20 or any(ord(c) < 32 for c in value)):
            raise ValueError("Use um nick com até 20 caracteres, sem quebras de linha.")
        with self._lock:
            handler = self._handler
            if handler is None or not self._state["available"]:
                raise RuntimeError("Abra a interface Nebula no Windows para usar a overlay.")
            if self._state["pending"]:
                raise RuntimeError("Aguarde a solicitação anterior da overlay.")
            self._state.update(pending=True, error=None)
        try:
            handler(action, value)
        except Exception:
            self.publish(pending=False, error="Não foi possível solicitar a overlay.")
            raise
        return {"ok": True, "message": "Solicitação de overlay recebida.", "state": self.status()}


OVERLAY_BRIDGE = OverlayBridge()


class RocketOverlay:
    """Janela Tk sem foco, transparente e com passagem de cliques no Windows."""

    def __init__(self, root, *,
                 control_provider: Callable[[], dict] = lambda: {},
                 sensor_provider: Callable[[], dict] = wifi_sensor_status,
                 bridge: OverlayBridge = OVERLAY_BRIDGE) -> None:
        self.root = root
        self.control_provider = control_provider
        self.sensor_provider = sensor_provider
        self.bridge = bridge
        self.window = None
        self.canvas = None
        self.position = "middle_left"
        self.nickname = DEFAULT_NICKNAME
        self._after = None
        self._last_snapshot = None
        self._next_position = 0.0

    def apply(self, action: str, value: object = None) -> None:
        try:
            if action == "start" or action == "toggle" and self.window is None:
                self.start()
            elif action in {"stop", "toggle"}:
                self.stop()
            elif action == "position":
                if not isinstance(value, str) or value not in POSITIONS:
                    raise ValueError("Posição de overlay inválida.")
                self.position = value
                self._place()
            elif action == "nickname":
                if not isinstance(value, str) or len(value) > 20 or any(ord(c) < 32 for c in value):
                    raise ValueError("Use um nick com até 20 caracteres.")
                self.nickname = value.strip()
                self._last_snapshot = None
            else:
                raise ValueError("Ação de overlay desconhecida.")
            self.bridge.publish(pending=False, position=self.position, nickname=self.nickname)
        except Exception as exc:
            self.bridge.publish(pending=False, error=str(exc), message=str(exc))

    def start(self) -> None:
        if self.window is not None:
            return
        if sys.platform != "win32":
            raise RuntimeError("A overlay com passagem de cliques requer Windows.")
        import tkinter as tk

        window = tk.Toplevel(self.root)
        window.withdraw()
        self.window = window
        try:
            window.title("Nebula HUD")
            window.overrideredirect(True)
            window.configure(bg="#010203")
            window.attributes("-topmost", True)
            window.attributes("-transparentcolor", "#010203")
            window.attributes("-alpha", 0.84)
            self.canvas = tk.Canvas(window, width=WIDTH, height=HEIGHT,
                                    bg="#010203", highlightthickness=0)
            self.canvas.pack()
            self._last_snapshot = None
            self._place()
            window.update_idletasks()
            self._make_click_through()
            window.deiconify()
            self.bridge.publish(enabled=True, error=None)
            self._tick()
        except Exception:
            self.stop()
            raise

    def _make_click_through(self) -> None:
        import win32con
        import win32gui

        handle = win32gui.GetParent(self.window.winfo_id()) or self.window.winfo_id()
        style = win32gui.GetWindowLong(handle, win32con.GWL_EXSTYLE)
        style |= (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT |
                  win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE)
        win32gui.SetWindowLong(handle, win32con.GWL_EXSTYLE, style)
        win32gui.SetWindowPos(handle, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                             win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED)

    def _place(self) -> None:
        if self.window is None:
            return
        left, top = 0, 0
        width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        # A posição acompanha a janela do jogo, inclusive em um segundo monitor.
        # A região inferior direita fica livre para o leitor de boost existente.
        if sys.platform == "win32":
            try:
                import win32gui
                from leitor_boost_visual import LeitorBoostVisual

                handle = LeitorBoostVisual._janela_rocket_league()
                if handle is not None and not win32gui.IsIconic(handle):
                    left, top = win32gui.ClientToScreen(handle, (0, 0))
                    _, _, width, height = win32gui.GetClientRect(handle)
            except (ImportError, OSError):
                pass
        x = left + (max(12, width - WIDTH - 24) if self.position == "top_right" else 24)
        y = top + (max(12, height - HEIGHT - 48) if self.position == "bottom_left" else 100)
        if self.position == "middle_left":
            y = top + max(0, (height - HEIGHT) // 2)
        self.window.geometry(f"{WIDTH}x{HEIGHT}{x:+d}{y:+d}")

    def _tick(self) -> None:
        if self.window is None:
            return
        try:
            snapshot = overlay_snapshot(self.sensor_provider(), self.control_provider())
            self.bridge.publish(**snapshot, enabled=True, error=None)
            if snapshot != self._last_snapshot:
                self._draw(snapshot)
                self._last_snapshot = snapshot
            if time.monotonic() >= self._next_position:
                self._place()
                self._next_position = time.monotonic() + 1.0
        except Exception:
            snapshot = overlay_snapshot({})
            snapshot["message"] = "Dados indisponíveis."
            self._draw(snapshot)
            self._last_snapshot = None
            self.bridge.publish(**snapshot, error="Falha ao atualizar os dados da overlay.")
        self._after = self.root.after(200, self._tick)

    def _draw(self, snapshot: dict) -> None:
        c = self.canvas
        c.delete("all")
        # Faixa de transmissão: o azul é a quantidade de boost, sem número extra.
        def capsule(left, right, color):
            c.create_oval(left, 5, left + 32, 37, fill=color, outline="")
            c.create_rectangle(left + 16, 5, right - 16, 37, fill=color, outline="")
            c.create_oval(right - 32, 5, right, 37, fill=color, outline="")

        capsule(4, 247, "#142949")
        boost = snapshot.get("boost_percent")
        if boost is not None and boost > 0:
            end = 4 + round(243 * boost / 100)
            for x in range(4, end):
                fraction = (x - 4) / 243
                # Recorta o preenchimento nas extremidades semicirculares.
                offset = max(20 - (x + .5), (x + .5) - 231, 0)
                half = math.sqrt(max(0, 16 * 16 - offset * offset))
                color = "#%02x%02x%02x" % (round(40 - 24 * fraction), round(111 - 26 * fraction), round(237 - 22 * fraction))
                c.create_line(x, 21 - half, x, 21 + half, fill=color)
        if self.nickname:
            c.create_text(20, 21, text=self.nickname, anchor="w", fill="#eef6ff",
                          font=("Bahnschrift", 12, "bold"))
        capsule(251, 336, "#101923")
        c.create_text(271, 21, text="♥", fill="#ff9b3d",
                      font=("Segoe UI Symbol", 14))
        bpm = snapshot["bpm"]
        value = str(bpm) if bpm is not None else "—"
        c.create_text(306, 21, text=value, fill="#ff9b3d",
                      font=("Bahnschrift", 17, "bold"))

    def stop(self) -> None:
        if self._after is not None:
            self.root.after_cancel(self._after)
            self._after = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
            self.canvas = None
        self.bridge.publish(enabled=False, pending=False, boost_percent=None, bpm=None,
                            source=None, error=None, message="Overlay desligada.")


def main() -> None:
    """A janela de configuração controla o HUD; não inicia captura do jogo."""
    import argparse
    import tkinter as tk
    from tkinter import ttk
    import json
    from urllib.request import Request, urlopen
    from remote_server import POWER_TOKEN

    parser = argparse.ArgumentParser(description="Overlay: coração, BPM e nick opcional.")
    parser.add_argument("--nickname", default=DEFAULT_NICKNAME)
    args = parser.parse_args()
    root = tk.Tk()
    root.title("Nebula • Overlay BPM")
    root.geometry("510x270")
    root.configure(bg="#091728")
    stop_polling = threading.Event()
    source_lock = threading.Lock()
    source_state = {}
    control_state = {}
    received_at = 0.0

    def read_sensor():
        with source_lock:
            state = dict(source_state)
            age = state.get("last_sample_age_seconds")
            if isinstance(age, (int, float)):
                state["last_sample_age_seconds"] = age + time.monotonic() - received_at
            return state

    def poll_sensor():
        nonlocal source_state, control_state, received_at
        while not stop_polling.is_set():
            if OVERLAY_BRIDGE.status()["running"]:
                try:
                    request = Request("http://127.0.0.1:8765/api/wifi-bpm/status",
                                      headers={"X-Nebula-Power-Token": POWER_TOKEN})
                    with urlopen(request, timeout=2) as response:
                        result = json.loads(response.read(100_000))
                    request = Request("http://127.0.0.1:8765/api/control", headers={"X-Nebula-Power-Token": POWER_TOKEN})
                    with urlopen(request, timeout=2) as response:
                        control = json.loads(response.read(100_000)).get("state", {})
                    with source_lock:
                        source_state = result if isinstance(result, dict) else {}
                        control_state = control if isinstance(control, dict) else {}
                        received_at = time.monotonic()
                except Exception:
                    with source_lock:
                        source_state = {}
                        control_state = {}
            stop_polling.wait(1.0)

    def read_control():
        with source_lock:
            return dict(control_state) if time.monotonic() - received_at <= 3 else {}

    overlay = RocketOverlay(root, sensor_provider=read_sensor, control_provider=read_control)
    overlay.apply("nickname", args.nickname)
    status = tk.StringVar(value="BPM depende de um receptor CSI; a leitura é experimental.")

    def action(name, value=None):
        overlay.apply(name, value)
        status.set(str(OVERLAY_BRIDGE.status()["message"]))

    tk.Label(root, text="♥  BPM", bg="#091728", fg="#42caff",
             font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=24, pady=(20, 8))
    tk.Label(root, text="Nick opcional (deixe vazio para ocultar)", bg="#091728",
             fg="#b5c9e0").pack(anchor="w", padx=24)
    nick = tk.Entry(root, font=("Segoe UI", 12))
    nick.insert(0, args.nickname)
    nick.pack(fill="x", padx=24, pady=5)
    row = tk.Frame(root, bg="#091728")
    row.pack(fill="x", padx=24, pady=10)
    tk.Button(row, text="Mostrar", command=lambda: (action("nickname", nick.get()), action("start")),
              bg="#183551", fg="white", relief="flat", padx=16, pady=8).pack(side="left", padx=(0, 8))
    tk.Button(row, text="Ocultar", command=lambda: action("stop"), bg="#183551", fg="white",
              relief="flat", padx=16, pady=8).pack(side="left", padx=(0, 8))
    position = ttk.Combobox(row, values=list(POSITIONS.values()), state="readonly", width=18)
    position.current(0)
    position.pack(side="left")
    position.bind("<<ComboboxSelected>>", lambda _event: action("position", list(POSITIONS)[position.current()]))
    tk.Label(root, textvariable=status, bg="#091728", fg="#ffad42", wraplength=460,
             justify="left", font=("Segoe UI", 9)).pack(anchor="w", padx=24)
    root.protocol("WM_DELETE_WINDOW", lambda: (stop_polling.set(), overlay.stop(), root.destroy()))
    threading.Thread(target=poll_sensor, daemon=True, name="NebulaBpmOverlay").start()
    root.mainloop()


if __name__ == "__main__":
    main()
