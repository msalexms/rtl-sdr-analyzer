"""CSV exporter for detection events."""

import csv
import logging
import threading
from pathlib import Path
from typing import Any, TextIO

from rtl_sdr_analyzer.detection.events import SignalEvent

from .base import Exporter

logger = logging.getLogger(__name__)

CSV_FIELDS: list[str] = [
    "timestamp",
    "frequency",
    "power",
    "bandwidth",
    "duration",
    "confidence",
    "snr",
    "center_offset",
    "noise_floor",
]


class CsvExporter(Exporter):
    """Thread-safe append exporter writing detection events to CSV."""

    def __init__(self, output_path: Path | None = None) -> None:
        super().__init__(output_path)
        self._lock = threading.Lock()
        self._file: TextIO | None = None
        self._writer: csv.DictWriter[str] | None = None

        if self.output_path is not None:
            self._open_file()

    def _open_file(self) -> None:
        if self.output_path is None:
            return
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.output_path.exists() or self.output_path.stat().st_size == 0
        self._file = open(self.output_path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            self._writer.writeheader()
            self._file.flush()

    def export(self, event: SignalEvent) -> None:
        with self._lock:
            if self._writer is None or self._file is None:
                logger.warning("CSV exporter has no output path configured")
                return
            row: dict[str, Any] = event.model_dump(mode="json")
            self._writer.writerow(row)
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
                self._writer = None
