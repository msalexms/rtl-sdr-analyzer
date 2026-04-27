"""Signal detection and analysis module.

Implements algorithms for detecting and characterizing RF signals.
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np

from .events import DetectionStats, JammingEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
Z_SCORE_EPSILON: float = 1e-10
BASELINE_EMA_ALPHA: float = 0.1
BANDWIDTH_DB_THRESHOLD: float = 3.0


class SignalDetector:
    """Detects and analyzes RF signals in spectrum data."""

    def __init__(
        self,
        power_threshold: float = -70.0,
        bandwidth_threshold: float = 0.1e6,
        z_score_threshold: float = 1.5,
        detection_window: int = 5,
        min_duration: float = 0.1,
        test_mode: bool = False,
    ):
        self.power_threshold = power_threshold
        self.bandwidth_threshold = bandwidth_threshold
        self.z_score_threshold = z_score_threshold
        self.detection_window = detection_window
        self.min_duration = min_duration
        self.test_mode = test_mode

        # Detection state
        self.power_history: list[float] = []
        self.baseline_mean: Optional[float] = None
        self.baseline_std: Optional[float] = None
        self.potential_signal = False
        self.signal_start_time: Optional[float] = None

        # Statistics
        self.stats = DetectionStats()

    def update_baseline(self, spectrum: np.ndarray) -> None:
        """Update adaptive baseline statistics using an exponential moving average.

        Args:
            spectrum: Current power spectrum in dB.
        """
        current_mean = float(np.mean(spectrum))
        self.power_history.append(current_mean)

        if len(self.power_history) > self.detection_window:
            self.power_history.pop(0)

        if len(self.power_history) < self.detection_window:
            return

        if self.baseline_mean is None:
            self.baseline_mean = float(np.mean(self.power_history))
            self.baseline_std = float(np.std(self.power_history))
            logger.info(
                "Baseline established: mean=%.2f dB, std=%.2f dB",
                self.baseline_mean,
                self.baseline_std,
            )
        else:
            alpha = BASELINE_EMA_ALPHA
            self.baseline_mean = (1 - alpha) * self.baseline_mean + alpha * current_mean
            new_std = float(np.std(self.power_history))
            if self.baseline_std is not None:
                self.baseline_std = (1 - alpha) * self.baseline_std + alpha * new_std

    def detect_signal(
        self,
        spectrum: np.ndarray,
        freq_range: np.ndarray,
        timestamp: float,
    ) -> Optional[JammingEvent]:
        """Detect potential signals in the spectrum.

        Args:
            spectrum: Power spectrum data in dB.
            freq_range: Frequency range array in MHz.
            timestamp: Current Unix timestamp.

        Returns:
            JammingEvent if a signal is confirmed, otherwise ``None``.
        """
        self.update_baseline(spectrum)

        if self.baseline_mean is None:
            return None

        # Calculate metrics
        max_power = float(np.max(spectrum))
        current_mean = float(np.mean(spectrum))
        baseline_mean = self.baseline_mean if self.baseline_mean is not None else 0.0
        baseline_std = self.baseline_std if self.baseline_std is not None else 1.0
        z_score = (current_mean - baseline_mean) / (
            baseline_std + Z_SCORE_EPSILON
        )

        # Bandwidth estimation
        mask = spectrum > (max_power - BANDWIDTH_DB_THRESHOLD)
        bin_width_mhz = float(freq_range[1] - freq_range[0])
        bandwidth = float(np.sum(mask) * bin_width_mhz * 1e6)

        # Detection logic
        detection_criteria = [
            max_power > self.power_threshold,
            bandwidth > self.bandwidth_threshold,
            abs(z_score) > self.z_score_threshold,
        ]

        is_signal = (
            all(detection_criteria) if not self.test_mode else any(detection_criteria)
        )

        self.stats.update(max_power, is_signal)

        if is_signal and not self.potential_signal:
            self.potential_signal = True
            self.signal_start_time = timestamp
            logger.info("Potential signal detected: power=%.2f dB", max_power)

        elif is_signal and self.potential_signal:
            signal_start = self.signal_start_time if self.signal_start_time is not None else timestamp
            duration = timestamp - signal_start
            if duration >= self.min_duration:
                event = JammingEvent(
                    timestamp=datetime.fromtimestamp(timestamp),
                    frequency=float(freq_range[np.argmax(spectrum)]),
                    power=max_power,
                    bandwidth=bandwidth,
                    duration=duration,
                    confidence=abs(z_score) / self.z_score_threshold,
                    snr=max_power - self.baseline_mean,
                )
                logger.info("Signal confirmed: %s", event.model_dump())
                return event

        elif not is_signal and self.potential_signal:
            self.potential_signal = False
            self.signal_start_time = None
            logger.info("Signal ended")

        return None
