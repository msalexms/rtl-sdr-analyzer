"""Offline IQ file replay source (.raw/.cu8 and .npz)."""

import threading
import time
from pathlib import Path
from types import TracebackType

import numpy as np

from rtl_sdr_analyzer.recording.metadata import read_metadata

from .base import (
    DeviceInfo,
    SDRConfigurationError,
    SDRConnectionError,
    SDRDisconnectedError,
    uint8_iq_to_complex64,
)

_MAX_PACE_S = 1.0
REPLAY_SPEEDS: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0)


class FileReplaySource:
    """Replay recorded ``.raw``/``.cu8`` or ``.npz`` IQ files in a loop, in real time.

    Raw files are memory-mapped, so large captures do not have to fit in RAM.
    Center frequency and sample rate come from the file metadata (npz arrays,
    JSON sidecar or ``<freq>MHz`` in the name) and are fixed during playback.
    """

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
        self.speed = 1.0

        self._lock = threading.RLock()
        # complex64 samples (npz) or a uint8 interleaved I/Q memmap (raw/cu8)
        self._samples: np.ndarray | None = None
        self._raw = False
        self._total = 0
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

            meta = read_metadata(self.file_path)
            self.center_freq = meta["center_freq_hz"] or self.center_freq
            self.sample_rate = meta["sample_rate_hz"] or self.sample_rate

            samples: np.ndarray
            if self.file_path.suffix.lower() == ".npz":
                with np.load(self.file_path) as archive:
                    if "iq" not in archive:
                        raise SDRConnectionError(f"Missing 'iq' array in {self.file_path}")
                    samples = np.asarray(archive["iq"], dtype=np.complex64)
                self._raw = False
                total = len(samples)
            else:
                if self.file_path.stat().st_size < 2:
                    raise SDRConnectionError(f"IQ file contains no samples: {self.file_path}")
                samples = np.memmap(self.file_path, dtype=np.uint8, mode="r")
                self._raw = True
                total = len(samples) // 2

            if total == 0:
                raise SDRConnectionError(f"IQ file contains no samples: {self.file_path}")

            self._samples = samples
            self._total = total
            self._cursor = 0
            self._last_read = time.monotonic()
            self._info = self._info.model_copy(
                update={
                    "connected": True,
                    "detail": f"{total:,} samples @ {self.sample_rate / 1e6:.3f} MSPS",
                }
            )

    def close(self) -> None:
        with self._lock:
            self._samples = None  # drops the memmap and releases the file
            self._total = 0
            self._cursor = 0
            self._info = self._info.model_copy(update={"connected": False})

    def read_samples(self, num_samples: int) -> np.ndarray:
        if num_samples <= 0:
            return np.empty(0, dtype=np.complex64)

        with self._lock:
            if self._samples is None:
                raise SDRDisconnectedError("Replay source is not open")

            if self.realtime:
                # Pace playback to the recorded sample rate (1 s of IQ takes 1 s).
                dt = min(_MAX_PACE_S, num_samples / (self.sample_rate * self.speed))
                elapsed = time.monotonic() - self._last_read
                if elapsed < dt:
                    time.sleep(dt - elapsed)
                self._last_read = time.monotonic()

            parts: list[np.ndarray] = []
            remaining = num_samples
            while remaining > 0:
                take = min(remaining, self._total - self._cursor)
                parts.append(self._slice(self._cursor, take))
                self._cursor = (self._cursor + take) % self._total
                remaining -= take
            return parts[0] if len(parts) == 1 else np.concatenate(parts)

    def _slice(self, start: int, count: int) -> np.ndarray:
        assert self._samples is not None
        if self._raw:
            return uint8_iq_to_complex64(self._samples[2 * start : 2 * (start + count)])
        return self._samples[start : start + count]

    def set_center_freq(self, freq_hz: float) -> None:
        if abs(float(freq_hz) - self.center_freq) > 1.0:
            raise SDRConfigurationError(
                "Frequency is fixed while replaying a recording; switch source to tune."
            )

    def set_sample_rate(self, rate_hz: float) -> None:
        if abs(float(rate_hz) - self.sample_rate) > 1.0:
            raise SDRConfigurationError(
                "Sample rate is fixed while replaying a recording; switch source to change it."
            )

    def set_gain(self, gain_db: float | None) -> None:
        with self._lock:
            self.gain = gain_db

    def set_ppm(self, ppm: int) -> None:
        with self._lock:
            self.ppm = int(ppm)

    # ------------------------------------------------------------------
    # Transport (position / speed)
    # ------------------------------------------------------------------

    @property
    def total_samples(self) -> int:
        return self._total

    @property
    def position_samples(self) -> int:
        with self._lock:
            return self._cursor

    def seek(self, sample_index: int) -> None:
        """Jump to ``sample_index`` (wrapped into the file length)."""
        with self._lock:
            if self._total > 0:
                self._cursor = int(sample_index) % self._total

    def set_speed(self, speed: float) -> None:
        if speed not in REPLAY_SPEEDS:
            raise SDRConfigurationError(f"Replay speed must be one of {REPLAY_SPEEDS}")
        with self._lock:
            self.speed = float(speed)

    def flush_buffer(self, discard_samples: int = 16384) -> None:
        with self._lock:
            if self._total > 0:
                self._cursor = (self._cursor + discard_samples) % self._total
