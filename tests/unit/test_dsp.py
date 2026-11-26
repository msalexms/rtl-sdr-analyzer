"""Unit tests for calibrated pure-NumPy DSP."""

import numpy as np
import pytest

from rtl_sdr_analyzer.dsp.processor import (
    SignalProcessor,
    compute_freq_axis_mhz,
    estimate_noise_floor,
    measure_bandwidth_hz,
)


class TestCalibratedDsp:
    @pytest.mark.parametrize("fft_size", [1024, 2048, 4096])
    def test_full_scale_tone_reads_zero_dbfs(self, fft_size: int) -> None:
        proc = SignalProcessor(fft_size=fft_size, sample_rate=2.048e6, averaging=1, ema_alpha=1.0)
        idx = np.arange(fft_size, dtype=np.float64)
        k = fft_size // 8
        iq = np.exp(1j * 2.0 * np.pi * k * idx / fft_size).astype(np.complex64)
        spectrum = proc.process_samples(iq)
        assert spectrum is not None
        assert spectrum.shape == (fft_size,)
        assert float(np.max(spectrum)) == pytest.approx(0.0, abs=0.05)

    def test_dc_removal(self) -> None:
        proc = SignalProcessor(fft_size=1024, sample_rate=2.048e6, averaging=1, ema_alpha=1.0)
        iq = np.ones(1024, dtype=np.complex64) * 2.5
        spectrum = proc.process_samples(iq)
        assert spectrum is not None
        assert float(np.max(spectrum)) < -100.0

    def test_none_or_short_input_returns_none(self) -> None:
        proc = SignalProcessor(fft_size=2048, sample_rate=2.048e6)
        assert proc.process_samples(None) is None
        assert proc.process_samples(np.zeros(512, dtype=np.complex64)) is None

    def test_ema_reset(self, complex_tone: np.ndarray) -> None:
        proc = SignalProcessor(fft_size=2048, sample_rate=2.048e6, averaging=1, ema_alpha=0.2)
        s1 = proc.process_samples(complex_tone)
        assert s1 is not None
        assert proc._ema_linear is not None
        proc.reset()
        assert proc._ema_linear is None


class TestFreqAxisAndMeasurements:
    def test_freq_axis_centered(self) -> None:
        freqs = compute_freq_axis_mhz(98.0e6, 2.048e6, 2048)
        assert len(freqs) == 2048
        assert freqs[1024] == pytest.approx(98.0, abs=1e-6)
        assert freqs[0] < 97.0
        assert freqs[-1] > 98.9

    def test_contiguous_bandwidth_ignores_disconnected_peaks(self) -> None:
        spec = np.full(100, -90.0)
        spec[20:25] = -30.0  # 5 contiguous bins -> 5 kHz at 1 kHz/bin
        spec[80:85] = -31.0  # disconnected secondary peak
        bw = measure_bandwidth_hz(spec, peak_idx=22, bin_width_hz=1000.0, drop_db=3.0)
        assert bw == pytest.approx(5000.0)

    def test_noise_floor_median_mad_ignores_strong_peaks(self) -> None:
        rng = np.random.default_rng(7)
        spec = rng.normal(-80.0, 1.5, 2048)
        spec[900:950] = -10.0
        floor, sigma = estimate_noise_floor(spec)
        assert floor == pytest.approx(-80.0, abs=0.5)
        assert 0.5 <= sigma <= 3.0

    def test_find_peaks(self, complex_tone: np.ndarray) -> None:
        proc = SignalProcessor(fft_size=2048, sample_rate=2.048e6, averaging=1, ema_alpha=1.0)
        spectrum = proc.process_samples(complex_tone)
        assert spectrum is not None
        freqs = compute_freq_axis_mhz(100.0e6, 2.048e6, 2048)
        peaks = proc.find_peaks(spectrum, freqs, 100.0e6, min_snr_db=10.0)
        assert len(peaks) >= 1
        assert peaks[0].power_db == pytest.approx(0.0, abs=0.2)
        assert peaks[0].offset_hz == pytest.approx(128_000.0, abs=2_000.0)
