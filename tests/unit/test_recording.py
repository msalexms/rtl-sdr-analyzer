"""Unit tests for IQRecorder (raw clipped uint8, numpy metadata, live tap)."""

from pathlib import Path

import numpy as np

from rtl_sdr_analyzer.recording.recorder import IQRecorder
from rtl_sdr_analyzer.sources.simulated import SimulatedSource


class TestIQRecorder:
    def test_raw_clips_positive_one_without_wraparound(self, tmp_path: Path) -> None:
        out = tmp_path / "clip.raw"
        samples = np.array([1.0 + 1.0j, -1.0 - 1.0j, 0.0 + 0.0j], dtype=np.complex64)
        with IQRecorder(out, format="raw", sample_rate=2.048e6, center_freq=98e6) as rec:
            rec.write_samples(samples)

        raw = np.frombuffer(out.read_bytes(), dtype=np.uint8)
        assert list(raw[:2]) == [255, 255]  # must NOT wrap to 0!
        assert list(raw[2:4]) == [0, 0]

    def test_numpy_archive_stores_metadata(self, tmp_path: Path) -> None:
        out = tmp_path / "cap.npz"
        src = SimulatedSource(center_freq=433.92e6, sample_rate=1.024e6, gain=29.7, realtime=False)
        with src, IQRecorder(out, format="numpy") as rec:
            written = rec.record(src, duration=0.02, chunk_size=2048)
            assert written > 0

        with np.load(out) as data:
            assert "iq" in data
            assert float(data["center_freq"]) == 433.92e6
            assert float(data["sample_rate"]) == 1.024e6
            assert float(data["gain"]) == 29.7
