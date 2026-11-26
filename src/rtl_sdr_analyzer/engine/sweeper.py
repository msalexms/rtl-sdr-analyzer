"""Wideband frequency sweeper shared by CLI and Web Studio."""

import logging
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
from pydantic import BaseModel, Field

from rtl_sdr_analyzer.detection.events import SignalEvent
from rtl_sdr_analyzer.dsp.processor import (
    PeakInfo,
    SignalProcessor,
    compute_freq_axis_mhz,
    estimate_noise_floor,
)
from rtl_sdr_analyzer.engine.event_bus import EventBus
from rtl_sdr_analyzer.sources.base import SDRConfigurationError, SDRSource
from rtl_sdr_analyzer.storage.database import EventStore

logger = logging.getLogger(__name__)


class SweepConfig(BaseModel):
    """Configuration for a wideband spectrum sweep."""

    start_freq_hz: float = Field(gt=0.0)
    end_freq_hz: float = Field(gt=0.0)
    step_hz: float | None = Field(default=None, gt=0.0)
    dwell_seconds: float = Field(default=0.35, gt=0.0, le=30.0)
    min_frames: int = Field(default=2, ge=1, le=50)
    fft_size: int = Field(default=1024, ge=256, le=8192)
    sample_rate_hz: float = Field(default=2.048e6, ge=225_001.0, le=3_200_000.0)
    power_threshold_db: float = Field(default=-65.0, ge=-140.0, le=10.0)
    snr_threshold_db: float = Field(default=8.0, ge=0.0, le=100.0)


class SweepProgress(BaseModel):
    """Live progress snapshot during an active sweep."""

    running: bool
    step_index: int
    total_steps: int
    current_freq_mhz: float
    percent: float
    peaks_found: int


class SweepResult(BaseModel):
    """Composite stitched spectrum and detected peaks from a completed sweep."""

    start_freq_mhz: float
    end_freq_mhz: float
    step_hz: float
    bin_width_hz: float
    freqs_mhz: list[float]
    power_db: list[float]
    noise_floor_db: float
    peaks: list[PeakInfo]
    events_count: int
    duration_s: float
    cancelled: bool = False


class FrequencySweeper:
    """Scans a wide RF range and stitches overlap-trimmed PSD steps."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        store: EventStore | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.store = store
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation of the currently running sweep."""
        self._cancel_event.set()

    def run(
        self,
        source: SDRSource,
        config: SweepConfig,
        on_progress: Callable[[SweepProgress], None] | None = None,
    ) -> SweepResult:
        """Execute a wideband sweep synchronously using an open ``SDRSource``."""
        if config.end_freq_hz <= config.start_freq_hz:
            raise ValueError("end_freq_hz must be greater than start_freq_hz")

        self._cancel_event.clear()
        t_start = time.monotonic()

        sample_rate = float(config.sample_rate_hz)
        step_hz = float(config.step_hz) if config.step_hz else sample_rate * 0.8
        # Ensure step stays within usable RF passband
        step_hz = min(step_hz, sample_rate * 0.95)

        if abs(source.sample_rate - sample_rate) > 1.0:
            source.set_sample_rate(sample_rate)

        processor = SignalProcessor(
            fft_size=config.fft_size,
            sample_rate=sample_rate,
            window="blackmanharris",
            averaging=2,
            ema_alpha=1.0,  # linear frame averaging managed per step
        )

        span_hz = config.end_freq_hz - config.start_freq_hz
        centers_hz: list[float] = []
        if span_hz <= step_hz:
            centers_hz.append(0.5 * (config.start_freq_hz + config.end_freq_hz))
        else:
            c = config.start_freq_hz + 0.5 * step_hz
            while (c - 0.5 * step_hz) < config.end_freq_hz - 1.0:
                centers_hz.append(c)
                c += step_hz

        start_mhz = config.start_freq_hz / 1e6
        end_mhz = config.end_freq_hz / 1e6
        total_steps = len(centers_hz)

        stitched_freqs: list[np.ndarray] = []
        stitched_power: list[np.ndarray] = []
        all_peaks: list[PeakInfo] = []
        events_count = 0
        cancelled = False
        last_config_err: SDRConfigurationError | None = None

        for idx, center_hz in enumerate(centers_hz):
            if self._cancel_event.is_set():
                cancelled = True
                break

            try:
                source.set_center_freq(center_hz)
                source.flush_buffer(discard_samples=8192)
            except SDRConfigurationError as exc:
                logger.warning(
                    "Skipping sweep step %.3f MHz after tune error: %s",
                    center_hz / 1e6,
                    exc,
                )
                last_config_err = exc
                continue
            processor.reset()

            if on_progress is not None:
                on_progress(
                    SweepProgress(
                        running=True,
                        step_index=idx + 1,
                        total_steps=total_steps,
                        current_freq_mhz=center_hz / 1e6,
                        percent=round(100.0 * idx / max(1, total_steps), 1),
                        peaks_found=len(all_peaks),
                    )
                )

            step_spectra_lin: list[np.ndarray] = []
            dwell_deadline = time.monotonic() + config.dwell_seconds
            frames_taken = 0
            while frames_taken < config.min_frames or time.monotonic() < dwell_deadline:
                if self._cancel_event.is_set():
                    cancelled = True
                    break
                iq = source.read_samples(config.fft_size * 2)
                spec_db = processor.process_samples(iq)
                if spec_db is not None:
                    step_spectra_lin.append(10.0 ** (spec_db / 10.0))
                    frames_taken += 1

            if cancelled:
                break
            if not step_spectra_lin:
                continue

            avg_lin = np.mean(step_spectra_lin, axis=0)
            avg_db = 10.0 * np.log10(avg_lin + 1e-15)
            freqs_mhz = compute_freq_axis_mhz(center_hz, sample_rate, config.fft_size)

            low_mhz = max(start_mhz, (center_hz - 0.5 * step_hz) / 1e6)
            high_mhz = min(end_mhz, (center_hz + 0.5 * step_hz) / 1e6)
            if idx == total_steps - 1:
                mask = (freqs_mhz >= low_mhz) & (freqs_mhz <= end_mhz + 1e-9)
            else:
                mask = (freqs_mhz >= low_mhz) & (freqs_mhz < high_mhz)

            if np.any(mask):
                stitched_freqs.append(freqs_mhz[mask])
                stitched_power.append(avg_db[mask])

            # Extract peaks within the retained slice
            noise_db, _ = estimate_noise_floor(avg_db)
            step_peaks = processor.find_peaks(
                avg_db,
                freqs_mhz,
                center_hz,
                noise_floor_db=noise_db,
                min_snr_db=config.snr_threshold_db,
                max_peaks=5,
                min_sep_bins=6,
            )
            for pk in step_peaks:
                if pk.power_db < config.power_threshold_db:
                    continue
                if pk.frequency_mhz < low_mhz or pk.frequency_mhz > high_mhz:
                    continue
                all_peaks.append(pk)
                event = SignalEvent(
                    timestamp=datetime.now(UTC),
                    frequency=pk.frequency_mhz,
                    power=pk.power_db,
                    bandwidth=pk.bandwidth_hz,
                    duration=config.dwell_seconds,
                    confidence=round(pk.snr_db / max(config.snr_threshold_db, 1.0), 2),
                    snr=pk.snr_db,
                    center_offset=pk.offset_hz,
                    noise_floor=noise_db,
                )
                events_count += 1
                if self.event_bus is not None:
                    self.event_bus.publish(event)
                if self.store is not None:
                    self.store.insert_event(event)

        if stitched_freqs:
            freqs_cat = np.concatenate(stitched_freqs)
            power_cat = np.concatenate(stitched_power)
            order = np.argsort(freqs_cat)
            freqs_cat = freqs_cat[order]
            power_cat = power_cat[order]
            overall_noise, _ = estimate_noise_floor(power_cat)
        elif not cancelled and last_config_err is not None:
            raise last_config_err
        else:
            freqs_cat = np.empty(0, dtype=np.float64)
            power_cat = np.empty(0, dtype=np.float64)
            overall_noise = -120.0

        all_peaks.sort(key=lambda p: p.power_db, reverse=True)
        # Deduplicate nearby peaks across step seams (within 25 kHz)
        deduped_peaks: list[PeakInfo] = []
        for pk in all_peaks:
            if all(abs(pk.frequency_mhz - kept.frequency_mhz) > 0.025 for kept in deduped_peaks):
                deduped_peaks.append(pk)

        if on_progress is not None:
            on_progress(
                SweepProgress(
                    running=False,
                    step_index=total_steps,
                    total_steps=total_steps,
                    current_freq_mhz=end_mhz,
                    percent=100.0
                    if not cancelled
                    else round(100.0 * len(stitched_freqs) / max(1, total_steps), 1),
                    peaks_found=len(deduped_peaks),
                )
            )

        bin_width_hz = sample_rate / config.fft_size
        duration_s = round(time.monotonic() - t_start, 3)

        # Downsample display arrays if huge (>4096 points) while preserving peaks cleanly
        max_pts = 4096
        if len(freqs_cat) > max_pts:
            stride = math.ceil(len(freqs_cat) / max_pts)
            n_full = (len(freqs_cat) // stride) * stride
            f_view = freqs_cat[:n_full].reshape(-1, stride).mean(axis=1)
            p_view = power_cat[:n_full].reshape(-1, stride).max(axis=1)
            freqs_list = [round(float(x), 5) for x in f_view]
            power_list = [round(float(y), 2) for y in p_view]
        else:
            freqs_list = [round(float(x), 5) for x in freqs_cat]
            power_list = [round(float(y), 2) for y in power_cat]

        logger.info(
            "Sweep %.3f-%.3f MHz finished in %.2fs (%d peaks, cancelled=%s)",
            start_mhz,
            end_mhz,
            duration_s,
            len(deduped_peaks),
            cancelled,
        )
        return SweepResult(
            start_freq_mhz=start_mhz,
            end_freq_mhz=end_mhz,
            step_hz=step_hz,
            bin_width_hz=bin_width_hz,
            freqs_mhz=freqs_list,
            power_db=power_list,
            noise_floor_db=round(overall_noise, 2),
            peaks=deduped_peaks[:50],
            events_count=events_count,
            duration_s=duration_s,
            cancelled=cancelled,
        )
