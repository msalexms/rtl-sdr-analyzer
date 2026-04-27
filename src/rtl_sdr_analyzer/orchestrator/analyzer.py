"""Main orchestrator coordinating all analyzer components."""

import logging
import signal
import time
from typing import Optional

from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase
from rtl_sdr_analyzer.core.signal_processor import SignalProcessor
from rtl_sdr_analyzer.detection.detector import SignalDetector
from rtl_sdr_analyzer.orchestrator.event_bus import EventBus
from rtl_sdr_analyzer.visualization.strategy import VisualizationStrategy

logger = logging.getLogger(__name__)


class Analyzer:
    """Coordinates RTL-SDR acquisition, processing, detection, and visualization.

    All dependencies are injected via the constructor, making the class fully
    testable without hardware.

    Example::

        analyzer = Analyzer(
            rtlsdr=rtl,
            processor=proc,
            detector=det,
            visualization=plotter,
            event_bus=bus,
        )
        analyzer.start()
    """

    def __init__(
        self,
        rtlsdr: RTLSDRBase,
        processor: SignalProcessor,
        detector: SignalDetector,
        visualization: VisualizationStrategy,
        event_bus: Optional[EventBus] = None,
        max_errors: int = 5,
    ):
        self.rtlsdr = rtlsdr
        self.processor = processor
        self.detector = detector
        self.visualization = visualization
        self.event_bus = event_bus or EventBus()
        self.max_errors = max_errors
        self._running = False
        self._error_count = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _handle_signal(self, signum: int, _frame: object) -> None:
        """Set the running flag to False on SIGINT/SIGTERM."""
        logger.info("Shutdown signal %d received", signum)
        self._running = False

    def start(self) -> None:
        """Start the acquisition and analysis loop.

        Blocks until the visualization loop exits or a signal is received.
        """
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        self._running = True
        self._error_count = 0
        logger.info("Starting signal analyzer...")

        try:
            with self.rtlsdr:
                self.visualization.start(self._update)
        except Exception as exc:  # noqa: BLE001
            logger.error("Analyzer failed: %s", exc)
            raise
        finally:
            self._running = False
            logger.info("Analyzer stopped.")

    def stop(self) -> None:
        """Request graceful shutdown."""
        self._running = False
        self.visualization.stop()

    # ------------------------------------------------------------------
    # Update loop
    # ------------------------------------------------------------------

    def _update(self, _frame: int) -> list:
        """Single iteration of the acquisition → process → detect → visualize pipeline."""
        if not self._running:
            return self.visualization.get_artists()

        try:
            iq_data = self.rtlsdr.read_samples()
            if iq_data is None:
                return self.visualization.get_artists()

            spectrum = self.processor.process_samples(iq_data)
            if spectrum is None:
                return self.visualization.get_artists()

            event = self.detector.detect_signal(
                spectrum,
                self.rtlsdr.freq_range,
                time.time(),
            )

            if event is not None:
                self.event_bus.publish(event)

            return self.visualization.update(spectrum, event)

        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            logger.error(
                "Update loop error (%d/%d): %s",
                self._error_count,
                self.max_errors,
                exc,
            )
            if self._error_count >= self.max_errors:
                logger.error("Maximum error count reached — shutting down.")
                self._running = False
            return self.visualization.get_artists()
