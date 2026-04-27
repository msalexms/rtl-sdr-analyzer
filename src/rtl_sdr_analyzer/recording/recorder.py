"""IQ sample recorder for offline analysis."""

import logging
import struct
import time
from pathlib import Path
from typing import Optional

import numpy as np

from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase

logger = logging.getLogger(__name__)


class IQRecorder:
    """Records raw IQ samples from RTL-SDR to a file.

    Supports two output formats:
    - **raw**: Interleaved uint8 I/Q data (compatible with rtl_sdr, GNU Radio)
    - **numpy**: NumPy .npz file with complex64 array + metadata

    Example::

        with IQRecorder("output.raw", format="raw") as rec:
            rec.record(rtl, duration=10.0)
    """

    def __init__(
        self,
        output_path: Path,
        format: str = "raw",
        sample_rate: float = 2.048e6,
    ):
        self.output_path = Path(output_path)
        self.format = format.lower()
        self.sample_rate = sample_rate
        self._file: Optional[object] = None
        self._samples: list[np.ndarray] = []
        self._total_bytes = 0

    def __enter__(self) -> "IQRecorder":
        if self.format == "raw":
            self._file = open(self.output_path, "wb")
            logger.info("Opened raw IQ file: %s", self.output_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.format == "raw" and self._file is not None:
            self._file.close()
            logger.info("Closed raw IQ file (%d bytes written)", self._total_bytes)
        elif self.format == "numpy":
            self._save_numpy()

    def record(self, rtlsdr: RTLSDRBase, duration: float) -> None:
        """Record IQ samples for the specified duration.

        Args:
            rtlsdr: Connected RTLSDRBase instance.
            duration: Recording duration in seconds.
        """
        end_time = time.time() + duration
        samples_read = 0

        logger.info(
            "Recording %.1fs of IQ data @ %.3f MHz (format=%s)",
            duration,
            rtlsdr.center_freq / 1e6,
            self.format,
        )

        try:
            while time.time() < end_time:
                iq_data = rtlsdr.read_samples()
                if iq_data is None:
                    continue

                if self.format == "raw":
                    self._write_raw(iq_data)
                elif self.format == "numpy":
                    self._samples.append(iq_data)

                samples_read += len(iq_data)

                # Progress every ~1 second
                elapsed = time.time() - (end_time - duration)
                if elapsed > 0 and int(elapsed) % 1 == 0:
                    remaining = end_time - time.time()
                    logger.debug(
                        "Recorded %d samples | %.1fs remaining",
                        samples_read,
                        max(0, remaining),
                    )

        except KeyboardInterrupt:
            logger.info("Recording interrupted by user.")

        logger.info(
            "Recording complete: %d samples (%.2f seconds of data)",
            samples_read,
            samples_read / self.sample_rate,
        )

    def _write_raw(self, iq_data: np.ndarray) -> None:
        """Write complex samples as interleaved uint8 to raw file."""
        # Convert complex64 [-1, 1] back to uint8 [0, 255]
        real = ((iq_data.real * 127.5) + 127.5).astype(np.uint8)
        imag = ((iq_data.imag * 127.5) + 127.5).astype(np.uint8)
        interleaved = np.empty(2 * len(iq_data), dtype=np.uint8)
        interleaved[0::2] = real
        interleaved[1::2] = imag

        self._file.write(interleaved.tobytes())
        self._total_bytes += len(interleaved)

    def _save_numpy(self) -> None:
        """Save accumulated samples as NumPy .npz with metadata."""
        if not self._samples:
            logger.warning("No samples to save.")
            return

        all_samples = np.concatenate(self._samples)
        np.savez(
            self.output_path,
            iq=all_samples,
            sample_rate=self.sample_rate,
            center_freq=getattr(self, "_center_freq", 0),
            timestamp=time.time(),
        )
        logger.info(
            "Saved NumPy archive: %s (%d samples)",
            self.output_path,
            len(all_samples),
        )
