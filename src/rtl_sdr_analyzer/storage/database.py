"""SQLite storage for detection events and spectrum data."""

import csv
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional, Union

from rtl_sdr_analyzer.detection.events import JammingEvent

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    frequency_mhz REAL NOT NULL,
    power_db REAL NOT NULL,
    bandwidth_hz REAL NOT NULL,
    duration_s REAL NOT NULL,
    confidence REAL NOT NULL,
    snr REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_frequency ON events(frequency_mhz);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT DEFAULT CURRENT_TIMESTAMP,
    end_time TEXT,
    center_freq_mhz REAL,
    sample_rate_hz REAL,
    total_events INTEGER DEFAULT 0
);
"""


class EventStore:
    """SQLite-backed storage for detection events.

    Example::

        store = EventStore("events.db")
        store.init_schema()
        store.insert_event(event)
    """

    def __init__(self, db_path: Union[Path, str] = "rtl_sdr_analyzer.db"):
        self.db_path = Path(db_path)
        self._session_id: Optional[int] = None

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        logger.info("Database initialized: %s", self.db_path)

    def start_session(
        self,
        center_freq_mhz: float,
        sample_rate_hz: float,
    ) -> int:
        """Start a new monitoring session and return its ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sessions (center_freq_mhz, sample_rate_hz) VALUES (?, ?)",
                (center_freq_mhz, sample_rate_hz),
            )
            self._session_id = cursor.lastrowid
        logger.info("Started session %d", self._session_id)
        return self._session_id

    def end_session(self, total_events: int = 0) -> None:
        """Mark the current session as ended."""
        if self._session_id is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET end_time = CURRENT_TIMESTAMP, total_events = ? WHERE id = ?",
                (total_events, self._session_id),
            )
        logger.info("Ended session %d (%d events)", self._session_id, total_events)
        self._session_id = None

    def insert_event(self, event: JammingEvent) -> int:
        """Insert a detection event and return its row ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events
                (timestamp, frequency_mhz, power_db, bandwidth_hz, duration_s, confidence, snr)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat(),
                    event.frequency,
                    event.power,
                    event.bandwidth,
                    event.duration,
                    event.confidence,
                    event.snr,
                ),
            )
            logger.debug("Inserted event id=%d", cursor.lastrowid)
            return cursor.lastrowid

    def get_recent_events(self, limit: int = 100) -> list[dict]:
        """Get the most recent detection events."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_event_count(self, since: Optional[str] = None) -> int:
        """Get total event count, optionally since a timestamp."""
        with self._connect() as conn:
            if since:
                row = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE timestamp > ?",
                    (since,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0

    def get_top_frequencies(self, limit: int = 10) -> list[dict]:
        """Get frequencies with the most detections."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT frequency_mhz, COUNT(*) as count,
                       AVG(power_db) as avg_power,
                       MAX(power_db) as max_power
                FROM events
                GROUP BY frequency_mhz
                ORDER BY count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_hourly_activity(self) -> list[dict]:
        """Get detection count per hour."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    strftime('%Y-%m-%d %H:00', timestamp) as hour,
                    COUNT(*) as count
                FROM events
                GROUP BY hour
                ORDER BY hour DESC
                LIMIT 24
                """,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_sessions(self, limit: int = 10) -> list[dict]:
        """Get recent monitoring sessions."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def export_to_csv(self, output_path: Path, since: Optional[str] = None) -> int:
        """Export events to CSV and return row count."""
        with self._connect() as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM events WHERE timestamp > ? ORDER BY timestamp",
                    (since,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY timestamp"
                ).fetchall()

        if not rows:
            logger.warning("No events to export.")
            return 0

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(row) for row in rows])

        logger.info("Exported %d events to %s", len(rows), output_path)
        return len(rows)
