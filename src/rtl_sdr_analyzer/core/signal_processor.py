"""Signal Processing Module.

Handles all signal processing operations including FFT, filtering,
and power calculations with proper error handling.
"""

import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np
from scipy.fft import fft, fftshift
from scipy.signal import butter, filtfilt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EPSILON: float = 1e-12
BANDWIDTH_DB_THRESHOLD: float = 3.0  # dB down for bandwidth measurement
DEFAULT_FILTER_ORDER: int = 4
DEFAULT_FILTER_CUTOFF_FRAC: float = 0.1  # fraction of Nyquist


class SignalProcessor:
    """Handles signal processing operations for RTL-SDR data."""

    def __init__(
        self,
        fft_size: int,
        sample_rate: float,
        filter_order: int = DEFAULT_FILTER_ORDER,
        filter_cutoff_frac: float = DEFAULT_FILTER_CUTOFF_FRAC,
    ):
        self.fft_size = fft_size
        self.sample_rate = sample_rate
        self.window = np.blackman(fft_size)
        self.filter_coeffs = self._create_filter(filter_order, filter_cutoff_frac)

    def _create_filter(
        self,
        order: int,
        cutoff_frac: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Create Butterworth filter coefficients.

        Args:
            order: Filter order.
            cutoff_frac: Cutoff frequency as a fraction of the Nyquist rate.

        Returns:
            Tuple of (numerator, denominator) coefficients.
        """
        nyquist = 0.5 * self.fft_size
        cutoff = cutoff_frac * nyquist
        return butter(order, cutoff / nyquist)

    def process_samples(self, iq_data: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """Process IQ samples into a power spectrum.

        Args:
            iq_data: Complex IQ samples.

        Returns:
            Power spectrum in dB, or ``None`` if processing fails.
        """
        try:
            if iq_data is None or len(iq_data) != self.fft_size:
                return None

            # Remove DC offset
            iq_data = iq_data - np.mean(iq_data)

            # Compute FFT with windowing
            fft_data = fftshift(fft(iq_data * self.window))

            # Power spectrum in dB
            power_db = 20 * np.log10(np.abs(fft_data) + EPSILON)

            # Smooth with zero-phase filter
            power_db_smooth = filtfilt(
                self.filter_coeffs[0],
                self.filter_coeffs[1],
                power_db,
            )

            logger.debug("Signal processed successfully")
            return power_db_smooth

        except Exception as exc:  # noqa: BLE001
            logger.error("Error processing samples: %s", exc)
            return None

    def calculate_signal_metrics(
        self,
        spectrum: np.ndarray,
        freq_range: np.ndarray,
    ) -> Dict[str, float]:
        """Calculate various signal metrics from the spectrum.

        Args:
            spectrum: Power spectrum in dB.
            freq_range: Frequency range array in MHz.

        Returns:
            Dictionary containing signal metrics.
        """
        try:
            return {
                "max_power": float(np.max(spectrum)),
                "mean_power": float(np.mean(spectrum)),
                "peak_frequency": float(freq_range[np.argmax(spectrum)]),
                "bandwidth": self._calculate_bandwidth(spectrum, freq_range),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Error calculating metrics: %s", exc)
            return {}

    def _calculate_bandwidth(
        self,
        spectrum: np.ndarray,
        freq_range: np.ndarray,
    ) -> float:
        """Calculate the bandwidth of the strongest signal.

        Uses the ``BANDWIDTH_DB_THRESHOLD`` dB down method.

        Args:
            spectrum: Power spectrum in dB.
            freq_range: Frequency range array in MHz.

        Returns:
            Bandwidth in Hz.
        """
        try:
            max_power: float = float(np.max(spectrum))
            mask = spectrum > (max_power - BANDWIDTH_DB_THRESHOLD)
            bin_width_mhz = float(freq_range[1] - freq_range[0])
            return float(np.sum(mask) * bin_width_mhz * 1e6)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error calculating bandwidth: %s", exc)
            return 0.0
