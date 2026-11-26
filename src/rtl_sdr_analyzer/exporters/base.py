"""Abstract base class for detection event exporters."""

from abc import ABC, abstractmethod
from pathlib import Path
from types import TracebackType

from rtl_sdr_analyzer.detection.events import SignalEvent


class Exporter(ABC):
    """Base interface for persisting :class:`SignalEvent` objects."""

    def __init__(self, output_path: Path | None = None) -> None:
        self.output_path = Path(output_path) if output_path is not None else None

    def __enter__(self) -> "Exporter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    @abstractmethod
    def export(self, event: SignalEvent) -> None:
        """Write a single event to the target output."""

    @abstractmethod
    def close(self) -> None:
        """Finalize and close any open resources."""
