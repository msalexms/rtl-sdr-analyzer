"""Shared pytest fixtures."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rtl_sdr_analyzer.config.models import Settings
from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase


@pytest.fixture
def valid_settings() -> Settings:
    return Settings()


@pytest.fixture
def sample_iq_data() -> np.ndarray:
    """Generate fake IQ samples (complex64)."""
    rng = np.random.default_rng(42)
    real = rng.integers(0, 256, size=2048, dtype=np.uint8)
    imag = rng.integers(0, 256, size=2048, dtype=np.uint8)
    return ((real + 1j * imag).astype(np.complex128) - 127.5 - 127.5j) / 127.5


@pytest.fixture
def sample_spectrum() -> np.ndarray:
    """Generate a spectrum with a small signal peak."""
    noise = np.random.default_rng(42).normal(-80.0, 5.0, 2048)
    noise[1000:1020] = -30.0
    return noise


@pytest.fixture
def mock_rtlsdr() -> RTLSDRBase:
    """Return a mocked RTLSDRBase with sample data."""
    with patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket") as mock_socket_cls:
        mock_socket_instance = MagicMock()
        mock_socket_cls.return_value = mock_socket_instance
        rtl = RTLSDRBase(
            host="localhost",
            port=1234,
            center_freq=100e6,
            sample_rate=2.048e6,
            fft_size=2048,
        )
        # Pre-populate freq_range
        rtl.freq_range = np.linspace(99.0, 101.0, 2048)
        yield rtl


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path
