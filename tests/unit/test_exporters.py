"""Tests for CSV and JSON exporters."""

from datetime import datetime
from pathlib import Path

import pytest

from rtl_sdr_analyzer.detection.events import JammingEvent
from rtl_sdr_analyzer.exporters.csv_exporter import CsvExporter
from rtl_sdr_analyzer.exporters.json_exporter import JsonExporter


@pytest.fixture
def sample_event() -> JammingEvent:
    return JammingEvent(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        frequency=446.0,
        power=-30.0,
        bandwidth=12500.0,
        duration=1.5,
        confidence=2.5,
        snr=45.0,
    )


class TestCsvExporter:
    def test_writes_header_and_row(self, tmp_path: Path, sample_event: JammingEvent) -> None:
        path = tmp_path / "events.csv"
        exporter = CsvExporter(output_path=path)
        exporter.export(sample_event)
        exporter.close()

        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("timestamp")
        assert "446.0" in lines[1]

    def test_appends_to_existing(self, tmp_path: Path, sample_event: JammingEvent) -> None:
        path = tmp_path / "events.csv"
        exporter1 = CsvExporter(output_path=path)
        exporter1.export(sample_event)
        exporter1.close()

        exporter2 = CsvExporter(output_path=path)
        exporter2.export(sample_event)
        exporter2.close()

        lines = path.read_text().strip().splitlines()
        assert len(lines) == 3  # header + 2 rows

    def test_no_path_warns(self, sample_event: JammingEvent) -> None:
        exporter = CsvExporter(output_path=None)
        exporter.export(sample_event)  # should not raise
        exporter.close()


class TestJsonExporter:
    def test_writes_json_line(self, tmp_path: Path, sample_event: JammingEvent) -> None:
        path = tmp_path / "events.jsonl"
        exporter = JsonExporter(output_path=path)
        exporter.export(sample_event)
        exporter.close()

        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert "446.0" in lines[0]

    def test_no_path_warns(self, sample_event: JammingEvent) -> None:
        exporter = JsonExporter(output_path=None)
        exporter.export(sample_event)  # should not raise
        exporter.close()
