"""Decoupled background RF acquisition, DSP, detection, and streaming engine."""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from rtl_sdr_analyzer.config.models import DetectorSettings, Settings, SourceMode, WindowType
from rtl_sdr_analyzer.detection.detector import SignalDetector
from rtl_sdr_analyzer.detection.events import SignalEvent, SpectrumFrame
from rtl_sdr_analyzer.dsp.processor import (
    SignalProcessor,
    compute_freq_axis_mhz,
    estimate_noise_floor,
)
from rtl_sdr_analyzer.engine.event_bus import EventBus
from rtl_sdr_analyzer.recording.recorder import IQRecorder
from rtl_sdr_analyzer.sources.base import (
    DeviceInfo,
    SDRConnectionError,
    SDRDisconnectedError,
    SDRLibraryNotFoundError,
    SDRSource,
    SDRSourceError,
)
from rtl_sdr_analyzer.sources.factory import create_source
from rtl_sdr_analyzer.sources.replay import FileReplaySource
from rtl_sdr_analyzer.storage.database import EventStore

logger = logging.getLogger(__name__)

EngineState = Literal["idle", "running", "paused", "sweeping", "disconnected", "error"]
FrameCallback = Callable[[SpectrumFrame], None]
StatusCallback = Callable[[dict[str, Any]], None]
_UNSET: Any = object()
# Sources that deliver samples in real time and must be read continuously
# (file replay is paced to its sample rate, so it plays at 1x speed).
_STREAMING = frozenset({"usb", "rtl_tcp", "file"})
_MAX_READ_SAMPLES = 1 << 20


def _classify_error_hint(exc: Exception) -> str:
    msg = str(exc)
    if isinstance(exc, SDRLibraryNotFoundError):
        return (
            "Install rtl-sdr / librtlsdr (or place rtlsdr.dll in PATH or Downloads) "
            "or switch source to RTL-TCP or Simulated RF."
        )
    if "No USB RTL-SDR" in msg or "Failed to open USB" in msg:
        return (
            "Check USB dongle connection and WinUSB driver (Zadig), close SDR++/rtl_tcp "
            "if open, or switch to Simulated RF."
        )
    if "RTL-TCP" in msg:
        return "Verify rtl_tcp is running at the configured host/port, or switch to USB or Simulated RF."
    return "Check RF source configuration or switch source mode in Settings."


class SpectrumEngine:
    """Owns the acquisition loop, live DSP/detector reconfiguration, and subscribers."""

    def __init__(
        self,
        settings: Settings,
        source: SDRSource | None = None,
        store: EventStore | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.settings = settings.model_copy(deep=True)
        self.event_bus = event_bus or EventBus()
        self.store = store

        rx = self.settings.receiver
        dsp = self.settings.dsp
        det = self.settings.detector

        self.processor = SignalProcessor(
            fft_size=rx.fft_size,
            sample_rate=rx.sample_rate,
            window=dsp.window,
            averaging=dsp.averaging,
            ema_alpha=dsp.ema_alpha,
            remove_dc=dsp.remove_dc,
        )
        self.detector = SignalDetector(
            enabled=det.enabled,
            power_threshold=det.power_threshold,
            snr_threshold=det.snr_threshold,
            bandwidth_threshold=det.bandwidth_threshold,
            z_score_threshold=det.z_score_threshold,
            detection_window=det.detection_window,
            min_duration=det.min_duration,
            holdover_seconds=det.holdover_seconds,
            cooldown_seconds=det.cooldown_seconds,
            test_mode=det.test_mode,
        )

        self._source: SDRSource | None = source
        self._owns_source = source is None
        self._state: EngineState = "idle"
        self._paused = False
        self._paused_for_exclusive = False
        self._stop_event = threading.Event()
        self._step_event = threading.Event()
        self._io_lock = threading.RLock()
        self._proc_lock = threading.RLock()
        self._rec_lock = threading.Lock()
        self._sub_lock = threading.Lock()

        self._frame_subscribers: list[FrameCallback] = []
        self._status_subscribers: list[StatusCallback] = []
        self._recorder: IQRecorder | None = None
        self._thread: threading.Thread | None = None

        self._seq: int = 0
        self._fps: float = 0.0
        self._last_error: str | None = None
        self._error_hint: str | None = None
        self._latest_frame: SpectrumFrame | None = None
        self._recent_events: deque[SignalEvent] = deque(maxlen=50)

        if self.store is not None:
            self.store.init_schema()
            self.event_bus.subscribe(self._store_event)

    def _store_event(self, event: SignalEvent) -> None:
        if self.store is not None:
            self.store.insert_event(event)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscribe_frames(self, callback: FrameCallback) -> None:
        with self._sub_lock:
            if callback not in self._frame_subscribers:
                self._frame_subscribers.append(callback)

    def unsubscribe_frames(self, callback: FrameCallback) -> None:
        with self._sub_lock:
            if callback in self._frame_subscribers:
                self._frame_subscribers.remove(callback)

    def subscribe_status(self, callback: StatusCallback) -> None:
        with self._sub_lock:
            if callback not in self._status_subscribers:
                self._status_subscribers.append(callback)

    def unsubscribe_status(self, callback: StatusCallback) -> None:
        with self._sub_lock:
            if callback in self._status_subscribers:
                self._status_subscribers.remove(callback)

    def _emit_frame(self, frame: SpectrumFrame) -> None:
        self._latest_frame = frame
        if frame.event is not None:
            self._recent_events.appendleft(frame.event)
        with self._sub_lock:
            callbacks = list(self._frame_subscribers)
        for cb in callbacks:
            try:
                cb(frame)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Frame subscriber error: %s", exc)

    def _emit_status(self) -> None:
        payload = self.get_status()
        with self._sub_lock:
            callbacks = list(self._status_subscribers)
        for cb in callbacks:
            try:
                cb(payload)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Status subscriber error: %s", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background acquisition thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._paused = False
        self._paused_for_exclusive = False
        if self.store is not None:
            self.store.start_session(
                center_freq_mhz=self.settings.receiver.frequency / 1e6,
                sample_rate_hz=self.settings.receiver.sample_rate,
            )
        self._thread = threading.Thread(
            target=self._run_loop,
            name="spectrum-engine",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop acquisition, recording, session tracking, and close the source."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        self.stop_recording()
        with self._io_lock:
            if self._source is not None:
                try:
                    self._source.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error closing source during stop: %s", exc)
        if self.store is not None:
            self.store.end_session()
        self._state = "idle"
        self._emit_status()

    def pause(self) -> None:
        self._paused = True
        if self._state == "running":
            self._state = "paused"
            self._emit_status()

    def resume(self) -> None:
        self._paused = False
        if self._state == "paused":
            self._state = "running"
            self._emit_status()

    # ------------------------------------------------------------------
    # Runtime reconfiguration
    # ------------------------------------------------------------------

    def update_receiver(
        self,
        *,
        frequency: float | None = None,
        sample_rate: float | None = None,
        fft_size: int | None = None,
        gain: float | None = _UNSET,
        ppm: int | None = None,
    ) -> None:
        """Apply receiver parameters live without restarting the engine."""
        rx = self.settings.receiver
        need_flush = False
        need_reset = False

        with self._io_lock:
            if frequency is not None and float(frequency) > 0:
                new_freq = float(frequency)
                if new_freq != rx.frequency:
                    if self._source is not None and self._source.is_open:
                        self._source.set_center_freq(new_freq)
                        need_flush = True
                    rx.frequency = new_freq
                    need_reset = True

            if sample_rate is not None and float(sample_rate) > 0:
                new_sr = float(sample_rate)
                if new_sr != rx.sample_rate:
                    if self._source is not None and self._source.is_open:
                        self._source.set_sample_rate(new_sr)
                        need_flush = True
                    rx.sample_rate = new_sr
                    need_reset = True

            if fft_size is not None:
                val = int(fft_size)
                if val & (val - 1) != 0 or val < 256 or val > 16384:
                    raise ValueError("fft_size must be a power of 2 between 256 and 16384")
                if val != rx.fft_size:
                    rx.fft_size = val
                    need_reset = True

            if gain is not _UNSET:
                new_gain = None if gain is None else float(gain)
                if new_gain != rx.gain:
                    if self._source is not None and self._source.is_open:
                        self._source.set_gain(new_gain)
                        need_flush = True
                    rx.gain = new_gain
                    need_reset = True

            if ppm is not None and int(ppm) != rx.ppm:
                new_ppm = int(ppm)
                if self._source is not None and self._source.is_open:
                    self._source.set_ppm(new_ppm)
                    need_flush = True
                rx.ppm = new_ppm
                need_reset = True

            if need_flush and self._source is not None and self._source.is_open:
                self._source.flush_buffer(discard_samples=8192)

        with self._proc_lock:
            self.processor.reconfigure(
                fft_size=rx.fft_size,
                sample_rate=rx.sample_rate,
            )
            if need_reset:
                self.processor.reset()
                self.detector.reset()

        self._emit_status()

    def update_dsp(
        self,
        *,
        window: WindowType | None = None,
        averaging: int | None = None,
        ema_alpha: float | None = None,
        remove_dc: bool | None = None,
    ) -> None:
        """Apply DSP settings live."""
        dsp = self.settings.dsp
        if window is not None:
            dsp.window = window
        if averaging is not None:
            dsp.averaging = max(1, min(64, int(averaging)))
        if ema_alpha is not None:
            dsp.ema_alpha = max(0.01, min(1.0, float(ema_alpha)))
        if remove_dc is not None:
            dsp.remove_dc = bool(remove_dc)

        with self._proc_lock:
            self.processor.reconfigure(
                window=dsp.window,
                averaging=dsp.averaging,
                ema_alpha=dsp.ema_alpha,
                remove_dc=dsp.remove_dc,
            )
        self._emit_status()

    def update_detector(self, updates: dict[str, Any]) -> None:
        """Validate and apply detector settings live."""
        merged = self.settings.detector.model_dump()
        merged.update({k: v for k, v in updates.items() if v is not None})
        validated = DetectorSettings(**merged)
        self.settings.detector = validated
        with self._proc_lock:
            self.detector.update_config(validated)
        self._emit_status()

    def switch_source(
        self,
        *,
        mode: SourceMode,
        device_index: int | None = None,
        library_path: str | None = None,
        replay_path: str | None = None,
        tcp_host: str | None = None,
        tcp_port: int | None = None,
        allow_simulated_fallback: bool = False,
    ) -> DeviceInfo:
        """Switch the active RF source at runtime."""
        self.settings.source.mode = mode
        if device_index is not None:
            self.settings.source.device_index = int(device_index)
        if library_path is not None:
            self.settings.source.library_path = library_path or None
        if replay_path is not None:
            self.settings.source.replay_path = replay_path or None
        if tcp_host is not None:
            self.settings.rtl_tcp.host = tcp_host
        if tcp_port is not None:
            self.settings.rtl_tcp.port = int(tcp_port)

        with self._io_lock:
            if self._source is not None:
                try:
                    self._source.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error closing previous source: %s", exc)
            self._source = create_source(
                self.settings, allow_simulated_fallback=allow_simulated_fallback
            )
            self._owns_source = True
            self._source.open()
            info = self._source.info
            self.settings.receiver.frequency = self._source.center_freq
            self.settings.receiver.sample_rate = self._source.sample_rate
            self._last_error = None
            self._error_hint = None
            self._state = "paused" if self._paused else "running"

        with self._proc_lock:
            self.processor.reconfigure(
                fft_size=self.settings.receiver.fft_size,
                sample_rate=self.settings.receiver.sample_rate,
            )
            self.processor.reset()
            self.detector.reset()

        self._emit_status()
        return info

    # ------------------------------------------------------------------
    # Recording tap
    # ------------------------------------------------------------------

    def start_recording(
        self, output_format: str = "raw", filename: str | None = None
    ) -> dict[str, Any]:
        """Start tapping live IQ samples to a file inside ``recordings_dir``."""
        with self._rec_lock:
            if self._recorder is not None:
                return self._recorder.summary()

            rec_dir = Path(self.settings.storage.recordings_dir)
            rec_dir.mkdir(parents=True, exist_ok=True)
            ext = "npz" if output_format.lower() == "numpy" else "raw"
            if filename:
                safe_name = Path(filename).name
                if not safe_name:
                    raise ValueError("Invalid recording filename")
                out_path = rec_dir / safe_name
            else:
                stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                freq_mhz = self.settings.receiver.frequency / 1e6
                out_path = rec_dir / f"iq_{freq_mhz:.3f}MHz_{stamp}.{ext}"

            rec = IQRecorder(
                output_path=out_path,
                format=output_format,
                sample_rate=self.settings.receiver.sample_rate,
                center_freq=self.settings.receiver.frequency,
                gain=self.settings.receiver.gain,
            )
            rec.open()
            self._recorder = rec
            summary = rec.summary()
        self._emit_status()
        return summary

    def stop_recording(self) -> dict[str, Any] | None:
        """Stop any active IQ recording and flush to disk."""
        with self._rec_lock:
            if self._recorder is None:
                return None
            rec = self._recorder
            self._recorder = None
            rec.close()
            summary = rec.summary()
        self._emit_status()
        return summary

    # ------------------------------------------------------------------
    # Exclusive hardware access (for Sweeper)
    # ------------------------------------------------------------------

    @contextmanager
    def pause_for_exclusive_use(self) -> Iterator[SDRSource]:
        """Pause the background loop temporarily and yield an open ``SDRSource``."""
        prev_state = self._state
        self._paused_for_exclusive = True
        self._state = "sweeping"
        self._emit_status()

        temp_opened = False
        with self._io_lock:
            try:
                if self._source is None:
                    self._source = create_source(self.settings, allow_simulated_fallback=True)
                if not self._source.is_open:
                    self._source.open()
                    temp_opened = True

                saved_freq = self.settings.receiver.frequency
                saved_sr = self.settings.receiver.sample_rate
                try:
                    yield self._source
                finally:
                    if self._source.is_open:
                        try:
                            if abs(self._source.sample_rate - saved_sr) > 1.0:
                                self._source.set_sample_rate(saved_sr)
                            self._source.set_center_freq(saved_freq)
                            self._source.flush_buffer(discard_samples=8192)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "Failed to restore receiver after exclusive use: %s", exc
                            )
                    if temp_opened and self._thread is None:
                        self._source.close()
            finally:
                with self._proc_lock:
                    self.processor.reconfigure(
                        fft_size=self.settings.receiver.fft_size,
                        sample_rate=self.settings.receiver.sample_rate,
                    )
                    self.processor.reset()
                    self.detector.reset()
                self._paused_for_exclusive = False
                if self._stop_event.is_set():
                    self._state = "idle"
                elif self._paused:
                    self._state = "paused"
                elif prev_state in ("running", "sweeping", "paused"):
                    self._state = "running"
                else:
                    self._state = prev_state
                self._emit_status()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return complete JSON-serializable state snapshot."""
        device_dict = (
            self._source.info.model_dump()
            if self._source is not None
            else DeviceInfo(
                index=self.settings.source.device_index,
                name="Not connected",
                source_type=self.settings.source.mode,
            ).model_dump()
        )
        rec_summary = self.recording_summary()
        return {
            "state": self._state,
            "source_mode": self.settings.source.mode,
            "source_type": self._source.source_type
            if self._source is not None
            else self.settings.source.mode,
            "device": device_dict,
            "rtl_tcp": self.settings.rtl_tcp.model_dump(),
            "receiver": self.settings.receiver.model_dump(),
            "dsp": self.settings.dsp.model_dump(),
            "detector": self.settings.detector.model_dump(),
            "display": self.settings.display.model_dump(),
            "stats": self.detector.stats.model_dump(),
            "recording": rec_summary,
            "replay_file": self._replay_filename(),
            "replay": self.replay_summary(),
            "fps": round(self._fps, 1),
            "frames_total": self._seq,
            "last_error": self._last_error,
            "error_hint": self._error_hint,
        }

    @property
    def is_running(self) -> bool:
        """Whether the acquisition thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def recording_summary(self) -> dict[str, Any] | None:
        """Cheap snapshot of the active recording (``None`` when not recording)."""
        with self._rec_lock:
            return self._recorder.summary() if self._recorder is not None else None

    def get_latest_frame(self) -> SpectrumFrame | None:
        return self._latest_frame

    def get_recent_memory_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in list(self._recent_events)[:limit]]

    # ------------------------------------------------------------------
    # Replay transport
    # ------------------------------------------------------------------

    def _replay_source(self) -> FileReplaySource:
        src = self._source
        if not isinstance(src, FileReplaySource) or not src.is_open:
            raise ValueError("Transport controls are only available while replaying a recording")
        return src

    def _frame_samples(self, sample_rate: float) -> int:
        fft_size = self.settings.receiver.fft_size
        fft_samples = max(fft_size, min(fft_size * self.settings.dsp.averaging, 32768))
        return max(fft_samples, min(int(sample_rate / self._target_fps()), _MAX_READ_SAMPLES))

    def replay_summary(self) -> dict[str, Any] | None:
        """Position/length/speed of the active replay, or ``None`` when not replaying."""
        src = self._source
        if not isinstance(src, FileReplaySource) or not src.is_open or src.total_samples == 0:
            return None
        sr = max(src.sample_rate, 1.0)
        frame = self._frame_samples(sr)
        frame_count = max(1, -(-src.total_samples // frame))  # ceil
        # The cursor sits at the end of the frame on screen, so that frame is (cursor - 1) // F.
        current = ((src.position_samples - 1) // frame) % frame_count
        return {
            "filename": src.file_path.name,
            "position_s": round(src.position_samples / sr, 3),
            "duration_s": round(src.total_samples / sr, 3),
            "speed": src.speed,
            "frame_s": round(frame / sr, 4),
            "frame": int(current),
            "frame_count": int(frame_count),
        }

    def replay_seek(self, position_s: float) -> None:
        """Jump to ``position_s`` seconds; if paused, render the frame at that position."""
        with self._io_lock:
            src = self._replay_source()
            src.seek(int(max(0.0, position_s) * src.sample_rate))
        with self._proc_lock:
            self.processor.reset()
        if self._paused:
            self._step_event.set()
        self._emit_status()

    def replay_seek_frame(self, frame_index: int) -> None:
        """Pause and show frame ``frame_index`` (0-based, wraps around the file)."""
        with self._io_lock:
            src = self._replay_source()
            frame = self._frame_samples(src.sample_rate)
            frame_count = max(1, -(-src.total_samples // frame))
            src.seek((int(frame_index) % frame_count) * frame)
        self._paused = True
        if self._state == "running":
            self._state = "paused"
        with self._proc_lock:
            self.processor.reset()
        self._step_event.set()
        self._emit_status()

    def replay_set_speed(self, speed: float) -> None:
        with self._io_lock:
            try:
                self._replay_source().set_speed(speed)
            except SDRSourceError as exc:
                raise ValueError(str(exc)) from exc
        self._emit_status()

    def step_frame(self, direction: int = 1) -> None:
        """Pause and render exactly one frame forward (``1``) or backward (``-1``)."""
        with self._io_lock:
            src = self._replay_source()
            if direction < 0:
                # The current frame ends at the cursor: go back two frames, render one.
                frame = self._frame_samples(src.sample_rate)
                src.seek(src.position_samples - 2 * frame)
        self._paused = True
        if self._state == "running":
            self._state = "paused"
        with self._proc_lock:
            self.processor.reset()  # show the exact frame, not an average with the last one
        self._step_event.set()
        self._emit_status()

    def _replay_filename(self) -> str | None:
        replay_path = getattr(self._source, "file_path", None)
        return Path(replay_path).name if replay_path is not None else None

    def protected_paths(self) -> set[Path]:
        """Files in use (active recording or replay) that must not be deleted."""
        paths: set[Path] = set()
        rec = self.recording_summary()
        if rec is not None:
            paths.add(Path(rec["path"]).resolve())
        replay_path = getattr(self._source, "file_path", None)
        if self._source is not None and self._source.is_open and replay_path is not None:
            paths.add(Path(replay_path).resolve())
        return paths

    def clear_recent_events(self) -> None:
        self._recent_events.clear()

    # ------------------------------------------------------------------
    # Acquisition worker loop
    # ------------------------------------------------------------------

    def _ensure_source_open(self) -> bool:
        with self._io_lock:
            if self._source is None:
                self._source = create_source(self.settings, allow_simulated_fallback=True)
            if self._source.is_open:
                return True
            try:
                self._source.open()
                self._last_error = None
                self._error_hint = None
                self._state = "paused" if self._paused else "running"
                self._emit_status()
                return True
            except (SDRSourceError, OSError) as exc:
                self._last_error = str(exc)
                self._error_hint = _classify_error_hint(exc)
                self._state = "error"
                logger.warning("Source open failed: %s", exc)
                self._emit_status()
                return False
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error opening source: %s", exc)
                self._last_error = str(exc)
                self._error_hint = _classify_error_hint(exc)
                self._state = "error"
                self._emit_status()
                return False

    def _target_fps(self) -> int:
        return max(1, self.settings.display.target_fps)

    def _run_loop(self) -> None:
        fps_t0 = time.monotonic()
        fps_frames = 0

        while not self._stop_event.is_set():
            stepping = self._paused and self._step_event.is_set()
            if self._paused_for_exclusive or (self._paused and not stepping):
                self._stop_event.wait(0.05)
                continue
            self._step_event.clear()

            if not self._ensure_source_open():
                self._stop_event.wait(1.0)
                continue

            iter_start = time.monotonic()
            try:
                with self._io_lock:
                    if (self._paused and not stepping) or self._paused_for_exclusive:
                        continue
                    if self._source is None:
                        continue
                    fft_size = self.settings.receiver.fft_size
                    avg = self.settings.dsp.averaging
                    fft_samples = max(fft_size, min(fft_size * avg, 32768))
                    # Real-time streams (and active recordings) must be drained completely:
                    # otherwise rtl_tcp lags behind real time and IQ recordings have gaps.
                    to_read = fft_samples
                    if self._recorder is not None or self._source.source_type in _STREAMING:
                        to_read = self._frame_samples(self._source.sample_rate)
                        # Replay speed scales the IQ consumed per frame (fps stays constant);
                        # single-frame steps always advance exactly one 1x frame.
                        if isinstance(self._source, FileReplaySource) and not stepping:
                            to_read = max(fft_samples, int(to_read * self._source.speed))
                    iq = self._source.read_samples(to_read)
                    center_freq = self._source.center_freq
                    sample_rate = self._source.sample_rate

                with self._rec_lock:
                    if self._recorder is not None:
                        self._recorder.write_samples(iq)

                with self._proc_lock:
                    spectrum = self.processor.process_samples(iq[-fft_samples:])
                    if spectrum is None:
                        continue
                    freqs_mhz = compute_freq_axis_mhz(center_freq, sample_rate, fft_size)
                    noise_db, noise_std = estimate_noise_floor(spectrum)
                    peaks = self.processor.find_peaks(
                        spectrum,
                        freqs_mhz,
                        center_freq,
                        noise_floor_db=noise_db,
                        min_snr_db=max(6.0, self.settings.detector.snr_threshold * 0.7),
                        max_peaks=8,
                    )
                    now_wall = time.time()
                    event = self.detector.detect_signal(
                        spectrum,
                        freqs_mhz,
                        now_wall,
                        center_freq_hz=center_freq,
                    )

                if event is not None:
                    self.event_bus.publish(event)

                self._seq += 1
                fps_frames += 1
                now_mono = time.monotonic()
                dt_fps = now_mono - fps_t0
                if dt_fps >= 1.0:
                    self._fps = fps_frames / dt_fps
                    fps_frames = 0
                    fps_t0 = now_mono

                peak_idx = int(spectrum.argmax())
                peak_power_db = float(spectrum[peak_idx])
                peak_freq_mhz = float(freqs_mhz[peak_idx])
                step_mhz = (sample_rate / fft_size) / 1e6

                frame = SpectrumFrame(
                    seq=self._seq,
                    timestamp=now_wall,
                    center_freq_hz=center_freq,
                    sample_rate_hz=sample_rate,
                    fft_size=fft_size,
                    freqs_start_mhz=float(freqs_mhz[0]),
                    freqs_step_mhz=step_mhz,
                    power_db=spectrum,
                    noise_floor_db=noise_db,
                    noise_std_db=noise_std,
                    peak_freq_mhz=peak_freq_mhz,
                    peak_power_db=peak_power_db,
                    peak_snr_db=max(0.0, peak_power_db - noise_db),
                    peaks=peaks,
                    event=event,
                    fps=self._fps,
                )
                self._emit_frame(frame)

                target_dt = 1.0 / self._target_fps()
                elapsed = time.monotonic() - iter_start
                if elapsed < target_dt and not stepping:
                    self._stop_event.wait(target_dt - elapsed)

            except (SDRDisconnectedError, SDRConnectionError) as exc:
                logger.warning("RF stream interrupted: %s", exc)
                self._last_error = str(exc)
                self._error_hint = _classify_error_hint(exc)
                self._state = "disconnected"
                with self._io_lock:
                    if self._source is not None:
                        self._source.close()
                self._emit_status()
                self._stop_event.wait(0.75)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error in SpectrumEngine loop: %s", exc)
                self._last_error = str(exc)
                self._error_hint = _classify_error_hint(exc)
                self._state = "error"
                self._emit_status()
                self._stop_event.wait(0.5)
