"""IQ sample recorder supporting blocking capture and live streaming taps."""

import logging
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

from rtl_sdr_analyzer.recording.metadata import write_sidecar
from rtl_sdr_analyzer.sources.base import SDRSource

logger = logging.getLogger(__name__)


class IQRecorder:
    """Records complex IQ samples to ``raw`` (uint8 interleaved) or ``numpy`` (``.npz``)."""

    def __init__(
        self,
        output_path: Path | str,
        format: str = "raw",
        sample_rate: float = 2.048e6,
        center_freq: float = 0.0,
        gain: float | None = None,
    ) -> None:
        self.output_path = Path(output_path)
        self.format = format.lower()
        if self.format not in ("raw", "numpy"):
            raise ValueError(f"Unsupported IQ format: {format!r} (expected 'raw' or 'numpy')")

        self.sample_rate = float(sample_rate)
        self.center_freq = float(center_freq)
        self.gain = gain

        self._lock = threading.Lock()
        self._file: Any = None
        # NumPy recordings stream complex64 to a side file so RAM stays flat.
        self._spool_path = self.output_path.with_name(self.output_path.name + ".part")
        self._samples_written: int = 0
        self._bytes_written: int = 0
        self._started_at: float = time.monotonic()

    def __enter__(self) -> "IQRecorder":
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
        """Prepare output file for writing."""
        with self._lock:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._started_at = time.monotonic()
            if self._file is None:
                self._file = open(self._target_path, "wb")
                logger.info("Opened %s IQ recording: %s", self.format, self.output_path)

    @property
    def _target_path(self) -> Path:
        return self.output_path if self.format == "raw" else self._spool_path

    def write_samples(self, iq_data: np.ndarray) -> None:
        """Append a complex IQ sample block to the active recording."""
        if len(iq_data) == 0:
            return
        # complex64 viewed as interleaved float32 I/Q pairs
        interleaved = np.ascontiguousarray(iq_data, dtype=np.complex64).view(np.float32)
        payload: np.ndarray
        if self.format == "raw":
            payload = np.clip(np.rint(interleaved * 127.5 + 127.5), 0, 255).astype(np.uint8)
        else:
            payload = interleaved
        with self._lock:
            if self._file is None:
                self._file = open(self._target_path, "wb")
            self._file.write(payload.tobytes())
            self._bytes_written += payload.nbytes
            self._samples_written += len(iq_data)

    def record(self, source: SDRSource, duration: float, chunk_size: int = 16384) -> int:
        """Record IQ samples synchronously from ``source`` for ``duration`` seconds."""
        self.sample_rate = float(source.sample_rate)
        self.center_freq = float(source.center_freq)
        self.gain = source.gain

        deadline = time.monotonic() + max(0.0, duration)
        while time.monotonic() < deadline:
            iq = source.read_samples(chunk_size)
            if len(iq) > 0:
                self.write_samples(iq)
        return self._samples_written

    def close(self) -> None:
        """Flush and close the recording output."""
        with self._lock:
            if self._file is None:
                return
            self._file.close()
            self._file = None
            if self.format == "raw":
                write_sidecar(
                    self.output_path,
                    center_freq_hz=self.center_freq,
                    sample_rate_hz=self.sample_rate,
                    gain_db=self.gain,
                    samples=self._samples_written,
                )
                logger.info(
                    "Saved raw IQ file %s (%d samples, %d bytes)",
                    self.output_path,
                    self._samples_written,
                    self._bytes_written,
                )
            else:
                self._save_numpy()

    def _save_numpy(self) -> None:
        if self._samples_written == 0:
            logger.warning("No IQ samples captured; skipping %s", self.output_path)
            self._spool_path.unlink(missing_ok=True)
            return
        all_samples = np.memmap(self._spool_path, dtype=np.complex64, mode="r")
        np.savez(
            self.output_path,
            iq=all_samples,
            sample_rate=np.float64(self.sample_rate),
            center_freq=np.float64(self.center_freq),
            gain=np.float64(-1.0 if self.gain is None else self.gain),
            timestamp=np.float64(time.time()),
        )
        del all_samples  # release the memmap before deleting its file (Windows)
        self._spool_path.unlink(missing_ok=True)
        self._bytes_written = self.output_path.stat().st_size if self.output_path.exists() else 0
        logger.info(
            "Saved NumPy IQ archive %s (%d samples @ %.3f MHz)",
            self.output_path,
            self._samples_written,
            self.center_freq / 1e6,
        )

    def summary(self) -> dict[str, Any]:
        """Return current recording statistics."""
        with self._lock:
            return {
                "filename": self.output_path.name,
                "path": str(self.output_path),
                "format": self.format,
                "samples": self._samples_written,
                "bytes": self._bytes_written,
                "duration_s": round(self._samples_written / max(self.sample_rate, 1.0), 3),
                "center_freq_hz": self.center_freq,
                "sample_rate_hz": self.sample_rate,
            }
