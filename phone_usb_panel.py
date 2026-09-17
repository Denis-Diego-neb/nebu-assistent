"""Abre o mostrador do A71 autorizado quando ele chega ao USB do PC."""
import json
import os
from pathlib import Path
import subprocess
import threading
from urllib.request import Request, urlopen

SERIAL = 'RQ8NA0AXH8M'


class UsbPanel:
    def __init__(self, token):
        self.token = token
        self.adb = Path(os.environ.get('LOCALAPPDATA', '')) / 'Android/Sdk/platform-tools/adb.exe'
        self.opened = False

    def command(self, *args):
        result = subprocess.run([str(self.adb), '-s', SERIAL, *args],
                                capture_output=True, text=True, timeout=8,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise OSError('A71 indisponivel no USB autorizado.')
        return result.stdout

    def tick(self):
        if not self.adb.is_file():
            return
        try:
            connected = self.command('get-state').strip() == 'device'
        except (OSError, subprocess.SubprocessError):
            connected = False
        if not connected:
            self.opened = False
            return
        if self.opened:
            return
        request = Request('http://127.0.0.1:8765/api/control',
                          headers={'X-Nebula-Power-Token': self.token})
        with urlopen(request, timeout=3) as response:
            payload = json.load(response)
        state = payload.get('state', payload)
        if state.get('devices', {}).get('mobile', {}).get('mode') not in ('rpm', 'turbo'):
            return
        self.command('reverse', 'tcp:8765', 'tcp:8765')
        output = self.command('shell', 'am', 'start', '-a', 'com.nebula.assistant.SHOW_GAUGE',
                              '-n', 'com.nebula.assistant/.MainActivity')
        if 'Error' in output or 'Exception' in output:
            raise OSError('Nao foi possivel abrir o mostrador no A71.')
        self.opened = True


def start_usb_panel_watcher(token):
    stop = threading.Event()
    panel = UsbPanel(token)
    def run():
        while not stop.is_set():
            try:
                panel.tick()
            except (OSError, ValueError, subprocess.SubprocessError):
                pass  # Tenta novamente quando USB e painel estiverem disponiveis.
            stop.wait(5)
    threading.Thread(target=run, daemon=True, name='Nebula-A71-USB').start()
    return stop
