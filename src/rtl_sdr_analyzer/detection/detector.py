"""Adaptive RF signal detector with robust baseline, holdover, and cooldown."""

import logging
from collections import deque
from datetime import UTC, datetime

import numpy as np

from rtl_sdr_analyzer.config.models import DetectorSettings
from rtl_sdr_analyzer.dsp.processor import estimate_noise_floor, measure_bandwidth_hz

from .events import DetectionStats, SignalEvent

logger = logging.getLogger(__name__)

BASELINE_EMA_ALPHA: float = 0.1
BANDWIDTH_DB_THRESHOLD: float = 3.0


class SignalDetector:
    """Detects RF signal transmissions above an adaptive noise floor."""

    def __init__(
        self,
        enabled: bool = True,
        power_threshold: float = -55.0,
        snr_threshold: float = 10.0,
        bandwidth_threshold: float = 5_000.0,
        z_score_threshold: float = 3.0,
        detection_window: int = 5,
        min_duration: float = 0.2,
        holdover_seconds: float = 0.5,
        cooldown_seconds: float = 2.0,
        test_mode: bool = False,
    ) -> None:
        self.enabled = bool(enabled)
        self.power_threshold = float(power_threshold)
        self.snr_threshold = float(snr_threshold)
        self.bandwidth_threshold = float(bandwidth_threshold)
        self.z_score_threshold = float(z_score_threshold)
        self.detection_window = max(1, int(detection_window))
        self.min_duration = float(min_duration)
        self.holdover_seconds = float(holdover_seconds)
        self.cooldown_seconds = float(cooldown_seconds)
        self.test_mode = bool(test_mode)

        self.power_history: deque[float] = deque(maxlen=self.detection_window)
        self.std_history: deque[float] = deque(maxlen=self.detection_window)
        self.baseline_mean: float | None = None
        self.baseline_std: float | None = None

        self.potential_signal: bool = False
        self.signal_start_time: float | None = None
        self.last_seen_time: float | None = None
        self.last_emit_time: float | None = None

        self.stats = DetectionStats()

    def reset(self) -> None:
        """Reset baseline history and active detection state (e.g. after retune)."""
        self.power_history.clear()
        self.std_history.clear()
        self.baseline_mean = None
        self.baseline_std = None
        self.potential_signal = False
        self.signal_start_time = None
        self.last_seen_time = None
        self.last_emit_time = None

    def update_config(self, cfg: DetectorSettings) -> None:
        """Apply updated detector settings cleanly at runtime."""
        self.enabled = cfg.enabled
        self.power_threshold = cfg.power_threshold
        self.snr_threshold = cfg.snr_threshold
        self.bandwidth_threshold = cfg.bandwidth_threshold
        self.z_score_threshold = cfg.z_score_threshold
        if cfg.detection_window != self.detection_window:
            self.detection_window = max(1, cfg.detection_window)
            self.power_history = deque(self.power_history, maxlen=self.detection_window)
            self.std_history = deque(self.std_history, maxlen=self.detection_window)
        self.min_duration = cfg.min_duration
        self.holdover_seconds = cfg.holdover_seconds
        self.cooldown_seconds = cfg.cooldown_seconds
        self.test_mode = cfg.test_mode

    def _update_baseline_from_noise(self, noise_floor: float, noise_std: float) -> None:
        self.power_history.append(noise_floor)
        self.std_history.append(noise_std)

        if len(self.power_history) < self.detection_window:
            return

        if self.baseline_mean is None or self.baseline_std is None:
            self.baseline_mean = float(np.median(self.power_history))
            self.baseline_std = max(float(np.median(self.std_history)), 0.5)
            logger.debug(
                "Baseline established: floor=%.2f dBFS, std=%.2f dB",
                self.baseline_mean,
                self.baseline_std,
            )
        else:
            alpha = BASELINE_EMA_ALPHA
            self.baseline_mean = (1.0 - alpha) * self.baseline_mean + alpha * noise_floor
            self.baseline_std = max(
                (1.0 - alpha) * self.baseline_std + alpha * noise_std,
                0.5,
            )

    def detect_signal(
        self,
        spectrum: np.ndarray,
        freq_range: np.ndarray,
        timestamp: float,
        center_freq_hz: float | None = None,
    ) -> SignalEvent | None:
        """Analyze a power spectrum frame and emit a :class:`SignalEvent` when confirmed."""
        if len(spectrum) == 0 or len(spectrum) != len(freq_range):
            return None

        frame_noise, frame_std = estimate_noise_floor(spectrum)

        if self.baseline_mean is None:
            self._update_baseline_from_noise(frame_noise, frame_std)
            if self.baseline_mean is None:
                return None

        peak_idx = int(np.argmax(spectrum))
        max_power = float(spectrum[peak_idx])
        peak_freq_mhz = float(freq_range[peak_idx])

        if not self.enabled:
            self._update_baseline_from_noise(frame_noise, frame_std)
            self.stats.update(max_power, False, noise_floor=self.baseline_mean)
            self.potential_signal = False
            self.signal_start_time = None
            self.last_seen_time = None
            return None

        baseline_mean = self.baseline_mean
        baseline_std = max(self.baseline_std if self.baseline_std is not None else 1.0, 0.5)
        snr = max(0.0, max_power - baseline_mean)
        z_score = snr / baseline_std

        bin_width_hz = float(freq_range[1] - freq_range[0]) * 1e6 if len(freq_range) > 1 else 1.0
        bandwidth = measure_bandwidth_hz(spectrum, peak_idx, bin_width_hz, BANDWIDTH_DB_THRESHOLD)

        criteria = [
            max_power >= self.power_threshold,
            snr >= self.snr_threshold,
            bandwidth >= self.bandwidth_threshold,
            z_score >= self.z_score_threshold,
        ]
        is_signal = all(criteria) if not self.test_mode else any(criteria)

        # Prevent sustained strong transmissions from poisoning the baseline floor
        if not is_signal and not self.potential_signal:
            self._update_baseline_from_noise(frame_noise, frame_std)

        self.stats.update(max_power, is_signal, noise_floor=self.baseline_mean)

        if is_signal:
            if not self.potential_signal:
                self.potential_signal = True
                self.signal_start_time = timestamp
            self.last_seen_time = timestamp

            start_t = self.signal_start_time if self.signal_start_time is not None else timestamp
            duration = max(0.0, timestamp - start_t)
            cooldown_ok = (
                self.last_emit_time is None
                or (timestamp - self.last_emit_time) >= self.cooldown_seconds
            )

            if duration >= self.min_duration and cooldown_ok:
                self.last_emit_time = timestamp
                self.stats.events_emitted += 1
                center_hz = (
                    center_freq_hz
                    if center_freq_hz is not None
                    else float((freq_range[0] + freq_range[-1]) * 0.5e6)
                )
                event = SignalEvent(
                    timestamp=datetime.fromtimestamp(timestamp, tz=UTC),
                    frequency=peak_freq_mhz,
                    power=max_power,
                    bandwidth=bandwidth,
                    duration=duration,
                    confidence=z_score / self.z_score_threshold,
                    snr=snr,
                    center_offset=(peak_freq_mhz * 1e6) - center_hz,
                    noise_floor=baseline_mean,
                )
                logger.info(
                    "Signal confirmed: freq=%.4f MHz power=%.1f dBFS snr=%.1f dB bw=%.0f Hz",
                    event.frequency,
                    event.power,
                    event.snr,
                    event.bandwidth,
                )
                return event

        elif self.potential_signal:
            last_seen = self.last_seen_time if self.last_seen_time is not None else timestamp
            if (timestamp - last_seen) > self.holdover_seconds:
                self.potential_signal = False
                self.signal_start_time = None
                self.last_seen_time = None

        return None
