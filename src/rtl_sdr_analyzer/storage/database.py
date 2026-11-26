"""SQLite storage for detection events and monitoring sessions."""

import csv
import json
import logging
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rtl_sdr_analyzer.detection.events import SignalEvent

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    center_freq_mhz REAL,
    sample_rate_hz REAL,
    total_events INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    timestamp TEXT NOT NULL,
    frequency_mhz REAL NOT NULL,
    power_db REAL NOT NULL,
    bandwidth_hz REAL NOT NULL,
    duration_s REAL NOT NULL,
    confidence REAL NOT NULL,
    snr REAL,
    center_offset_hz REAL,
    noise_floor_db REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_frequency ON events(frequency_mhz);
"""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EventStore:
    """Thread-safe SQLite-backed storage for RF detection events and sessions."""

    def __init__(self, db_path: Path | str = "rtl_sdr_analyzer.db") -> None:
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._session_id: int | None = None
        self._session_event_count: int = 0
        self._conn: sqlite3.Connection | None = None

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield the shared connection inside a transaction (serialized by ``_lock``)."""
        with self._lock:
            if self._conn is None:
                if self.db_path != Path(":memory:"):
                    self.db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                self._conn = conn
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        """Close the underlying connection (reopened lazily on next use)."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def init_schema(self) -> None:
        """Create tables and indexes, migrating older v2 schemas safely if present."""
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
            if "session_id" not in cols:
                conn.execute("ALTER TABLE events ADD COLUMN session_id INTEGER")
            if "center_offset_hz" not in cols:
                conn.execute("ALTER TABLE events ADD COLUMN center_offset_hz REAL")
            if "noise_floor_db" not in cols:
                conn.execute("ALTER TABLE events ADD COLUMN noise_floor_db REAL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
        logger.debug("Database schema ready: %s", self.db_path)

    def start_session(self, center_freq_mhz: float, sample_rate_hz: float) -> int:
        """Start a new monitoring session and return its ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sessions (start_time, center_freq_mhz, sample_rate_hz) VALUES (?, ?, ?)",
                (_utc_now_iso(), center_freq_mhz, sample_rate_hz),
            )
            row_id = cursor.lastrowid
            if row_id is None:
                raise RuntimeError("Failed to create monitoring session")
            self._session_id = row_id
            self._session_event_count = 0
        logger.info("Started session %d", self._session_id)
        return self._session_id

    def end_session(self, total_events: int | None = None) -> None:
        """Mark the current session as ended and persist accurate event count."""
        with self._lock:
            if self._session_id is None:
                return
            count = self._session_event_count if total_events is None else total_events
            session_id = self._session_id
            with self._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET end_time = ?, total_events = ? WHERE id = ?",
                    (_utc_now_iso(), count, session_id),
                )
            logger.info("Ended session %d (%d events)", session_id, count)
            self._session_id = None
            self._session_event_count = 0

    def insert_event(self, event: SignalEvent) -> int:
        """Insert a detection event and return its row ID."""
        ts = event.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    session_id, timestamp, frequency_mhz, power_db,
                    bandwidth_hz, duration_s, confidence, snr,
                    center_offset_hz, noise_floor_db
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._session_id,
                    ts.astimezone(UTC).isoformat(),
                    event.frequency,
                    event.power,
                    event.bandwidth,
                    event.duration,
                    event.confidence,
                    event.snr,
                    event.center_offset,
                    event.noise_floor,
                ),
            )
            row_id = cursor.lastrowid
            if row_id is None:
                raise RuntimeError("Failed to insert detection event")
            if self._session_id is not None:
                self._session_event_count += 1
            return row_id

    def get_recent_events(
        self, limit: int = 100, since_hours: int | None = None
    ) -> list[dict[str, Any]]:
        """Return recent detection events newest-first."""
        with self._connect() as conn:
            if since_hours is not None:
                cutoff = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()
                rows = conn.execute(
                    "SELECT * FROM events WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_event_count(self, since: str | None = None) -> int:
        """Return total event count, optionally filtered after ISO timestamp ``since``."""
        with self._connect() as conn:
            if since:
                row = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE timestamp > ?",
                    (since,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0]) if row else 0

    def get_top_frequencies(
        self, limit: int = 10, since_hours: int | None = None
    ) -> list[dict[str, Any]]:
        """Return frequencies ordered by detection count."""
        with self._connect() as conn:
            if since_hours is not None:
                cutoff = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()
                rows = conn.execute(
                    """
                    SELECT ROUND(frequency_mhz, 3) AS frequency_mhz,
                           COUNT(*) AS count,
                           AVG(power_db) AS avg_power,
                           MAX(power_db) AS max_power
                    FROM events
                    WHERE timestamp > ?
                    GROUP BY ROUND(frequency_mhz, 3)
                    ORDER BY count DESC
                    LIMIT ?
                    """,
                    (cutoff, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT ROUND(frequency_mhz, 3) AS frequency_mhz,
                           COUNT(*) AS count,
                           AVG(power_db) AS avg_power,
                           MAX(power_db) AS max_power
                    FROM events
                    GROUP BY ROUND(frequency_mhz, 3)
                    ORDER BY count DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_hourly_activity(self, hours: int = 24) -> list[dict[str, Any]]:
        """Return detection count grouped by UTC hour."""
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT strftime('%Y-%m-%d %H:00', timestamp) AS hour,
                       COUNT(*) AS count
                FROM events
                WHERE timestamp > ?
                GROUP BY hour
                ORDER BY hour DESC
                LIMIT ?
                """,
                (cutoff, hours),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent monitoring sessions."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_events(self) -> int:
        """Delete all stored detection events and return deleted count."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM events")
            return int(cur.rowcount or 0)

    def _query_events_for_export(self, since: str | None = None) -> list[sqlite3.Row]:
        with self._connect() as conn:
            if since:
                return conn.execute(
                    "SELECT * FROM events WHERE timestamp > ? ORDER BY timestamp",
                    (since,),
                ).fetchall()
            return conn.execute("SELECT * FROM events ORDER BY timestamp").fetchall()

    def export_to_csv(self, output_path: Path, since: str | None = None) -> int:
        """Export events to CSV and return row count."""
        rows = self._query_events_for_export(since=since)
        if not rows:
            logger.warning("No events to export.")
            return 0
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows([dict(row) for row in rows])
        logger.info("Exported %d events to %s", len(rows), output_path)
        return len(rows)

    def export_to_jsonl(self, output_path: Path, since: str | None = None) -> int:
        """Export events to JSON Lines and return row count."""
        rows = self._query_events_for_export(since=since)
        if not rows:
            return 0
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(dict(row)) + "\n")
        return len(rows)
