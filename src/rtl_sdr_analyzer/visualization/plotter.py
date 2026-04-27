"""Real-time spectrum visualization using matplotlib."""

import logging
from collections import deque
from typing import Any, Optional

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

from rtl_sdr_analyzer.detection.events import JammingEvent

logger = logging.getLogger(__name__)


class MatplotlibVisualization:
    """Real-time spectrum and waterfall plotter."""

    def __init__(
        self,
        freq_range: np.ndarray,
        waterfall_length: int = 50,
        update_interval: int = 50,
    ):
        self.freq_range = freq_range
        self.waterfall_length = waterfall_length
        self.update_interval = update_interval
        self.animation: Optional[FuncAnimation] = None

        # Waterfall data buffer
        self.waterfall_data = deque(
            [np.full(len(freq_range), -100) for _ in range(waterfall_length)],
            maxlen=waterfall_length,
        )

        self._setup_plot()
        self.event_markers: list[Any] = []

    def _setup_plot(self) -> None:
        """Set up the matplotlib figure and axes."""
        plt.style.use("dark_background")
        self.fig, (self.ax_spectrum, self.ax_waterfall) = plt.subplots(
            2,
            1,
            figsize=(12, 8),
            gridspec_kw={"height_ratios": [4, 1]},
            tight_layout=True,
        )

        # Configure figure appearance
        self.fig.patch.set_facecolor("#000000")
        for ax in (self.ax_spectrum, self.ax_waterfall):
            ax.set_facecolor("#000000")
            ax.tick_params(axis="both", colors="white")
            for spine in ax.spines.values():
                spine.set_color("#444444")

        # Spectrum plot
        self.line_spectrum, = self.ax_spectrum.plot([], [], "w-", lw=1)
        self.ax_spectrum.set_xlim(self.freq_range[0], self.freq_range[-1])
        self.ax_spectrum.set_ylim(-100, -30)
        self.ax_spectrum.set_ylabel("Power (dB)", color="white")
        self.ax_spectrum.grid(True, color="#333333", alpha=0.5)

        # Waterfall plot
        self.waterfall_img = self.ax_waterfall.imshow(
            np.array(self.waterfall_data),
            aspect="auto",
            cmap="jet",
            extent=[
                self.freq_range[0],
                self.freq_range[-1],
                0,
                self.waterfall_length,
            ],
            vmin=-90,
            vmax=-20,
        )
        self.ax_waterfall.set_xlabel("Frequency (MHz)", color="white")

    def update(
        self,
        spectrum: Optional[np.ndarray],
        event: Optional[JammingEvent] = None,
    ) -> list[Any]:
        """Update the plot with new spectrum data."""
        if spectrum is None:
            return self.get_artists()

        self.line_spectrum.set_data(self.freq_range, spectrum)
        self.waterfall_data.appendleft(spectrum)
        self.waterfall_img.set_array(np.array(self.waterfall_data))

        if event:
            self._mark_event(event)

        # Dynamic range adjustment
        pmin = float(np.min(spectrum))
        pmax = float(np.max(spectrum))
        self.ax_spectrum.set_ylim(pmin - 10, pmax + 10)
        self.waterfall_img.set_clim(pmin - 10, pmax + 10)

        return [self.line_spectrum, self.waterfall_img] + self.event_markers

    def _mark_event(self, event: JammingEvent) -> None:
        """Mark a detection event on the plot."""
        for marker in self.event_markers:
            marker.remove()
        self.event_markers.clear()

        marker = self.ax_spectrum.axvline(
            x=event.frequency,
            color="r",
            alpha=0.5,
            linestyle="--",
        )
        self.event_markers.append(marker)

    def start(self, update_func: Any) -> None:
        """Start the real-time animation."""
        self.animation = FuncAnimation(
            self.fig,
            update_func,
            interval=self.update_interval,
            blit=True,
            cache_frame_data=False,
        )
        plt.show(block=True)

    def stop(self) -> None:
        """Stop the animation."""
        if self.animation is not None:
            self.animation.event_source.stop()

    def get_artists(self) -> list[Any]:
        """Return all plot artists."""
        return [self.line_spectrum, self.waterfall_img] + self.event_markers
