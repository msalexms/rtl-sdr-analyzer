"""Unit tests for the signal detector."""

import numpy as np
import pytest

from rtl_sdr_analyzer.detection.detector import SignalDetector


@pytest.fixture
def detector() -> SignalDetector:
    return SignalDetector(
        power_threshold=-70.0,
        bandwidth_threshold=1e5,
        z_score_threshold=1.5,
        detection_window=5,
        min_duration=0.1,
    )


@pytest.fixture
def quiet_spectrum() -> np.ndarray:
    return np.full(2048, -80.0)


@pytest.fixture
def loud_spectrum() -> np.ndarray:
    """Spectrum with ~146 kHz bandwidth (>100 kHz threshold)."""
    s = np.full(2048, -80.0)
    s[950:1100] = -30.0  # 150 bins → ~146 kHz bandwidth
    return s


@pytest.fixture
def freq_range() -> np.ndarray:
    return np.linspace(914.0, 916.0, 2048)


class TestBaselineEstablishment:
    def test_no_baseline_until_window_full(self, detector: SignalDetector, quiet_spectrum: np.ndarray, freq_range: np.ndarray) -> None:
        for i in range(4):
            event = detector.detect_signal(quiet_spectrum, freq_range, float(i))
            assert event is None
        assert detector.baseline_mean is None

        detector.detect_signal(quiet_spectrum, freq_range, 5.0)
        assert detector.baseline_mean is not None
        assert detector.baseline_std is not None


class TestDetectionLogic:
    def test_no_signal_in_quiet(self, detector: SignalDetector, quiet_spectrum: np.ndarray, freq_range: np.ndarray) -> None:
        # Establish baseline
        for i in range(5):
            detector.detect_signal(quiet_spectrum, freq_range, float(i))

        # Quiet spectrum should not trigger
        event = detector.detect_signal(quiet_spectrum, freq_range, 5.0)
        assert event is None

    def test_signal_detected_when_strong(self, detector: SignalDetector, quiet_spectrum: np.ndarray, loud_spectrum: np.ndarray, freq_range: np.ndarray) -> None:
        # Establish baseline
        for i in range(5):
            detector.detect_signal(quiet_spectrum, freq_range, float(i))

        # First strong frame starts potential signal
        event = detector.detect_signal(loud_spectrum, freq_range, 5.0)
        assert event is None  # min_duration not met
        assert detector.potential_signal is True

        # Second frame after min_duration should confirm
        event = detector.detect_signal(loud_spectrum, freq_range, 5.2)
        assert event is not None
        assert event.power == pytest.approx(-30.0)
        assert event.duration >= 0.1
        assert event.snr is not None
        assert event.snr > 0

    def test_signal_ends(self, detector: SignalDetector, quiet_spectrum: np.ndarray, loud_spectrum: np.ndarray, freq_range: np.ndarray) -> None:
        for i in range(5):
            detector.detect_signal(quiet_spectrum, freq_range, float(i))

        detector.detect_signal(loud_spectrum, freq_range, 5.0)
        detector.detect_signal(loud_spectrum, freq_range, 5.2)

        # Return to quiet
        detector.detect_signal(quiet_spectrum, freq_range, 6.0)
        assert detector.potential_signal is False
        assert detector.signal_start_time is None

    def test_test_mode_any_criteria(self, quiet_spectrum: np.ndarray, freq_range: np.ndarray) -> None:
        # Use a long min_duration to avoid accidental confirmation.
        detector = SignalDetector(
            power_threshold=-70.0,
            bandwidth_threshold=1e5,
            z_score_threshold=1.5,
            detection_window=5,
            min_duration=5.0,
            test_mode=True,
        )
        for i in range(5):
            detector.detect_signal(quiet_spectrum, freq_range, float(i))

        # In test mode, any single criterion triggers detection.
        s = np.full(2048, -60.0)
        event = detector.detect_signal(s, freq_range, 5.0)
        assert event is None  # min_duration (5.0) not met yet
        assert detector.potential_signal is True

        # Confirm after min_duration
        event = detector.detect_signal(s, freq_range, 10.0)
        assert event is not None
        assert event.power == pytest.approx(-60.0)


class TestDetectionStats:
    def test_stats_updated(self, detector: SignalDetector, quiet_spectrum: np.ndarray, freq_range: np.ndarray) -> None:
        for i in range(5):
            detector.detect_signal(quiet_spectrum, freq_range, float(i))

        # Stats are only updated once baseline is established (5th frame)
        assert detector.stats.total_frames == 1
        assert detector.stats.detected_frames == 0
