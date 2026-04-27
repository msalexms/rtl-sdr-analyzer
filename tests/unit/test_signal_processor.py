"""Tests for SignalProcessor."""

import numpy as np
import pytest

from rtl_sdr_analyzer.core.signal_processor import SignalProcessor


@pytest.fixture
def processor() -> SignalProcessor:
    return SignalProcessor(fft_size=2048, sample_rate=2.048e6)


class TestProcessSamples:
    def test_none_input(self, processor: SignalProcessor) -> None:
        assert processor.process_samples(None) is None

    def test_wrong_size(self, processor: SignalProcessor) -> None:
        assert processor.process_samples(np.zeros(100)) is None

    def test_valid_input(self, processor: SignalProcessor) -> None:
        rng = np.random.default_rng(42)
        iq = (rng.random(2048) + 1j * rng.random(2048)).astype(np.complex128)
        spectrum = processor.process_samples(iq)
        assert spectrum is not None
        assert spectrum.shape == (2048,)
        assert np.isfinite(spectrum).all()

    def test_dc_removal(self, processor: SignalProcessor) -> None:
        """A constant signal should have its DC removed, yielding low power."""
        iq = np.ones(2048, dtype=np.complex128) * 5.0
        spectrum = processor.process_samples(iq)
        assert spectrum is not None
        # After DC removal and FFT, the constant signal becomes near-zero
        assert np.mean(spectrum) < -30.0


class TestMetrics:
    def test_calculate_metrics(self, processor: SignalProcessor) -> None:
        spectrum = np.full(2048, -80.0)
        spectrum[1000:1020] = -30.0
        freq = np.linspace(99.0, 101.0, 2048)
        metrics = processor.calculate_signal_metrics(spectrum, freq)
        assert metrics["max_power"] == pytest.approx(-30.0)
        assert metrics["peak_frequency"] == pytest.approx(freq[1010], abs=0.1)
        assert metrics["bandwidth"] > 0

    def test_empty_spectrum(self, processor: SignalProcessor) -> None:
        metrics = processor.calculate_signal_metrics(np.array([]), np.array([]))
        assert metrics == {}
