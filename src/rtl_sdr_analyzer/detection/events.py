"""Event data structures for signal detection and analysis."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JammingEvent(BaseModel):
    """Represents a detected RF signal event."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    frequency: float
    power: float
    bandwidth: float
    duration: float
    confidence: float
    snr: float | None = Field(default=None, ge=0)
    center_offset: float | None = None


class DetectionStats(BaseModel):
    """Running statistics for signal detection performance."""

    total_frames: int = 0
    detected_frames: int = 0
    false_positives: int = 0
    detection_rate: float = 0.0
    average_power: float = 0.0
    peak_power: float = float("-inf")

    def update(self, power: float, is_detection: bool) -> None:
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
