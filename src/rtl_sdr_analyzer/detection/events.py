"""Event and frame data structures for signal detection and streaming."""

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from rtl_sdr_analyzer.dsp.processor import PeakInfo


class SignalEvent(BaseModel):
    """Represents a confirmed RF signal / interference detection event."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    frequency: float
    power: float
    bandwidth: float
    duration: float
    confidence: float
    snr: float = Field(default=0.0, ge=0.0)
    center_offset: float | None = None
    noise_floor: float | None = None


class DetectionStats(BaseModel):
    """Running statistics for signal detection performance."""

    total_frames: int = 0
    detected_frames: int = 0
    events_emitted: int = 0
    detection_rate: float = 0.0
    average_power: float = 0.0
    peak_power: float = float("-inf")
    noise_floor_db: float = -120.0

    def update(self, power: float, is_detection: bool, noise_floor: float | None = None) -> None:
        """Update detection statistics with a new frame."""
        self.total_frames += 1
        if is_detection:
            self.detected_frames += 1
        self.peak_power = max(self.peak_power, power)
        self.average_power = (
            self.average_power * (self.total_frames - 1) + power
        ) / self.total_frames
        if self.total_frames > 0:
            self.detection_rate = self.detected_frames / self.total_frames
        if noise_floor is not None:
            self.noise_floor_db = noise_floor


@dataclass(slots=True)
class SpectrumFrame:
    """Processed spectrum frame emitted by :class:`SpectrumEngine`."""

    seq: int
    timestamp: float
    center_freq_hz: float
    sample_rate_hz: float
    fft_size: int
    freqs_start_mhz: float
    freqs_step_mhz: float
    power_db: np.ndarray
    noise_floor_db: float
    noise_std_db: float
    peak_freq_mhz: float
    peak_power_db: float
    peak_snr_db: float
    peaks: list[PeakInfo] = field(default_factory=list)
    event: SignalEvent | None = None
    fps: float = 0.0
