"""Pure-NumPy calibrated PSD estimation, noise floor, and peak extraction."""

import math

import numpy as np
from pydantic import BaseModel

from rtl_sdr_analyzer.config.models import WindowType

EPSILON: float = 1e-15


class PeakInfo(BaseModel, frozen=True):
    """Spectral peak detected inside a single FFT frame."""

    frequency_mhz: float
    power_db: float
    snr_db: float
    bandwidth_hz: float
    offset_hz: float


def build_window(name: WindowType, size: int) -> np.ndarray:
    """Create a symmetric spectral analysis window of length ``size``."""
    if size <= 1:
        return np.ones(max(1, size), dtype=np.float64)
    if name == "hann":
        return np.hanning(size)
    if name == "hamming":
        return np.hamming(size)
    if name == "rectangular":
        return np.ones(size, dtype=np.float64)
    # 4-term Blackman-Harris
    n = np.arange(size, dtype=np.float64)
    phase = 2.0 * math.pi * n / (size - 1)
    return (
        0.35875
        - 0.48829 * np.cos(phase)
        + 0.14128 * np.cos(2.0 * phase)
        - 0.01168 * np.cos(3.0 * phase)
    )


def compute_freq_axis_mhz(
    center_freq_hz: float,
    sample_rate_hz: float,
    fft_size: int,
) -> np.ndarray:
    """Compute centered RF frequency axis in MHz matching ``fftshift(fft(...))``."""
    offsets_hz = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate_hz))
    return (center_freq_hz + offsets_hz) / 1e6


def estimate_noise_floor(spectrum: np.ndarray) -> tuple[float, float]:
    """Estimate robust ``(noise_floor_db, robust_std_db)`` via median and MAD."""
    if len(spectrum) == 0:
        return (-120.0, 1.0)
    median = float(np.median(spectrum))
    mad = float(np.median(np.abs(spectrum - median)))
    sigma = max(1.4826 * mad, 0.5)
    return (median, sigma)


def measure_bandwidth_hz(
    spectrum: np.ndarray,
    peak_idx: int,
    bin_width_hz: float,
    drop_db: float = 3.0,
) -> float:
    """Measure contiguous ``-drop_db`` bandwidth around ``peak_idx`` in Hz."""
    n = len(spectrum)
    if n == 0 or peak_idx < 0 or peak_idx >= n or bin_width_hz <= 0:
        return 0.0

    cutoff = float(spectrum[peak_idx]) - drop_db
    left = peak_idx
    while left > 0 and spectrum[left - 1] >= cutoff:
        left -= 1

    right = peak_idx
    while right < n - 1 and spectrum[right + 1] >= cutoff:
        right += 1

    return float((right - left + 1) * bin_width_hz)


class SignalProcessor:
    """Calibrated Welch-averaged PSD processor yielding dBFS spectra."""

    def __init__(
        self,
        fft_size: int = 2048,
        sample_rate: float = 2.048e6,
        window: WindowType = "blackmanharris",
        averaging: int = 4,
        ema_alpha: float = 0.35,
        remove_dc: bool = True,
    ) -> None:
        self.fft_size = int(fft_size)
        self.sample_rate = float(sample_rate)
        self.window_name: WindowType = window
        self.averaging = max(1, int(averaging))
        self.ema_alpha = float(ema_alpha)
        self.remove_dc = bool(remove_dc)

        self._window = build_window(self.window_name, self.fft_size)
        self._coherent_gain = float(np.sum(self._window))
        self._ema_linear: np.ndarray | None = None

    def reset(self) -> None:
        """Reset temporal averaging state (e.g. after retuning)."""
        self._ema_linear = None

    def reconfigure(
        self,
        *,
        fft_size: int | None = None,
        sample_rate: float | None = None,
        window: WindowType | None = None,
        averaging: int | None = None,
        ema_alpha: float | None = None,
        remove_dc: bool | None = None,
    ) -> None:
        """Update DSP parameters cleanly and reset temporal filter when geometry changes."""
        rebuild_window = False
        reset_ema = False

        if fft_size is not None and int(fft_size) != self.fft_size:
            self.fft_size = int(fft_size)
            rebuild_window = True
            reset_ema = True
        if sample_rate is not None and float(sample_rate) != self.sample_rate:
            self.sample_rate = float(sample_rate)
            reset_ema = True
        if window is not None and window != self.window_name:
            self.window_name = window
            rebuild_window = True
            reset_ema = True
        if averaging is not None:
            self.averaging = max(1, int(averaging))
        if ema_alpha is not None:
            self.ema_alpha = float(ema_alpha)
        if remove_dc is not None:
            self.remove_dc = bool(remove_dc)

        if rebuild_window:
            self._window = build_window(self.window_name, self.fft_size)
            self._coherent_gain = float(np.sum(self._window))
        if reset_ema:
            self.reset()

    def process_samples(self, iq_data: np.ndarray | None) -> np.ndarray | None:
        """Compute calibrated dBFS power spectrum from complex IQ samples."""
        if iq_data is None or len(iq_data) < self.fft_size:
            return None

        n_samples = len(iq_data)
        n_fft = self.fft_size
        step = n_fft if n_samples >= n_fft * self.averaging else max(1, n_fft // 2)

        starts = range(0, n_samples - n_fft + 1, step)
        blocks_list = [
            iq_data[s : s + n_fft] for _, s in zip(range(self.averaging), starts, strict=False)
        ]
        if not blocks_list:
            return None

        blocks = np.asarray(blocks_list, dtype=np.complex128)
        if self.remove_dc:
            blocks = blocks - np.mean(blocks, axis=1, keepdims=True)

        windowed = blocks * self._window[np.newaxis, :]
        fft_out = np.fft.fftshift(np.fft.fft(windowed, axis=1), axes=1) / self._coherent_gain
        power_lin = np.mean(fft_out.real**2 + fft_out.imag**2, axis=0)

        if self.ema_alpha < 1.0:
            if self._ema_linear is None or len(self._ema_linear) != n_fft:
                self._ema_linear = power_lin
            else:
                self._ema_linear = (
                    self.ema_alpha * power_lin + (1.0 - self.ema_alpha) * self._ema_linear
                )
            effective_lin = self._ema_linear
        else:
            effective_lin = power_lin

        return 10.0 * np.log10(effective_lin + EPSILON)

    def find_peaks(
        self,
        spectrum: np.ndarray,
        freqs_mhz: np.ndarray,
        center_freq_hz: float,
        noise_floor_db: float | None = None,
        min_snr_db: float = 8.0,
        max_peaks: int = 8,
        min_sep_bins: int = 5,
    ) -> list[PeakInfo]:
        """Extract prominent local spectral peaks above ``noise_floor_db + min_snr_db``."""
        n = len(spectrum)
        if n < 3 or len(freqs_mhz) != n:
            return []

        if noise_floor_db is None:
            noise_floor_db, _ = estimate_noise_floor(spectrum)

        bin_width_hz = self.sample_rate / n
        cutoff = noise_floor_db + min_snr_db

        # Local maxima (including edge bins carefully)
        mid_mask = (spectrum[1:-1] >= spectrum[:-2]) & (spectrum[1:-1] >= spectrum[2:])
        candidates: list[int] = [int(x) for x in np.flatnonzero(mid_mask) + 1]
        if spectrum[0] > spectrum[1]:
            candidates.append(0)
        if spectrum[-1] > spectrum[-2]:
            candidates.append(n - 1)

        above = [idx for idx in candidates if float(spectrum[idx]) >= cutoff]
        above.sort(key=lambda idx: float(spectrum[idx]), reverse=True)

        selected: list[int] = []
        for idx in above:
            if all(abs(idx - kept) >= min_sep_bins for kept in selected):
                selected.append(idx)
                if len(selected) >= max_peaks:
                    break

        peaks: list[PeakInfo] = []
        for idx in selected:
            power_db = float(spectrum[idx])
            freq_mhz = float(freqs_mhz[idx])
            peaks.append(
                PeakInfo(
                    frequency_mhz=freq_mhz,
                    power_db=power_db,
                    snr_db=max(0.0, power_db - noise_floor_db),
                    bandwidth_hz=measure_bandwidth_hz(spectrum, idx, bin_width_hz),
                    offset_hz=(freq_mhz * 1e6) - center_freq_hz,
                )
            )
        return peaks
