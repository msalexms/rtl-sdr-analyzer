"""JSON Lines exporter for detection events."""

import json
import logging
from pathlib import Path
from typing import Any, Optional, TextIO

from rtl_sdr_analyzer.detection.events import JammingEvent

from .base import Exporter

logger = logging.getLogger(__name__)


class JsonExporter(Exporter):
    """Append detection events to a JSON Lines file."""

    def __init__(self, output_path: Optional[Path] = None) -> None:
        super().__init__(output_path)
        self._file: Optional[TextIO] = None

        if self.output_path is not None:
            self._file = open(self.output_path, "a", encoding="utf-8")

    def export(self, event: JammingEvent) -> None:
        if self._file is None:
            logger.warning("JSON exporter has no output path configured")
            return
        record: dict[str, Any] = event.model_dump(mode="json")
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()
        logger.debug("Exported event to JSON: %s", record.get("timestamp"))

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
