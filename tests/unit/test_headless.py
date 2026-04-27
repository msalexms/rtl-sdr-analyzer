"""Tests for HeadlessVisualization."""

import logging

import numpy as np
import pytest

from rtl_sdr_analyzer.detection.events import JammingEvent
from rtl_sdr_analyzer.visualization.headless import HeadlessVisualization


@pytest.fixture
def headless() -> HeadlessVisualization:
    freq = np.linspace(99.0, 101.0, 2048)
    return HeadlessVisualization(
        freq_range=freq,
        waterfall_length=10,
        update_interval=50,
        log_interval_frames=2,
    )


class TestHeadlessVisualization:
    def test_update_logs_stats(self, headless: HeadlessVisualization, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO)
        spectrum = np.full(2048, -50.0)
        headless.update(spectrum)
        headless.update(spectrum)
        assert any("Spectrum stats" in r.message for r in caplog.records)

    def test_update_logs_detection(self, headless: HeadlessVisualization, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO)
        spectrum = np.full(2048, -50.0)
        event = JammingEvent(
            timestamp=__import__("datetime").datetime.now(),
            frequency=100.0,
            power=-30.0,
            bandwidth=1000.0,
            duration=1.0,
            confidence=2.0,
        )
        headless.update(spectrum, event)
        assert any("DETECTION" in r.message for r in caplog.records)

    def test_none_spectrum(self, headless: HeadlessVisualization) -> None:
        artists = headless.update(None)
        assert artists == []

    def test_stop_sets_flag(self, headless: HeadlessVisualization) -> None:
        headless.stop()
        assert headless._running is False
