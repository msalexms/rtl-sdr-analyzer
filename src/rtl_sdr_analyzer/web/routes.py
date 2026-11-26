"""REST API routes for RTL-SDR Analyzer Web Studio."""

import csv
import io
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from rtl_sdr_analyzer import __version__
from rtl_sdr_analyzer.config.models import Settings, SourceMode, WindowType
from rtl_sdr_analyzer.engine.spectrum_engine import SpectrumEngine
from rtl_sdr_analyzer.engine.sweeper import (
    FrequencySweeper,
    SweepConfig,
    SweepProgress,
    SweepResult,
)
from rtl_sdr_analyzer.sources.base import SDRSourceError
from rtl_sdr_analyzer.sources.usb import get_usb_diagnostics
from rtl_sdr_analyzer.storage.database import EventStore
from rtl_sdr_analyzer.web.ws import SpectrumBroadcaster

logger = logging.getLogger(__name__)


class ReceiverPatchRequest(BaseModel):
    frequency: float | None = Field(default=None, gt=0.0)
    sample_rate: float | None = Field(default=None, ge=225_001.0, le=3_200_000.0)
    fft_size: int | None = Field(default=None, ge=256, le=16384)
    gain: float | None = Field(default=None, ge=0.0, le=60.0)
    ppm: int | None = Field(default=None, ge=-500, le=500)


class DspPatchRequest(BaseModel):
    window: WindowType | None = None
    averaging: int | None = Field(default=None, ge=1, le=64)
    ema_alpha: float | None = Field(default=None, gt=0.0, le=1.0)
    remove_dc: bool | None = None


class DetectorPatchRequest(BaseModel):
    enabled: bool | None = None
    power_threshold: float | None = Field(default=None, ge=-140.0, le=10.0)
    snr_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    bandwidth_threshold: float | None = Field(default=None, ge=0.0)
    z_score_threshold: float | None = Field(default=None, gt=0.0)
    detection_window: int | None = Field(default=None, ge=1)
    min_duration: float | None = Field(default=None, ge=0.0)
    holdover_seconds: float | None = Field(default=None, ge=0.0)
    cooldown_seconds: float | None = Field(default=None, ge=0.0)
    test_mode: bool | None = None


class SourceSwitchRequest(BaseModel):
    mode: SourceMode
    device_index: int | None = Field(default=None, ge=0)
    library_path: str | None = None
    replay_path: str | None = None
    tcp_host: str | None = None
    tcp_port: int | None = Field(default=None, ge=1, le=65535)


class RecordingStartRequest(BaseModel):
    format: str = Field(default="raw")
    filename: str | None = None


class SweepStartRequest(BaseModel):
    start_freq_hz: float = Field(gt=0.0)
    end_freq_hz: float = Field(gt=0.0)
    step_hz: float | None = Field(default=None, gt=0.0)
    dwell_seconds: float = Field(default=0.35, gt=0.0, le=30.0)
    fft_size: int = Field(default=1024, ge=256, le=8192)
    snr_threshold_db: float = Field(default=8.0, ge=0.0, le=100.0)
    power_threshold_db: float = Field(default=-65.0, ge=-140.0, le=10.0)


class SweepCoordinator:
    """Manages at most one active wideband sweep job."""

    def __init__(
        self,
        engine: SpectrumEngine,
        store: EventStore | None,
        broadcaster: SpectrumBroadcaster,
    ) -> None:
        self.engine = engine
        self.store = store
        self.broadcaster = broadcaster
        self._lock = threading.Lock()
        self._sweeper: FrequencySweeper | None = None
        self._thread: threading.Thread | None = None
        self._progress: SweepProgress | None = None
        self._result: SweepResult | None = None
        self._error: str | None = None

    def start_sweep(self, req: SweepStartRequest) -> SweepProgress:
        if req.end_freq_hz <= req.start_freq_hz:
            raise HTTPException(status_code=400, detail="end_freq_hz must exceed start_freq_hz")

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise HTTPException(status_code=409, detail="A frequency sweep is already running")

            sweeper = FrequencySweeper(event_bus=self.engine.event_bus, store=None)
            self._sweeper = sweeper
            self._error = None
            self._result = None
            self._progress = SweepProgress(
                running=True,
                step_index=0,
                total_steps=1,
                current_freq_mhz=req.start_freq_hz / 1e6,
                percent=0.0,
                peaks_found=0,
            )

            cfg = SweepConfig(
                start_freq_hz=req.start_freq_hz,
                end_freq_hz=req.end_freq_hz,
                step_hz=req.step_hz,
                dwell_seconds=req.dwell_seconds,
                fft_size=req.fft_size,
                sample_rate_hz=self.engine.settings.receiver.sample_rate,
                snr_threshold_db=req.snr_threshold_db,
                power_threshold_db=req.power_threshold_db,
            )

            def _worker() -> None:
                try:
                    with self.engine.pause_for_exclusive_use() as src:

                        def _on_prog(p: SweepProgress) -> None:
                            self._progress = p
                            self.broadcaster.broadcast(
                                {"type": "sweep_progress", "progress": p.model_dump()}
                            )

                        res = sweeper.run(src, cfg, on_progress=_on_prog)
                        self._result = res
                        self.broadcaster.broadcast(
                            {"type": "sweep_result", "result": res.model_dump()}
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Sweep failed: %s", exc)
                    self._error = str(exc)
                    self.broadcaster.broadcast({"type": "sweep_error", "error": str(exc)})
                finally:
                    if self._progress is not None:
                        self._progress = self._progress.model_copy(update={"running": False})

            self._thread = threading.Thread(target=_worker, name="rf-sweeper", daemon=True)
            self._thread.start()
            return self._progress

    def cancel(self) -> bool:
        with self._lock:
            if self._sweeper is not None and self._thread is not None and self._thread.is_alive():
                self._sweeper.cancel()
                return True
            return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {
                "running": running,
                "progress": self._progress.model_dump() if self._progress else None,
                "result": self._result.model_dump() if self._result else None,
                "error": self._error,
            }


def _list_recordings(rec_dir: Path) -> list[dict[str, Any]]:
    if not rec_dir.is_dir():
        return []
    files = [
        (p, p.stat())
        for p in rec_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".raw", ".cu8", ".npz")
    ]
    files.sort(key=lambda item: item[1].st_mtime, reverse=True)
    return [
        {
            "filename": p.name,
            "size_bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
            "format": "numpy" if p.suffix.lower() == ".npz" else "raw",
        }
        for p, st in files
    ]


def _memory_event_rows(engine: SpectrumEngine, limit: int) -> list[dict[str, Any]]:
    """In-memory events shaped like :meth:`EventStore.get_recent_events` rows."""
    return [
        {
            "id": idx + 1,
            "timestamp": e["timestamp"],
            "frequency_mhz": e["frequency"],
            "power_db": e["power"],
            "bandwidth_hz": e["bandwidth"],
            "duration_s": e["duration"],
            "confidence": e["confidence"],
            "snr": e["snr"],
            "center_offset_hz": e.get("center_offset"),
            "noise_floor_db": e.get("noise_floor"),
        }
        for idx, e in enumerate(engine.get_recent_memory_events(limit=limit))
    ]


def create_api_router(
    engine: SpectrumEngine,
    store: EventStore | None,
    settings: Settings,
    broadcaster: SpectrumBroadcaster,
    sweeper: SweepCoordinator,
) -> APIRouter:
    """Build the FastAPI router exposing receiver, sweep, recording, and event endpoints."""
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, Any]:
        status = engine.get_status()
        return {
            "status": "ok",
            "version": __version__,
            "engine_state": status["state"],
            "source_type": status["source_type"],
        }

    @router.get("/devices")
    def devices() -> dict[str, Any]:
        diag = get_usb_diagnostics(engine.settings.source.library_path)
        status = engine.get_status()
        active_dev = status.get("device") or {}
        if status.get("source_type") == "usb" and active_dev.get("connected"):
            active_idx = active_dev.get("index", 0)
            for item in diag.get("devices", []):
                if item.get("index") == active_idx:
                    item["connected"] = True
                    item["tuner"] = active_dev.get("tuner", item.get("tuner", "UNKNOWN"))
                    item["supported_gains"] = active_dev.get("supported_gains", [])
        return diag

    @router.get("/state")
    def get_state() -> dict[str, Any]:
        state = engine.get_status()
        state["recordings"] = _list_recordings(Path(engine.settings.storage.recordings_dir))
        state["version"] = __version__
        return state

    @router.patch("/receiver")
    def patch_receiver(req: ReceiverPatchRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        fields = req.model_fields_set
        if "frequency" in fields and req.frequency is not None:
            kwargs["frequency"] = req.frequency
        if "sample_rate" in fields and req.sample_rate is not None:
            kwargs["sample_rate"] = req.sample_rate
        if "fft_size" in fields and req.fft_size is not None:
            kwargs["fft_size"] = req.fft_size
        if "gain" in fields:
            kwargs["gain"] = req.gain
        if "ppm" in fields and req.ppm is not None:
            kwargs["ppm"] = req.ppm

        try:
            engine.update_receiver(**kwargs)
        except (ValueError, SDRSourceError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return engine.get_status()

    @router.patch("/dsp")
    def patch_dsp(req: DspPatchRequest) -> dict[str, Any]:
        engine.update_dsp(
            window=req.window,
            averaging=req.averaging,
            ema_alpha=req.ema_alpha,
            remove_dc=req.remove_dc,
        )
        return engine.get_status()

    @router.patch("/detector")
    def patch_detector(req: DetectorPatchRequest) -> dict[str, Any]:
        updates = req.model_dump(exclude_none=True)
        try:
            engine.update_detector(updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return engine.get_status()

    @router.post("/source")
    def post_source(req: SourceSwitchRequest) -> dict[str, Any]:
        try:
            engine.switch_source(
                mode=req.mode,
                device_index=req.device_index,
                library_path=req.library_path,
                replay_path=req.replay_path,
                tcp_host=req.tcp_host,
                tcp_port=req.tcp_port,
                allow_simulated_fallback=False,
            )
        except SDRSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return engine.get_status()

    @router.post("/stream/pause")
    def pause_stream() -> dict[str, Any]:
        engine.pause()
        return {"state": engine.get_status()["state"]}

    @router.post("/stream/resume")
    def resume_stream() -> dict[str, Any]:
        engine.resume()
        return {"state": engine.get_status()["state"]}

    @router.post("/recording/start")
    def recording_start(req: RecordingStartRequest) -> dict[str, Any]:
        try:
            summary = engine.start_recording(output_format=req.format, filename=req.filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return summary

    @router.post("/recording/stop")
    def recording_stop() -> dict[str, Any]:
        summary = engine.stop_recording()
        return {"recording": summary}

    @router.get("/recordings")
    def list_recordings() -> dict[str, Any]:
        rec_dir = Path(engine.settings.storage.recordings_dir)
        return {"recordings": _list_recordings(rec_dir)}

    @router.get("/recordings/{filename}")
    def download_recording(filename: str) -> FileResponse:
        if (
            Path(filename).name != filename
            or ".." in filename
            or "/" in filename
            or "\\" in filename
        ):
            raise HTTPException(status_code=400, detail="Invalid filename")
        rec_dir = Path(engine.settings.storage.recordings_dir).resolve()
        target = (rec_dir / filename).resolve()
        if not target.is_relative_to(rec_dir) or not target.is_file():
            raise HTTPException(status_code=404, detail="Recording not found")
        return FileResponse(path=target, filename=filename, media_type="application/octet-stream")

    @router.post("/sweep")
    def start_sweep(req: SweepStartRequest) -> dict[str, Any]:
        prog = sweeper.start_sweep(req)
        return {"running": True, "progress": prog.model_dump()}

    @router.get("/sweep")
    def get_sweep() -> dict[str, Any]:
        return sweeper.status()

    @router.post("/sweep/cancel")
    def cancel_sweep() -> dict[str, Any]:
        return {"cancelled": sweeper.cancel()}

    @router.get("/events")
    def list_events(
        limit: int = Query(default=100, ge=1, le=500),
        since_hours: int | None = Query(default=None, ge=1, le=720),
    ) -> dict[str, Any]:
        if store is not None:
            events = store.get_recent_events(limit=limit, since_hours=since_hours)
        else:
            events = _memory_event_rows(engine, limit)
        return {"events": events}

    @router.get("/stats")
    def get_stats() -> dict[str, Any]:
        if store is not None:
            return {
                "total_events": store.get_event_count(),
                "top_frequencies": store.get_top_frequencies(limit=10),
                "hourly_activity": store.get_hourly_activity(hours=24),
                "sessions": store.get_sessions(limit=5),
                "live": engine.detector.stats.model_dump(),
            }
        mem_events = engine.get_recent_memory_events(limit=200)
        grouped: dict[float, list[float]] = {}
        for ev in mem_events:
            f = round(float(ev["frequency"]), 3)
            grouped.setdefault(f, []).append(float(ev["power"]))
        top_freqs = [
            {
                "frequency_mhz": f,
                "count": len(powers),
                "avg_power": sum(powers) / len(powers),
                "max_power": max(powers),
            }
            for f, powers in sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
        ]
        return {
            "total_events": len(mem_events),
            "top_frequencies": top_freqs,
            "hourly_activity": [],
            "sessions": [],
            "live": engine.detector.stats.model_dump(),
        }

    @router.get("/events/export")
    def export_events(format: str = Query(default="csv")) -> Response:
        fmt = format.lower()
        if fmt not in ("csv", "json"):
            raise HTTPException(status_code=400, detail="format must be 'csv' or 'json'")

        events = (
            store.get_recent_events(limit=5000)
            if store is not None
            else _memory_event_rows(engine, 500)
        )

        if fmt == "json":
            payload = "\n".join(json.dumps(row) for row in events)
            return Response(
                content=payload,
                media_type="application/x-ndjson",
                headers={"Content-Disposition": 'attachment; filename="rtl-sdr-events.jsonl"'},
            )

        buf = io.StringIO()
        fields = (
            list(events[0].keys())
            if events
            else [
                "timestamp",
                "frequency_mhz",
                "power_db",
                "bandwidth_hz",
                "duration_s",
                "confidence",
                "snr",
            ]
        )
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        writer.writerows(events)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="rtl-sdr-events.csv"'},
        )

    @router.delete("/events")
    def delete_events() -> dict[str, Any]:
        deleted = store.clear_events() if store is not None else 0
        engine.clear_recent_events()
        return {"deleted": deleted}

    return router
