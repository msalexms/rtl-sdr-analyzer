"""Shared pytest fixtures for RTL-SDR Analyzer v3."""

from pathlib import Path

import numpy as np
import pytest

from rtl_sdr_analyzer.config.models import Settings
from rtl_sdr_analyzer.sources.simulated import SimulatedSource


@pytest.fixture
def default_settings() -> Settings:
    return Settings()


@pytest.fixture
def simulated_source() -> SimulatedSource:
    """Fast deterministic non-realtime simulated source for tests."""
    return SimulatedSource(
        center_freq=98.0e6,
        sample_rate=2.048e6,
        realtime=False,
        seed=123,
    )


@pytest.fixture
def complex_tone() -> np.ndarray:
    """Full-scale complex tone centered on bin +128 of a 2048-point FFT."""
    n = 2048
    k = 128
    idx = np.arange(n, dtype=np.float64)
    return np.exp(1j * 2.0 * np.pi * k * idx / n).astype(np.complex64)


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path
