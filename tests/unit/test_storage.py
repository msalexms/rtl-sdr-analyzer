"""Unit tests for WAL SQLite EventStore, v2 migration, and StatsDashboard."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from rtl_sdr_analyzer.detection.events import SignalEvent
from rtl_sdr_analyzer.storage.database import EventStore
from rtl_sdr_analyzer.storage.stats import StatsDashboard


def _make_event(freq: float = 446.006, power: float = -32.0) -> SignalEvent:
    return SignalEvent(
        timestamp=datetime.now(UTC),
        frequency=freq,
        power=power,
        bandwidth=12_500.0,
        duration=0.5,
        confidence=2.0,
        snr=42.0,
        center_offset=6_000.0,
        noise_floor=-74.0,
    )


class TestEventStore:
    def test_session_and_event_lifecycle(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "sub" / "events.db")
        store.init_schema()

        sid = store.start_session(center_freq_mhz=446.0, sample_rate_hz=2.048e6)
        store.insert_event(_make_event(446.006, -30.0))
        store.insert_event(_make_event(446.056, -40.0))
        store.end_session()

        sessions = store.get_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid
        assert sessions[0]["total_events"] == 2
        assert sessions[0]["end_time"] is not None

        recent = store.get_recent_events(limit=10)
        assert len(recent) == 2
        assert recent[0]["session_id"] == sid

    def test_migrates_legacy_v2_schema(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                frequency_mhz REAL NOT NULL,
                power_db REAL NOT NULL,
                bandwidth_hz REAL NOT NULL,
                duration_s REAL NOT NULL,
                confidence REAL NOT NULL,
                snr REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()

        store = EventStore(db_path)
        store.init_schema()
        store.insert_event(_make_event())
        assert store.get_event_count() == 1

    def test_export_csv_and_jsonl(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        store.init_schema()
        store.insert_event(_make_event(98.5, -25.0))

        csv_out = tmp_path / "out.csv"
        jsonl_out = tmp_path / "out.jsonl"
        assert store.export_to_csv(csv_out) == 1
        assert store.export_to_jsonl(jsonl_out) == 1
        assert "98.5" in csv_out.read_text(encoding="utf-8")
        assert "98.5" in jsonl_out.read_text(encoding="utf-8")


class TestStatsDashboard:
    def test_renders_without_error(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "stats.db")
        store.init_schema()
        store.start_session(98.0, 2.048e6)
        store.insert_event(_make_event(98.5, -25.0))
        store.end_session()

        dash = StatsDashboard(store.db_path)
        dash.show_summary()
        dash.show_top_frequencies()
        dash.show_hourly_activity()
        dash.show_recent_events()
        assert dash.export_csv(tmp_path / "dash.csv", since_hours=24) == 1
