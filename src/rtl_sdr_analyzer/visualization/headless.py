"""Headless (non-GUI) visualization for daemon/CLI mode."""

import logging
from collections import deque
from typing import Optional

import numpy as np

from rtl_sdr_analyzer.detection.events import JammingEvent

logger = logging.getLogger(__name__)


class HeadlessVisualization:
    """Console-only visualization that logs spectrum statistics.

    Implements the same interface as :class:`MatplotlibVisualization`
    so it can be swapped in when running without a display.
    """

    def __init__(
        self,
        freq_range: np.ndarray,
        waterfall_length: int = 50,
        update_interval: int = 50,
        log_interval_frames: int = 10,
    ):
        self.freq_range = freq_range
        self.waterfall_length = waterfall_length
        self.update_interval = update_interval
        self.log_interval_frames = log_interval_frames
        self._frame_count = 0
        self._running = False

        # Maintain a small history for basic stats
        self.power_history = deque(maxlen=waterfall_length)

    def update(
        self,
        spectrum: Optional[np.ndarray],
        event: Optional[JammingEvent] = None,
    ) -> list:
        """Log spectrum statistics instead of rendering."""
        if spectrum is None:
            return []

        self._frame_count += 1
        self.power_history.append(float(np.mean(spectrum)))

        if self._frame_count % self.log_interval_frames == 0:
            pmin = float(np.min(spectrum))
            pmax = float(np.max(spectrum))
            mean = float(np.mean(spectrum))
            logger.info(
                "Spectrum stats [%d] | mean=%.1f dB | min=%.1f dB | max=%.1f dB",
                self._frame_count,
                mean,
                pmin,
                pmax,
            )

        if event:
            logger.info(
                "DETECTION | freq=%.3f MHz | power=%.1f dB | bw=%.0f Hz | dur=%.2f s | conf=%.2f",
                event.frequency,
                event.power,
                event.bandwidth,
                event.duration,
                event.confidence,
            )

        return []

    def start(self, update_func) -> None:
        """Run the update loop without matplotlib.

        Relies on the outer signal handler (registered by Analyzer) to set
        _running = False on SIGINT/SIGTERM.
        """
        self._running = True
        while self._running:
            try:
                update_func(0)
            except Exception as exc:  # noqa: BLE001
                logger.error("Error in headless update loop: %s", exc)

    def stop(self) -> None:
        """Signal the loop to exit."""
        self._running = False

    def get_artists(self) -> list:
        """No artists in headless mode."""
        return []
