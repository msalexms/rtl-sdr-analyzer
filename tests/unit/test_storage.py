"""Tests for SQLite storage and stats dashboard."""

from datetime import datetime
from pathlib import Path

import pytest

from rtl_sdr_analyzer.detection.events import JammingEvent
from rtl_sdr_analyzer.storage.database import EventStore
from rtl_sdr_analyzer.storage.stats import StatsDashboard


@pytest.fixture
def temp_db(tmp_path: Path) -> EventStore:
    db = EventStore(tmp_path / "test.db")
    db.init_schema()
    return db


class TestEventStore:
    def test_insert_and_retrieve(self, temp_db: EventStore) -> None:
        event = JammingEvent(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            frequency=446.0,
            power=-30.0,
            bandwidth=12500.0,
            duration=1.5,
            confidence=2.5,
            snr=45.0,
        )
        row_id = temp_db.insert_event(event)
        assert row_id == 1

        events = temp_db.get_recent_events(limit=10)
        assert len(events) == 1
        assert events[0]["frequency_mhz"] == 446.0

    def test_session_tracking(self, temp_db: EventStore) -> None:
        session_id = temp_db.start_session(center_freq_mhz=446.0, sample_rate_hz=2.048e6)
        assert session_id == 1

        temp_db.end_session(total_events=5)
        sessions = temp_db.get_sessions()
        assert len(sessions) == 1
        assert sessions[0]["total_events"] == 5

    def test_top_frequencies(self, temp_db: EventStore) -> None:
        for freq in [446.0, 446.0, 446.0, 100.0]:
            temp_db.insert_event(
                JammingEvent(
                    timestamp=datetime.now(),
                    frequency=freq,
                    power=-30.0,
                    bandwidth=1000.0,
                    duration=1.0,
                    confidence=2.0,
                )
            )

        top = temp_db.get_top_frequencies(limit=2)
        assert len(top) == 2
        assert top[0]["frequency_mhz"] == 446.0
        assert top[0]["count"] == 3

    def test_export_csv(self, temp_db: EventStore, tmp_path: Path) -> None:
        temp_db.insert_event(
            JammingEvent(
                timestamp=datetime(2024, 1, 1, 12, 0, 0),
                frequency=100.0,
                power=-50.0,
                bandwidth=1000.0,
                duration=1.0,
                confidence=2.0,
            )
        )

        output = tmp_path / "export.csv"
        count = temp_db.export_to_csv(output)
        assert count == 1
        assert output.exists()
        assert "frequency_mhz" in output.read_text()


class TestStatsDashboard:
    def test_show_summary(self, temp_db: EventStore, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        dashboard = StatsDashboard(temp_db.db_path)
        # Just verify it doesn't crash
        dashboard.show_summary()
        captured = capsys.readouterr()
        assert "Statistics" in captured.out or captured.out == ""
