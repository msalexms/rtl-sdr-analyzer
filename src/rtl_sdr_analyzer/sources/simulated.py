"""Deterministic/realistic RF signal simulator for testing and hardware-free demos."""

import math
import threading
import time
from dataclasses import dataclass
from types import TracebackType

import numpy as np

from .base import DeviceInfo, SDRDisconnectedError


@dataclass(frozen=True)
class _VirtualCarrier:
    freq_hz: float
    amplitude: float
    bw_hz: float = 0.0
    burst_period_s: float = 0.0
    burst_duty: float = 1.0


_VIRTUAL_CARRIERS: tuple[_VirtualCarrier, ...] = (
    # FM broadcast band (MHz)
    _VirtualCarrier(98.1e6, 0.16, bw_hz=90_000.0),
    _VirtualCarrier(98.5e6, 0.24, bw_hz=110_000.0),
    _VirtualCarrier(99.1e6, 0.09, bw_hz=80_000.0),
    _VirtualCarrier(100.3e6, 0.20, bw_hz=100_000.0),
    _VirtualCarrier(102.7e6, 0.14, bw_hz=90_000.0),
    # Airband beacon
    _VirtualCarrier(121.5e6, 0.18, bw_hz=8_000.0, burst_period_s=6.0, burst_duty=0.45),
    # ISM 433.92 MHz OOK burst
    _VirtualCarrier(433.92e6, 0.28, bw_hz=25_000.0, burst_period_s=5.0, burst_duty=0.5),
    # PMR446 walkie-talkie burst
    _VirtualCarrier(446.00625e6, 0.32, bw_hz=12_500.0, burst_period_s=4.5, burst_duty=0.55),
    _VirtualCarrier(446.05625e6, 0.14, bw_hz=12_500.0),
    # ISM 868.3 / 915 MHz
    _VirtualCarrier(868.3e6, 0.25, bw_hz=35_000.0, burst_period_s=5.0, burst_duty=0.5),
    _VirtualCarrier(915.0e6, 0.28, bw_hz=45_000.0, burst_period_s=4.0, burst_duty=0.6),
    # ADS-B 1090 MHz
    _VirtualCarrier(1090.0e6, 0.22, bw_hz=120_000.0, burst_period_s=3.5, burst_duty=0.4),
)

_SIM_GAINS: list[float] = [0.0, 8.7, 14.4, 20.7, 29.7, 36.4, 42.1, 49.6]


class SimulatedSource:
    """Realistic RF IQ stream source requiring no physical RTL-SDR dongle."""

    source_type: str = "simulated"

    def __init__(
        self,
        center_freq: float = 98.0e6,
        sample_rate: float = 2.048e6,
        gain: float | None = None,
        ppm: int = 0,
        realtime: bool = True,
        noise_std: float = 0.008,
        seed: int = 42,
    ) -> None:
        self.center_freq = float(center_freq)
        self.sample_rate = float(sample_rate)
        self.gain = gain
        self.ppm = int(ppm)
        self.realtime = realtime
        self.noise_std = float(noise_std)

        self._lock = threading.RLock()
        self._open = False
        self._rng = np.random.default_rng(seed)
        self._sample_cursor = 0
        self._last_read_time = 0.0
        self._info = DeviceInfo(
            index=0,
            name="Simulated RF Source (AMSTech Demo)",
            source_type="simulated",
            tuner="VIRTUAL",
            supported_gains=list(_SIM_GAINS),
            connected=False,
            detail="FM / ISM / PMR446 / ADS-B virtual carriers",
        )

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    @property
    def info(self) -> DeviceInfo:
        with self._lock:
            return self._info.model_copy()

    def __enter__(self) -> "SimulatedSource":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def open(self) -> None:
        with self._lock:
            self._open = True
            self._last_read_time = time.monotonic()
            self._info = self._info.model_copy(update={"connected": True})

    def close(self) -> None:
        with self._lock:
            self._open = False
            self._info = self._info.model_copy(update={"connected": False})

    def read_samples(self, num_samples: int) -> np.ndarray:
        """Generate ``num_samples`` realistic complex64 RF samples."""
        if num_samples <= 0:
            return np.empty(0, dtype=np.complex64)

        with self._lock:
            if not self._open:
                raise SDRDisconnectedError("Simulated source is closed")

            if self.realtime:
                now = time.monotonic()
                block_dt = min(0.035, num_samples / self.sample_rate)
                elapsed = now - self._last_read_time
                if elapsed < block_dt:
                    time.sleep(block_dt - elapsed)
                self._last_read_time = time.monotonic()

            gain_scale = 1.0 if self.gain is None else 10.0 ** ((self.gain - 20.0) / 40.0)
            noise_re = self._rng.normal(0.0, self.noise_std, num_samples).astype(np.float32)
            noise_im = self._rng.normal(0.0, self.noise_std, num_samples).astype(np.float32)
            out = (noise_re + 1j * noise_im).astype(np.complex64)

            t_idx = np.arange(
                self._sample_cursor, self._sample_cursor + num_samples, dtype=np.float64
            )
            t_sec = t_idx / self.sample_rate
            wall_t = time.monotonic()

            half_bw = self.sample_rate * 0.48
            effective_center = self.center_freq * (1.0 + self.ppm * 1e-6)

            for carrier in _VIRTUAL_CARRIERS:
                offset = carrier.freq_hz - effective_center
                if abs(offset) > half_bw:
                    continue

                if carrier.burst_period_s > 0.0:
                    phase_in_cycle = (wall_t % carrier.burst_period_s) / carrier.burst_period_s
                    if phase_in_cycle > carrier.burst_duty:
                        continue

                amp = np.float32(carrier.amplitude * gain_scale)
                if carrier.bw_hz > 1000.0:
                    # Slight FM deviation to give realistic spectral width
                    mod = (carrier.bw_hz * 0.35) * np.sin(2.0 * math.pi * 1100.0 * t_sec)
                    phase = 2.0 * math.pi * offset * t_sec + (mod / 1100.0)
                else:
                    phase = 2.0 * math.pi * offset * t_sec
                out += amp * np.exp(1j * phase).astype(np.complex64)

            self._sample_cursor += num_samples
            return out

    def set_center_freq(self, freq_hz: float) -> None:
        with self._lock:
            self.center_freq = float(freq_hz)

    def set_sample_rate(self, rate_hz: float) -> None:
        with self._lock:
            self.sample_rate = float(rate_hz)

    def set_gain(self, gain_db: float | None) -> None:
        with self._lock:
            self.gain = gain_db

    def set_ppm(self, ppm: int) -> None:
        with self._lock:
            self.ppm = int(ppm)

    def flush_buffer(self, discard_samples: int = 16384) -> None:
        with self._lock:
            self._sample_cursor += discard_samples
