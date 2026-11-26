"""WebSocket spectrum streaming hub with bounded per-client queues."""

import asyncio
import base64
import contextlib
import logging
import threading
from typing import Any

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from rtl_sdr_analyzer.detection.events import SpectrumFrame

logger = logging.getLogger(__name__)


def encode_frame_payload(
    frame: SpectrumFrame,
    recording: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a :class:`SpectrumFrame` cleanly with compact Base64 Int16 bins."""
    scaled = np.clip(np.rint(frame.power_db * 10.0), -1600, 200).astype("<i2")
    bins_b64 = base64.b64encode(scaled.tobytes()).decode("ascii")
    return {
        "type": "frame",
        "seq": frame.seq,
        "ts": round(frame.timestamp, 3),
        "center_freq_hz": frame.center_freq_hz,
        "sample_rate_hz": frame.sample_rate_hz,
        "fft_size": frame.fft_size,
        "freqs_start_mhz": round(frame.freqs_start_mhz, 6),
        "freqs_step_mhz": frame.freqs_step_mhz,
        "bins_b64": bins_b64,
        "noise_floor_db": round(frame.noise_floor_db, 2),
        "noise_std_db": round(frame.noise_std_db, 2),
        "peak_freq_mhz": round(frame.peak_freq_mhz, 5),
        "peak_power_db": round(frame.peak_power_db, 2),
        "peak_snr_db": round(frame.peak_snr_db, 2),
        "peaks": [p.model_dump() for p in frame.peaks],
        "fps": round(frame.fps, 1),
        "recording": recording,
        "event": frame.event.model_dump(mode="json") if frame.event is not None else None,
    }


class SpectrumBroadcaster:
    """Thread-safe hub pushing frames and status updates to connected WebSockets."""

    def __init__(self, recording_provider: Any = None) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._recording_provider = recording_provider

    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        with self._lock:
            self._loop = loop

    def _enqueue_latest(
        self, queue: asyncio.Queue[dict[str, Any]], payload: dict[str, Any]
    ) -> None:
        if not queue.full():
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)
            return

        # Evict oldest frame first so control events (status, sweep_result, sweep_error) survive
        items: list[dict[str, Any]] = []
        while True:
            try:
                items.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        drop_idx = next(
            (i for i, item in enumerate(items) if item.get("type") == "frame"),
            None,
        )
        if drop_idx is not None:
            items.pop(drop_idx)
        elif payload.get("type") != "frame" and items:
            items.pop(0)
        else:
            # Queue is full of control messages and incoming message is a frame: drop the frame
            for item in items:
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(item)
            return

        for item in items:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(item)
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(payload)

    def broadcast(self, payload: dict[str, Any]) -> None:
        with self._lock:
            loop = self._loop
            clients = list(self._clients)
        if loop is None or loop.is_closed() or not clients:
            return

        def _dispatch() -> None:
            for q in clients:
                self._enqueue_latest(q, payload)

        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(_dispatch)

    def on_frame(self, frame: SpectrumFrame) -> None:
        rec = self._recording_provider() if callable(self._recording_provider) else None
        self.broadcast(encode_frame_payload(frame, recording=rec))

    def on_status(self, status: dict[str, Any]) -> None:
        self.broadcast({"type": "status", "status": status})

    def register_client(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        with self._lock:
            self._clients.add(q)
        return q

    def unregister_client(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._clients.discard(queue)


async def handle_spectrum_ws(
    websocket: WebSocket,
    broadcaster: SpectrumBroadcaster,
    initial_status_fn: Any,
    latest_frame_fn: Any,
    recording_fn: Any,
) -> None:
    """Serve live spectrum frames and status events over WebSocket."""
    await websocket.accept()
    broadcaster.set_loop(asyncio.get_running_loop())
    queue = broadcaster.register_client()

    try:
        await websocket.send_json({"type": "status", "status": initial_status_fn()})
        latest = latest_frame_fn()
        if latest is not None:
            await websocket.send_json(encode_frame_payload(latest, recording=recording_fn()))

        async def _sender() -> None:
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)

        async def _receiver() -> None:
            while True:
                await websocket.receive_text()

        sender_task = asyncio.create_task(_sender())
        receiver_task = asyncio.create_task(_receiver())
        done, pending = await asyncio.wait(
            {sender_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unregister_client(queue)
