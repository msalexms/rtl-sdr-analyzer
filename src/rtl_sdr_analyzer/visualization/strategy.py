"""Visualization strategy protocol."""

from typing import Optional, Protocol, runtime_checkable

import numpy as np

from rtl_sdr_analyzer.detection.events import JammingEvent


@runtime_checkable
class VisualizationStrategy(Protocol):
    """Protocol for real-time visualization backends."""

    def start(self, update_func) -> None:
        """Start the visualization loop."""
        ...

    def stop(self) -> None:
        """Stop the visualization loop."""
        ...

    def update(
        self,
        spectrum: Optional[np.ndarray],
        event: Optional[JammingEvent] = None,
    ) -> list:
        """Update the display with new spectrum data."""
        ...

    def get_artists(self) -> list:
        """Return drawable artists (for matplotlib blit support)."""
        ...
