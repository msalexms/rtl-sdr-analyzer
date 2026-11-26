"""JSON Lines exporter for detection events."""

import json
import logging
import threading
from pathlib import Path
from typing import Any, TextIO

from rtl_sdr_analyzer.detection.events import SignalEvent

from .base import Exporter

logger = logging.getLogger(__name__)


class JsonExporter(Exporter):
    """Thread-safe append exporter writing detection events to JSON Lines."""

    def __init__(self, output_path: Path | None = None) -> None:
        super().__init__(output_path)
        self._lock = threading.Lock()
        self._file: TextIO | None = None

        if self.output_path is not None:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.output_path, "a", encoding="utf-8")

    def export(self, event: SignalEvent) -> None:
        with self._lock:
            if self._file is None:
                logger.warning("JSON exporter has no output path configured")
                return
            record: dict[str, Any] = event.model_dump(mode="json")
            self._file.write(json.dumps(record) + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
