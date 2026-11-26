"""Headless console runner for daemon/CLI mode."""

import logging
import signal
import threading

from rich.console import Console

from rtl_sdr_analyzer.detection.events import SpectrumFrame
from rtl_sdr_analyzer.engine.spectrum_engine import SpectrumEngine

logger = logging.getLogger(__name__)


class HeadlessRunner:
    """Runs :class:`SpectrumEngine` cleanly in console/daemon mode until interrupted."""

    def __init__(
        self,
        engine: SpectrumEngine,
        *,
        log_interval_frames: int = 20,
        max_frames: int | None = None,
        console: Console | None = None,
    ) -> None:
        self.engine = engine
        self.log_interval_frames = max(1, log_interval_frames)
        self.max_frames = max_frames
        self.console = console or Console()
        self._stop_event = threading.Event()
        self._frames = 0

    def _on_frame(self, frame: SpectrumFrame) -> None:
        self._frames += 1
        if self._frames % self.log_interval_frames == 0:
            logger.info(
                "Spectrum [%d] | center=%.3f MHz | floor=%.1f dBFS | peak=%.4f MHz (%.1f dBFS, SNR %.1f dB) | %.1f fps",
                frame.seq,
                frame.center_freq_hz / 1e6,
                frame.noise_floor_db,
                frame.peak_freq_mhz,
                frame.peak_power_db,
                frame.peak_snr_db,
                frame.fps,
            )
        if frame.event is not None:
            ev = frame.event
            self.console.print(
                f"[bold #D9C26A]SIGNAL[/bold #D9C26A] "
                f"[bold #9EA6F2]{ev.frequency:.4f} MHz[/bold #9EA6F2]  "
                f"power=[#E9E6E0]{ev.power:.1f} dBFS[/#E9E6E0]  "
                f"snr=[#8FD3A4]+{ev.snr:.1f} dB[/#8FD3A4]  "
                f"bw=[#9E9AA8]{ev.bandwidth / 1e3:.1f} kHz[/#9E9AA8]  "
                f"dur=[#9E9AA8]{ev.duration:.2f}s[/#9E9AA8]"
            )
        if self.max_frames is not None and self._frames >= self.max_frames:
            self._stop_event.set()

    def run(self) -> int:
        """Start engine and block until SIGINT/SIGTERM or ``max_frames``."""
        self._stop_event.clear()
        self._frames = 0
        self.engine.subscribe_frames(self._on_frame)

        prev_sigterm = None
        if threading.current_thread() is threading.main_thread():
            prev_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, lambda *_: self._stop_event.set())

        try:
            self.engine.start()
            while not self._stop_event.wait(0.2):
                if not self.engine.is_running:
                    break
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
        finally:
            self.engine.unsubscribe_frames(self._on_frame)
            self.engine.stop()
            if prev_sigterm is not None:
                signal.signal(signal.SIGTERM, prev_sigterm)
        return self._frames
