"""Experimental CSI periodicity estimator; it is not a medical heart-rate sensor.

Only actual complex CSI samples are accepted. RSSI, Wi-Fi discovery and ping
latency cannot supply this input. Quality gates reduce, but cannot eliminate,
false identification of motion/respiration harmonics as cardiac activity.
"""

from __future__ import annotations

from collections import deque
import math
import statistics
import threading
import time
from typing import Callable

MIN_SECONDS = 24.0
WINDOW_SECONDS = 30.0
MIN_RATE_HZ = 10.0
STALE_SECONDS = 5.0
MAX_SAMPLES = 4096
MAX_BATCH = 512
MAX_CARRIERS = 256
NOTICE = "Estimativa experimental de periodicidade CSI; não validada clinicamente."


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve ser um número finito.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} deve ser um número finito.")
    return value


def _detrend(values: list[float]) -> list[float]:
    count = len(values)
    center = (count - 1) / 2
    average = statistics.fmean(values)
    slope = sum((i - center) * (v - average) for i, v in enumerate(values))
    slope /= sum((i - center) ** 2 for i in range(count)) or 1
    return [v - average - slope * (i - center) for i, v in enumerate(values)]


def _spectrum(values: list[float], rate: float) -> list[tuple[float, float]]:
    """Hann-windowed Goertzel powers; no NumPy/native runtime required."""
    count = len(values)
    centered = _detrend(values)
    tapered = [v * (0.5 - 0.5 * math.cos(2 * math.pi * i / (count - 1)))
               for i, v in enumerate(centered)]
    result = []
    for index in range(max(1, math.ceil(0.1 * count / rate)),
                       math.floor(3.1 * count / rate) + 1):
        frequency = index * rate / count
        coefficient = 2 * math.cos(2 * math.pi * index / count)
        previous = previous2 = 0.0
        for value in tapered:
            current = value + coefficient * previous - previous2
            previous2, previous = previous, current
        power = max(0.0, previous * previous + previous2 * previous2
                    - coefficient * previous * previous2)
        result.append((frequency, power))
    return result


def _peak(spectrum: list[tuple[float, float]], low: float, high: float
          ) -> tuple[float, float, float]:
    indices = [i for i, (f, _) in enumerate(spectrum) if low <= f <= high]
    best = max(indices, key=lambda i: spectrum[i][1])
    total = sum(spectrum[i][1] for i in indices)
    local = sum(spectrum[i][1] for i in indices if abs(i - best) <= 1)
    frequency, power = spectrum[best]
    if 0 < best < len(spectrum) - 1:
        # Log-parabolic interpolation improves the frequency between DFT bins.
        a, b, c = [math.log(max(spectrum[i][1], 1e-30))
                   for i in (best - 1, best, best + 1)]
        denominator = a - 2 * b + c
        offset = 0.5 * (a - c) / denominator if denominator else 0
        if abs(offset) <= 0.5:
            frequency += offset * (spectrum[best + 1][0] - spectrum[best][0])
    return frequency, local / total if total else 0.0, power


def _resample(rows: list[tuple[float, tuple[float, ...]]], carrier: int,
              rate: float) -> list[float]:
    """Bin-average dense captures, then interpolate only small empty bins."""
    start, end = rows[0][0], rows[-1][0]
    count = math.floor((end - start) * rate) + 1
    buckets: list[list[float]] = [[] for _ in range(count)]
    for timestamp, amplitudes in rows:
        index = min(count - 1, max(0, round((timestamp - start) * rate)))
        buckets[index].append(amplitudes[carrier])
    values = [statistics.fmean(bucket) if bucket else None for bucket in buckets]
    known = [i for i, value in enumerate(values) if value is not None]
    for left, right in zip(known, known[1:]):
        for i in range(left + 1, right):
            values[i] = values[left] + (values[right] - values[left]) * (i - left) / (right - left)
    return [float(v if v is not None else values[known[-1]]) for v in values]


class WifiBpmSensor:
    """Thread-safe, memory-only ingestion and rate-limited signal analysis."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._rows: deque[tuple[float, tuple[float, ...]]] = deque(maxlen=MAX_SAMPLES)
        self._source = ""
        self._layout = ""
        self._width = 0
        self._cached: dict | None = None
        self._analysed_at = -math.inf
        self._generation = 0
        self._cached_generation = -1

    def reset(self) -> dict:
        with self._lock:
            self._rows.clear()
            self._source = self._layout = ""
            self._width = 0
            self._cached = None
            self._analysed_at = -math.inf
            self._generation += 1
            return self._base("hardware_required", "Conecte um receptor compatível com CSI Wi-Fi.")

    def _base(self, state: str, message: str, **extra) -> dict:
        now = self._clock()
        duration = self._rows[-1][0] - self._rows[0][0] if self._rows else 0.0
        result = {
            "status": state, "bpm": None, "quality": 0.0,
            "message": message, "experimental": True, "notice": NOTICE,
            "samples": len(self._rows), "window_seconds": round(duration, 2),
            "minimum_window_seconds": MIN_SECONDS,
            "sample_rate_hz": round((len(self._rows) - 1) / duration, 1) if duration else 0.0,
            "last_sample_age_seconds": round(max(0.0, now - self._rows[-1][0]), 2) if self._rows else None,
            "source": self._source or None,
        }
        result.update(extra)
        return result

    def ingest(self, payload: dict) -> dict:
        """Accept {source, layout?, timestamp, csi:[[real,imag],...]} or samples.

        Batch format: {source, layout?, samples:[{timestamp,csi}, ...]}.
        Timestamps are capture time in UNIX seconds, increasing within a stream.
        The caller owns authentication and request-size limits.
        Validation is atomic: a malformed batch never partially changes state.
        """
        if not isinstance(payload, dict):
            raise ValueError("Envie um objeto JSON com amostras CSI.")
        source = payload.get("source")
        layout = payload.get("layout", "default")
        if not isinstance(source, str) or not source.strip() or len(source) > 100:
            raise ValueError("source deve identificar o receptor CSI (até 100 caracteres).")
        if not isinstance(layout, str) or not layout.strip() or len(layout) > 150:
            raise ValueError("layout deve identificar canal, antena e subportadoras.")
        samples = payload.get("samples", [payload])
        if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_BATCH:
            raise ValueError(f"Envie de 1 a {MAX_BATCH} amostras por lote.")
        rows = []
        width = None
        now = self._clock()
        for sample in samples:
            if not isinstance(sample, dict):
                raise ValueError("Cada amostra precisa de timestamp e csi.")
            timestamp = _number(sample.get("timestamp"), "timestamp")
            if timestamp <= 0 or timestamp > now + 2 or timestamp < now - WINDOW_SECONDS - STALE_SECONDS:
                raise ValueError("timestamp deve usar segundos UNIX de uma captura recente (até 35 s).")
            if rows and timestamp <= rows[-1][0]:
                raise ValueError("Timestamps devem ser estritamente crescentes.")
            csi = sample.get("csi")
            if not isinstance(csi, list) or not 4 <= len(csi) <= MAX_CARRIERS:
                raise ValueError("csi precisa de 4 a 256 pares [real, imaginário]; RSSI não é CSI.")
            amplitudes = []
            for pair in csi:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError("Cada subportadora CSI deve ser um par [real, imaginário].")
                real, imaginary = (_number(pair[0], "CSI real"), _number(pair[1], "CSI imaginário"))
                if max(abs(real), abs(imaginary)) > 1_000_000:
                    raise ValueError("Amplitude CSI fora do limite aceito.")
                amplitudes.append(math.hypot(real, imaginary))
            if width is not None and width != len(amplitudes):
                raise ValueError("Todas as amostras devem usar as mesmas subportadoras.")
            width = len(amplitudes)
            rows.append((timestamp, tuple(amplitudes)))
        if now - rows[-1][0] > STALE_SECONDS:
            raise ValueError("Lote antigo: a última captura precisa ter no máximo 5 segundos.")
        with self._lock:
            if self._rows:
                if source != self._source or layout != self._layout or width != self._width:
                    raise ValueError("Reinicie a coleta antes de trocar receptor, layout ou subportadoras.")
                if rows[0][0] <= self._rows[-1][0]:
                    raise ValueError("A captura já foi recebida ou está fora de ordem.")
                if rows[0][0] - self._rows[-1][0] > 0.5:
                    self._rows.clear()
                    self._cached = None
            self._source, self._layout, self._width = source, layout, width
            self._rows.extend(rows)
            cutoff = self._rows[-1][0] - WINDOW_SECONDS
            while self._rows and self._rows[0][0] < cutoff:
                self._rows.popleft()
            self._generation += 1
            return self.status()

    def status(self) -> dict:
        with self._lock:
            if not self._rows:
                return self._base("hardware_required", "Conecte um receptor compatível com CSI Wi-Fi.")
            now = self._clock()
            if now - self._rows[-1][0] > STALE_SECONDS:
                return self._base("stale", "O receptor parou de enviar CSI. BPM ocultado.")
            if self._rows[-1][0] - self._rows[0][0] < MIN_SECONDS:
                return self._base("collecting", "Coletando: mantenha uma pessoa imóvel durante pelo menos 24 segundos.")
            if self._cached is not None and (
                    self._generation == self._cached_generation or now - self._analysed_at < 1.0):
                return self._base(**self._cached)
            self._cached = self._analyse(list(self._rows))
            self._cached_generation = self._generation
            self._analysed_at = now
            return self._base(**self._cached)

    def _analyse(self, rows: list[tuple[float, tuple[float, ...]]]) -> dict:
        def reject(message: str) -> dict:
            return {"state": "poor_signal", "message": message}

        intervals = [b[0] - a[0] for a, b in zip(rows, rows[1:])]
        mean_interval = statistics.fmean(intervals)
        rate = 1 / mean_interval
        if rate < MIN_RATE_HZ - 0.05 or max(intervals) > 0.25:
            return reject("CSI insuficiente: capture pelo menos 10 amostras/s, sem lacunas maiores que 250 ms.")
        if statistics.pstdev(intervals) / mean_interval > 0.6:
            return reject("Cadência CSI irregular. Estabilize o emissor e a conexão do receptor.")
        carrier_stats = []
        for carrier in range(self._width):
            values = [row[1][carrier] for row in rows]
            average = statistics.fmean(values)
            deviation = statistics.pstdev(values)
            relative = deviation / max(average, 1e-12)
            if average > 1e-8 and 1e-5 < relative < 0.15:
                carrier_stats.append((relative, carrier))
        if len(carrier_stats) < 3:
            return reject("Sinal plano, fraco ou com movimento excessivo; ajuste as antenas e permaneça imóvel.")
        # Bound CPU: analyze at most six varying carriers at at most 20 Hz.
        candidates = []
        for _, carrier in sorted(carrier_stats, reverse=True)[:6]:
            values = _resample(rows, carrier, min(20.0, rate))
            average = statistics.fmean(values)
            if max(abs(b - a) for a, b in zip(values, values[1:])) / max(average, 1e-12) > 0.12:
                continue
            spectrum = _spectrum(values, min(20.0, rate))
            frequency, purity, power = _peak(spectrum, 0.75, 3.0)
            cardiac_power = sum(p for f, p in spectrum if 0.75 <= f <= 3.0)
            total_power = sum(p for _, p in spectrum)
            if purity < 0.6 or cardiac_power / max(total_power, 1e-30) < 0.2:
                continue
            respiration, _, respiration_power = _peak(spectrum, 0.1, 0.6)
            harmonic = frequency / respiration
            if respiration_power > power * 0.5 and 2 <= round(harmonic) <= 8 and abs(harmonic - round(harmonic)) < 0.15:
                continue
            halves = (values[:len(values) // 2], values[len(values) // 2:])
            peaks = [_peak(_spectrum(half, min(20.0, rate)), 0.75, 3.0) for half in halves]
            if any(abs(f - frequency) * 60 > 6 or quality < 0.5 for f, quality, _ in peaks):
                continue
            candidates.append((frequency * 60, purity))
        if len(candidates) < 3:
            return reject("Sem periodicidade estável em três subportadoras; movimento, respiração ou ruído podem dominar.")
        center = statistics.median(bpm for bpm, _ in candidates)
        agreeing = [(bpm, purity) for bpm, purity in candidates if abs(bpm - center) <= 6]
        if len(agreeing) < 3 or len(agreeing) / len(candidates) < 0.75:
            return reject("As subportadoras discordam; não é possível estimar BPM nesta janela.")
        bpm = statistics.fmean(bpm for bpm, _ in agreeing)
        if not 45 <= bpm <= 180:
            return reject("Periodicidade fora da faixa experimental de 45 a 180 BPM.")
        quality = min(0.99, statistics.fmean(purity for _, purity in agreeing) * len(agreeing) / len(candidates))
        return {"state": "experimental_estimate", "message": NOTICE,
                "bpm": round(bpm, 1), "quality": round(quality, 2),
                "agreeing_subcarriers": len(agreeing), "analyzed_at": self._clock()}


SENSOR = WifiBpmSensor()


def status() -> dict:
    return SENSOR.status()


def ingest(payload: dict) -> dict:
    return SENSOR.ingest(payload)


def reset() -> dict:
    return SENSOR.reset()
