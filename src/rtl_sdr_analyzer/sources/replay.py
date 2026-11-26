"""Offline IQ file replay source (.raw/.cu8 and .npz)."""

import threading
import time
from pathlib import Path
from types import TracebackType

import numpy as np

from .base import (
    DeviceInfo,
    SDRConnectionError,
    SDRDisconnectedError,
    uint8_iq_to_complex64,
)


class FileReplaySource:
    """Replay recorded ``.raw``/``.cu8`` or ``.npz`` IQ files in a loop."""

    source_type: str = "file"

    def __init__(
        self,
        file_path: str | Path,
        center_freq: float = 98.0e6,
        sample_rate: float = 2.048e6,
        realtime: bool = True,
    ) -> None:
        self.file_path = Path(file_path)
        self.center_freq = float(center_freq)
        self.sample_rate = float(sample_rate)
        self.gain: float | None = None
        self.ppm: int = 0
        self.realtime = realtime

        self._lock = threading.RLock()
        self._samples: np.ndarray | None = None
        self._cursor: int = 0
        self._last_read: float = 0.0
        self._info = DeviceInfo(
            index=0,
            name=f"IQ File ({self.file_path.name})",
            source_type="file",
            tuner="REPLAY",
            detail=str(self.file_path),
        )

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._samples is not None

    @property
    def info(self) -> DeviceInfo:
        with self._lock:
            return self._info.model_copy()

    def __enter__(self) -> "FileReplaySource":
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
        """Load IQ file into memory for seamless looping playback."""
        with self._lock:
            if not self.file_path.is_file():
                raise SDRConnectionError(f"Replay IQ file not found: {self.file_path}")

            suffix = self.file_path.suffix.lower()
            if suffix == ".npz":
                with np.load(self.file_path) as archive:
                    if "iq" not in archive:
                        raise SDRConnectionError(f"Missing 'iq' array in {self.file_path}")
                    samples = np.asarray(archive["iq"], dtype=np.complex64)
                    if "sample_rate" in archive and float(archive["sample_rate"]) > 0:
                        self.sample_rate = float(archive["sample_rate"])
                    if "center_freq" in archive and float(archive["center_freq"]) > 0:
                        self.center_freq = float(archive["center_freq"])
            else:
                raw = self.file_path.read_bytes()
                samples = uint8_iq_to_complex64(raw)

            if len(samples) == 0:
                raise SDRConnectionError(f"IQ file contains no samples: {self.file_path}")

            self._samples = samples
            self._cursor = 0
            self._last_read = time.monotonic()
            self._info = self._info.model_copy(
                update={
                    "connected": True,
                    "detail": f"{len(samples):,} samples @ {self.sample_rate / 1e6:.3f} MSPS",
                }
            )

    def close(self) -> None:
        with self._lock:
            self._samples = None
            self._cursor = 0
            self._info = self._info.model_copy(update={"connected": False})

    def read_samples(self, num_samples: int) -> np.ndarray:
        if num_samples <= 0:
            return np.empty(0, dtype=np.complex64)

        with self._lock:
            if self._samples is None:
                raise SDRDisconnectedError("Replay source is not open")

            if self.realtime:
                now = time.monotonic()
                dt = min(0.035, num_samples / self.sample_rate)
                elapsed = now - self._last_read
                if elapsed < dt:
                    time.sleep(dt - elapsed)
                self._last_read = time.monotonic()

            total = len(self._samples)
            if num_samples <= total - self._cursor:
                chunk = self._samples[self._cursor : self._cursor + num_samples]
                self._cursor = (self._cursor + num_samples) % total
                return chunk

            parts: list[np.ndarray] = []
            remaining = num_samples
            while remaining > 0:
                take = min(remaining, total - self._cursor)
                parts.append(self._samples[self._cursor : self._cursor + take])
                self._cursor = (self._cursor + take) % total
                remaining -= take
            return np.concatenate(parts)

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
            if self._samples is not None and len(self._samples) > 0:
                self._cursor = (self._cursor + discard_samples) % len(self._samples)
