"""Recebe apenas a telemetria local do protocolo Nebula instalado no BeamNG."""
from __future__ import annotations

import math
import socket
import struct
import threading
import time

PORT = 29878
PACKET = struct.Struct('<4sIIIfff')
PACKET_V2 = struct.Struct('<4sIIIfffI')
TIMEOUT = 1.0


def decode_packet(data):
    if len(data) not in (PACKET.size, PACKET_V2.size):
        raise ValueError('Tamanho de telemetria invalido.')
    magic, version, sequence, flags, pressure, maximum, rpm = PACKET.unpack(data[:PACKET.size])
    if magic != b'NBTG' or (version, len(data)) not in ((1, PACKET.size), (2, PACKET_V2.size)) or flags & ~3:
        raise ValueError('Protocolo de turbo invalido.')
    if not all(math.isfinite(v) for v in (pressure, maximum, rpm)):
        raise ValueError('Telemetria nao finita.')
    if not (-1 <= pressure <= 20 and 0 <= maximum <= 20 and 0 <= rpm <= 50000):
        raise ValueError('Telemetria fora da faixa.')
    return {'sequence': sequence, 'valid': bool(flags & 1), 'has_turbo': bool(flags & 2),
            'turbo_bar': pressure, 'max_turbo_bar': maximum, 'rpm': rpm,
            'afterfire': PACKET_V2.unpack(data)[-1] if version == 2 else None}


class BeamngTurbo:
    def __init__(self, port=PORT, clock=time.monotonic):
        self.port, self.clock = port, clock
        self._lock = threading.Lock()
        self._socket = None
        self._stop = threading.Event()
        self._thread = None
        self._sample = None
        self._last = None
        self._error = None

    def start(self):
        with self._lock:
            if self._socket is not None:
                return
            receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                receiver.bind(('127.0.0.1', self.port))
                receiver.settimeout(0.25)
            except OSError as exc:
                receiver.close()
                self._error = str(exc)
                return
            self._socket = receiver
            self._error = None
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, args=(receiver,), daemon=True, name='Nebula-BeamNG-Turbo')
            self._thread.start()

    def ingest(self, data, origin='127.0.0.1'):
        if origin != '127.0.0.1':
            return False
        try:
            sample = decode_packet(data)
        except ValueError:
            return False
        now = self.clock()
        with self._lock:
            if self._sample is not None and self._last is not None and now-self._last <= TIMEOUT:
                delta = (sample['sequence']-self._sample['sequence']) & 0xFFFFFFFF
                if not 0 < delta < 0x80000000:
                    return False
            self._sample, self._last = sample, now
        return True

    def _loop(self, receiver):
        while not self._stop.is_set():
            try:
                data, origin = receiver.recvfrom(PACKET_V2.size+1)
            except socket.timeout:
                continue
            except OSError:
                break
            self.ingest(data, origin[0])

    def status(self):
        with self._lock:
            fresh = self._last is not None and self.clock()-self._last <= TIMEOUT
            sample = self._sample or {}
            valid = fresh and sample.get('valid', False)
            has_turbo = valid and sample.get('has_turbo', False)
            return {'source': 'beamng', 'unit': 'bar', 'receiving': fresh, 'valid': valid,
                    'rpm': sample.get('rpm') if valid else None,
                    'afterfire': sample.get('afterfire') if valid else None,
                    'has_turbo': has_turbo,
                    'turbo_bar': sample.get('turbo_bar') if has_turbo else None,
                    'max_turbo_bar': sample.get('max_turbo_bar') if has_turbo else None,
                    'status': 'error' if self._error else 'live' if has_turbo else 'no_turbo' if valid else 'waiting',
                    'error': self._error}

    def close(self):
        self._stop.set()
        with self._lock:
            receiver, self._socket = self._socket, None
            self._sample, self._last = None, None
        if receiver:
            receiver.close()
        if self._thread:
            self._thread.join(timeout=1)


SENSOR = BeamngTurbo()
