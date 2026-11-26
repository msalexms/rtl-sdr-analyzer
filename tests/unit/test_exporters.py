"""Unit tests for CSV and JSONL event exporters."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rtl_sdr_analyzer.detection.events import SignalEvent
from rtl_sdr_analyzer.exporters.csv_exporter import CsvExporter
from rtl_sdr_analyzer.exporters.json_exporter import JsonExporter


@pytest.fixture
def sample_event() -> SignalEvent:
    return SignalEvent(
        timestamp=datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC),
        frequency=446.006,
        power=-30.0,
        bandwidth=12_500.0,
        duration=1.5,
        confidence=2.5,
        snr=45.0,
        center_offset=6_000.0,
        noise_floor=-75.0,
    )


def test_csv_exporter_creates_parent_and_appends(tmp_path: Path, sample_event: SignalEvent) -> None:
    path = tmp_path / "nested" / "events.csv"
    with CsvExporter(path) as exp:
        exp.export(sample_event)
    with CsvExporter(path) as exp:
        exp.export(sample_event)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("timestamp")


def test_json_exporter(tmp_path: Path, sample_event: SignalEvent) -> None:
    path = tmp_path / "events.jsonl"
    with JsonExporter(path) as exp:
        exp.export(sample_event)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "446.006" in lines[0]
