"""Abstract base class for detection event exporters."""

from abc import ABC, abstractmethod
from pathlib import Path

from rtl_sdr_analyzer.detection.events import JammingEvent


class Exporter(ABC):
    """Base interface for persisting :class:`JammingEvent` objects."""

    def __init__(self, output_path: Path | None = None) -> None:
        self.output_path = output_path

    @abstractmethod
    def export(self, event: JammingEvent) -> None:
        """Write a single event to the target output."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Finalize and close any open resources."""
        ...
