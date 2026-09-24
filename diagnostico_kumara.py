r"""Teste isolado: repete um frame completo, sem captura ou deduplicacao.

Execute com a Nebula e o OpenRGB fechados:
  .venv\Scripts\python.exe diagnostico_kumara.py --fps 24 --seconds 20
Nao altera o algoritmo nem o mapeamento do Ambilight.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time

from teclado_evision import TecladoKumaraUSB, encontrar_kumara


class MeasuredHID:
    def __init__(self, device):
        self.device = device
        self.reset()

    def reset(self):
        self.packets = 0
        self.modes = 0
        self.custom = 0
        self.writers = set()

    def write(self, packet):
        self.packets += 1
        writer = getattr(self.device, 'writer_ident', None) or threading.get_ident()
        self.writers.add((os.getpid(), writer))
        if packet[3] == 6 and int.from_bytes(packet[5:7], 'little') == 0:
            self.modes += 1
            self.custom += packet[8] == 20
        return self.device.write(packet)

    def read(self, *args):
        return self.device.read(*args)

    def close(self):
        return self.device.close()


def run(keyboard, measured, *, fps, seconds, color, output, transaction=False,
        burst=False, burst_unconfirmed=False, single_block=False,
        slow_change=False):
    frame = [tuple(color)] * keyboard.LED_COUNT
    if single_block:
        keyboard._frame(frame, force=True, interval=0, burst_unconfirmed=True)
        block = bytes(channel for pixel in frame[:keyboard.BLOCK_SIZE // 3]
                      for channel in pixel)
    start = deadline = time.perf_counter()
    frame_id = 0
    while time.perf_counter() - start < seconds:
        time.sleep(max(0, deadline - time.perf_counter()))
        measured.reset()
        began = time.perf_counter()
        error = None
        try:
            if single_block:
                keyboard._send_block(block, 0)
            elif slow_change:
                phase = frame_id % 128
                delta = phase if phase < 64 else 127 - phase
                changing = [(min(255, color[0] + delta), color[1], color[2])]
                keyboard._frame(changing * keyboard.LED_COUNT, interval=0,
                                burst_unconfirmed=True)
            else:
                # Force bypasses BOTH full-frame and per-block deduplication.
                keyboard._frame(frame, force=True, interval=0,
                                transaction=transaction, burst=burst,
                                burst_unconfirmed=burst_unconfirmed)
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            ended = time.perf_counter()
            output.write(json.dumps(dict(
                timestamp=datetime.now(timezone.utc).isoformat(),
                frame_id=frame_id, target_fps=fps, elapsed_ms=(began-start)*1000,
                capture_ms=None, processing_ms=None, usb_ms=(ended-began)*1000,
                packets=measured.packets, mode_commands=measured.modes,
                custom_reinitializations=measured.custom, clear_reset=False,
                writers=sorted(measured.writers), error=error,
            )) + '\n')
            output.flush()
        frame_id += 1
        deadline += 1 / fps
        # Never catch up by flooding the USB after an overrun.
        if deadline < ended:
            deadline = ended
    return frame_id / (time.perf_counter() - start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fps', type=int, choices=(10, 20, 24, 30), default=24)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--color', type=int, nargs=3, default=(32, 64, 120))
    parser.add_argument('--output', type=Path, default=Path('tmp/kumara-static.jsonl'))
    parser.add_argument('--transaction', action='store_true',
                        help='delimita cada frame com BEGIN/END do protocolo EVision')
    parser.add_argument('--burst', action='store_true',
                        help='escreve todos os pacotes antes de recolher os ecos')
    parser.add_argument('--burst-unconfirmed', action='store_true',
                        help='diagnostico: rajada seguida de drenagem dos ecos')
    parser.add_argument('--single-block', action='store_true',
                        help='repete apenas o primeiro bloco apos montar o frame')
    parser.add_argument('--slow-change', action='store_true',
                        help='varia um canal lentamente e aplica threshold real')
    args = parser.parse_args()
    if not 0 < args.seconds <= 300 or any(not 0 <= c <= 255 for c in args.color):
        parser.error('Use duracao de ate 300 segundos e canais RGB de 0 a 255.')
    import psutil
    competitors = [(p.pid, p.info['name']) for p in psutil.process_iter(['name'])
                   if (p.info['name'] or '').lower().startswith(('nebula-', 'openrgb'))]
    if competitors:
        parser.error(f'Feche os outros controladores antes do teste: {competitors}')
    info = encontrar_kumara()
    if info is None:
        parser.error('Kumara USB 320F:5000 nao encontrado.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TecladoKumaraUSB(info) as keyboard:
        measured = MeasuredHID(keyboard._device)
        keyboard._device = measured
        with args.output.open('w', encoding='utf-8') as output:
            actual = run(keyboard, measured, fps=args.fps, seconds=args.seconds,
                         color=args.color, output=output,
                         transaction=args.transaction, burst=args.burst,
                         burst_unconfirmed=args.burst_unconfirmed,
                         single_block=args.single_block,
                         slow_change=args.slow_change)
    print(f'FPS efetivo: {actual:.2f}; log: {args.output}')
    print('A estabilidade visual precisa ser observada no teclado; ACK nao mede flicker.')


if __name__ == '__main__':
    main()
