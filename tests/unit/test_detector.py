"""Unit tests for the adaptive SignalDetector."""

import numpy as np
import pytest

from rtl_sdr_analyzer.detection.detector import SignalDetector
from rtl_sdr_analyzer.dsp.processor import compute_freq_axis_mhz


@pytest.fixture
def freq_range() -> np.ndarray:
    return compute_freq_axis_mhz(915.0e6, 2.048e6, 2048)


@pytest.fixture
def quiet_spectrum() -> np.ndarray:
    return np.full(2048, -82.0)


@pytest.fixture
def loud_spectrum() -> np.ndarray:
    s = np.full(2048, -82.0)
    s[1000:1030] = -30.0  # 30 bins * 1 kHz = 30 kHz BW, +52 dB SNR
    return s


class TestSignalDetector:
    def test_baseline_not_poisoned_by_active_signal(
        self,
        quiet_spectrum: np.ndarray,
        loud_spectrum: np.ndarray,
        freq_range: np.ndarray,
    ) -> None:
        det = SignalDetector(
            power_threshold=-60.0,
            snr_threshold=10.0,
            bandwidth_threshold=5_000.0,
            z_score_threshold=2.0,
            detection_window=5,
            min_duration=0.1,
            cooldown_seconds=1.0,
        )
        for i in range(5):
            assert det.detect_signal(quiet_spectrum, freq_range, float(i)) is None
        assert det.baseline_mean == pytest.approx(-82.0)

        # Trigger and hold active signal for many frames; baseline must stay near -82 dB
        assert det.detect_signal(loud_spectrum, freq_range, 5.0) is None
        ev = det.detect_signal(loud_spectrum, freq_range, 5.2)
        assert ev is not None
        assert ev.timestamp.tzinfo is not None
        assert ev.snr == pytest.approx(52.0)
        assert det.baseline_mean == pytest.approx(-82.0)

    def test_cooldown_prevents_frame_spam_and_holdover_bridges_brief_fade(
        self,
        quiet_spectrum: np.ndarray,
        loud_spectrum: np.ndarray,
        freq_range: np.ndarray,
    ) -> None:
        det = SignalDetector(
            power_threshold=-60.0,
            snr_threshold=10.0,
            bandwidth_threshold=5_000.0,
            z_score_threshold=2.0,
            detection_window=3,
            min_duration=0.1,
            holdover_seconds=0.5,
            cooldown_seconds=2.0,
        )
        for i in range(3):
            det.detect_signal(quiet_spectrum, freq_range, float(i))

        assert det.detect_signal(loud_spectrum, freq_range, 10.0) is None
        ev1 = det.detect_signal(loud_spectrum, freq_range, 10.2)
        assert ev1 is not None

        # Within cooldown: suppressed
        assert det.detect_signal(loud_spectrum, freq_range, 10.5) is None

        # Brief 0.3s fade (< 0.5s holdover): still active
        assert det.detect_signal(quiet_spectrum, freq_range, 10.8) is None
        assert det.potential_signal is True

        # After cooldown elapses while signal continues: emits again
        ev2 = det.detect_signal(loud_spectrum, freq_range, 12.5)
        assert ev2 is not None

        # Fade longer than holdover ends signal
        assert det.detect_signal(quiet_spectrum, freq_range, 13.5) is None
        assert det.potential_signal is False

    def test_test_mode_non_negative_snr(
        self,
        quiet_spectrum: np.ndarray,
        freq_range: np.ndarray,
    ) -> None:
        det = SignalDetector(
            power_threshold=-90.0,
            min_duration=0.0,
            detection_window=2,
            cooldown_seconds=0.0,
            test_mode=True,
        )
        det.detect_signal(quiet_spectrum, freq_range, 0.0)
        det.detect_signal(quiet_spectrum, freq_range, 1.0)
        ev = det.detect_signal(np.full(2048, -85.0), freq_range, 2.0)
        assert ev is not None
        assert ev.snr >= 0.0
