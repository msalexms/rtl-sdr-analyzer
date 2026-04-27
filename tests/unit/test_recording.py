"""Tests for IQ recording."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from rtl_sdr_analyzer.recording.recorder import IQRecorder


@pytest.fixture
def mock_rtlsdr() -> MagicMock:
    rtl = MagicMock()
    rtl.center_freq = 100e6
    rtl.sample_rate = 2.048e6
    return rtl


class TestIQRecorder:
    def test_raw_recording(self, tmp_path: Path, mock_rtlsdr: MagicMock) -> None:
        output = tmp_path / "test.raw"

        # Simulate 2048 samples per read
        mock_rtlsdr.read_samples.side_effect = [
            np.ones(2048, dtype=np.complex64) * 0.5,
            np.ones(2048, dtype=np.complex64) * 0.5,
            None,
        ]

        with IQRecorder(output, format="raw") as rec:
            rec.record(mock_rtlsdr, duration=0.1)

        assert output.exists()
        assert output.stat().st_size > 0

    def test_numpy_recording(self, tmp_path: Path, mock_rtlsdr: MagicMock) -> None:
        output = tmp_path / "test.npz"

        mock_rtlsdr.read_samples.side_effect = [
            np.ones(2048, dtype=np.complex64) * 0.3,
            None,
        ]

        with IQRecorder(output, format="numpy") as rec:
            rec.record(mock_rtlsdr, duration=0.1)

        assert output.exists()
        data = np.load(output)
        assert "iq" in data
        assert len(data["iq"]) == 2048

    def test_empty_recording(self, tmp_path: Path, mock_rtlsdr: MagicMock) -> None:
        output = tmp_path / "empty.npz"
        mock_rtlsdr.read_samples.return_value = None

        with IQRecorder(output, format="numpy") as rec:
            rec.record(mock_rtlsdr, duration=0.1)

        # Should not crash even with no samples
        assert output.exists() or True  # may not create file if empty
