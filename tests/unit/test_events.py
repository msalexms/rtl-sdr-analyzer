"""Unit tests for detection event models."""

from datetime import datetime

import pytest

from rtl_sdr_analyzer.detection.events import DetectionStats, JammingEvent


class TestJammingEvent:
    def test_creation_and_fields(self) -> None:
        ts = datetime(2024, 1, 1, 12, 0, 0)
        event = JammingEvent(
            timestamp=ts,
            frequency=446.0,
            power=-30.0,
            bandwidth=12500.0,
            duration=1.5,
            confidence=2.5,
            snr=45.0,
        )
        assert event.frequency == 446.0
        assert event.power == -30.0
        assert event.snr == 45.0

    def test_optional_fields_default_to_none(self) -> None:
        ts = datetime.now()
        event = JammingEvent(
            timestamp=ts,
            frequency=100.0,
            power=-50.0,
            bandwidth=1000.0,
            duration=0.5,
            confidence=1.0,
        )
        assert event.snr is None
        assert event.center_offset is None

    def test_model_dump(self) -> None:
        ts = datetime(2024, 1, 1, 12, 0, 0)
        event = JammingEvent(
            timestamp=ts,
            frequency=446.0,
            power=-30.0,
            bandwidth=12500.0,
            duration=1.5,
            confidence=2.5,
        )
        data = event.model_dump()
        assert data["frequency"] == 446.0
        assert data["power"] == -30.0
        assert isinstance(data["timestamp"], datetime)

    def test_immutability(self) -> None:
        ts = datetime.now()
        event = JammingEvent(
            timestamp=ts,
            frequency=100.0,
            power=-50.0,
            bandwidth=1000.0,
            duration=0.5,
            confidence=1.0,
        )
        with pytest.raises(AttributeError):
            event.power = -40.0


class TestDetectionStats:
    def test_initial_state(self) -> None:
        stats = DetectionStats()
        assert stats.total_frames == 0
        assert stats.detected_frames == 0
        assert stats.detection_rate == 0.0

    def test_update_detection(self) -> None:
        stats = DetectionStats()
        stats.update(-50.0, True)
        assert stats.total_frames == 1
        assert stats.detected_frames == 1
        assert stats.peak_power == -50.0
        assert stats.average_power == -50.0
        assert stats.detection_rate == 1.0

    def test_update_no_detection(self) -> None:
        stats = DetectionStats()
        stats.update(-80.0, False)
        assert stats.total_frames == 1
        assert stats.detected_frames == 0
        assert stats.detection_rate == 0.0

    def test_average_power_running(self) -> None:
        stats = DetectionStats()
        stats.update(-80.0, False)
        stats.update(-60.0, True)
        assert stats.average_power == -70.0
        assert stats.peak_power == -60.0
        assert stats.detection_rate == 0.5
