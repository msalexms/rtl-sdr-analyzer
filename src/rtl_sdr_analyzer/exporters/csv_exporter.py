"""CSV exporter for detection events."""

import csv
import logging
from pathlib import Path
from typing import Optional

from rtl_sdr_analyzer.detection.events import JammingEvent

from .base import Exporter

logger = logging.getLogger(__name__)


class CsvExporter(Exporter):
    """Append detection events to a CSV file."""

    def __init__(self, output_path: Optional[Path] = None) -> None:
        super().__init__(output_path)
        self._file: Optional[object] = None
        self._writer: Optional[csv.DictWriter] = None

        if self.output_path is not None:
            self._open_file()

    def _open_file(self) -> None:
        path = Path(self.output_path)
        file_exists = path.exists()
        self._file = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=[
                "timestamp",
                "frequency",
                "power",
                "bandwidth",
                "duration",
                "confidence",
                "snr",
                "center_offset",
            ],
        )
        if not file_exists:
            self._writer.writeheader()

    def export(self, event: JammingEvent) -> None:
        if self._writer is None:
            logger.warning("CSV exporter has no output path configured")
            return
        row = event.model_dump(mode="json")
        self._writer.writerow(row)
        self._file.flush()
        logger.debug("Exported event to CSV: %s", row.get("timestamp"))

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None
