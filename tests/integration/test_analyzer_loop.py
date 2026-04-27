"""Integration tests for the Analyzer orchestrator."""

from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase
from rtl_sdr_analyzer.core.signal_processor import SignalProcessor
from rtl_sdr_analyzer.detection.detector import SignalDetector
from rtl_sdr_analyzer.orchestrator.analyzer import Analyzer
from rtl_sdr_analyzer.orchestrator.event_bus import EventBus
from rtl_sdr_analyzer.visualization.headless import HeadlessVisualization


@pytest.fixture
def mock_analyzer() -> Analyzer:
    """Return an Analyzer wired with mocked components."""
    rtl = MagicMock(spec=RTLSDRBase)
    rtl.freq_range = np.linspace(99.0, 101.0, 2048)
    rtl.__enter__ = MagicMock(return_value=rtl)
    rtl.__exit__ = MagicMock(return_value=False)

    processor = MagicMock(spec=SignalProcessor)
    detector = MagicMock(spec=SignalDetector)
    viz = MagicMock(spec=HeadlessVisualization)
    viz.get_artists.return_value = []
    viz.start.side_effect = lambda fn: fn(0)  # run one update then exit

    bus = EventBus()

    analyzer = Analyzer(
        rtlsdr=rtl,
        processor=processor,
        detector=detector,
        visualization=viz,
        event_bus=bus,
    )
    return analyzer


class TestAnalyzerLoop:
    def test_full_pipeline(self, mock_analyzer: Analyzer) -> None:
        received_events: list = []

        def capture(event) -> None:
            received_events.append(event)

        mock_analyzer.event_bus.subscribe(capture)

        # Simulate one cycle with data
        mock_analyzer.rtlsdr.read_samples.return_value = np.ones(2048, dtype=np.complex128)
        mock_analyzer.processor.process_samples.return_value = np.full(2048, -50.0)
        event = MagicMock()
        event.timestamp = datetime.now()
        event.frequency = 100.0
        event.power = -30.0
        event.bandwidth = 1000.0
        event.duration = 1.0
        event.confidence = 2.0
        mock_analyzer.detector.detect_signal.return_value = event

        mock_analyzer.start()

        mock_analyzer.rtlsdr.read_samples.assert_called_once()
        mock_analyzer.processor.process_samples.assert_called_once()
        mock_analyzer.detector.detect_signal.assert_called_once()
        assert len(received_events) == 1

    def test_error_recovery(self, mock_analyzer: Analyzer) -> None:
        mock_analyzer.max_errors = 3
        mock_analyzer.rtlsdr.read_samples.side_effect = RuntimeError("boom")
        mock_analyzer.visualization.start.side_effect = lambda fn: [fn(0) for _ in range(5)]

        # Should not raise — errors are caught internally
        mock_analyzer.start()
        assert mock_analyzer._error_count == 3
