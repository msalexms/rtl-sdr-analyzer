"""Main orchestrator coordinating all analyzer components."""

import logging
import signal
import time
from typing import Any

from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase
from rtl_sdr_analyzer.core.signal_processor import SignalProcessor
from rtl_sdr_analyzer.detection.detector import SignalDetector
from rtl_sdr_analyzer.exporters.base import Exporter
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
        event_bus: EventBus | None = None,
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
        self._exporters: list[Any] = []

    def add_exporter(self, exporter: Exporter) -> None:
        """Register an exporter to be closed on shutdown."""
        self._exporters.append(exporter)
        logger.info("Registered exporter: %s", type(exporter).__name__)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _handle_sigterm(self, signum: int, _frame: object) -> None:
        """Handle SIGTERM for daemon mode."""
        logger.info("SIGTERM received — shutting down.")
        self._running = False

    def start(self) -> None:
        """Start the acquisition and analysis loop.

        Blocks until the visualization loop exits or KeyboardInterrupt is raised.
        """
        # Only trap SIGTERM; leave SIGINT to raise KeyboardInterrupt naturally
        # so Ctrl+C works immediately without waiting for socket timeouts.
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        self._running = True
        self._error_count = 0
        logger.info("Starting signal analyzer...")

        try:
            with self.rtlsdr:
                self.visualization.start(self._update)
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Analyzer failed: %s", exc)
            raise
        finally:
            self._running = False
            self._close_exporters()
            logger.info("Analyzer stopped.")

    def stop(self) -> None:
        """Request graceful shutdown."""
        self._running = False
        self.visualization.stop()

    def _close_exporters(self) -> None:
        """Close all registered exporters."""
        for exporter in self._exporters:
            try:
                exporter.close()
                logger.debug("Closed exporter: %s", type(exporter).__name__)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing exporter: %s", exc)
        self._exporters.clear()

    # ------------------------------------------------------------------
    # Update loop
    # ------------------------------------------------------------------

    def _update(self, _frame: int) -> list[Any]:
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
