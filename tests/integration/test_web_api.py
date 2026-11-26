"""Integration tests for FastAPI REST + WebSocket Web Studio."""

import base64
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from rtl_sdr_analyzer.config.models import Settings
from rtl_sdr_analyzer.engine.spectrum_engine import SpectrumEngine
from rtl_sdr_analyzer.sources.base import SDRConfigurationError
from rtl_sdr_analyzer.sources.simulated import SimulatedSource
from rtl_sdr_analyzer.storage.database import EventStore
from rtl_sdr_analyzer.web.app import create_app

LOCAL_WS = {"host": "127.0.0.1:8080"}


def _build_test_client(tmp_path: Path) -> tuple[TestClient, SpectrumEngine]:
    settings = Settings(
        source={"mode": "simulated"},
        receiver={"frequency": 98.5e6, "sample_rate": 2.048e6, "fft_size": 1024},
        detector={"min_duration": 0.0, "detection_window": 2, "cooldown_seconds": 0.0},
        display={"target_fps": 40},
        storage={"db_path": str(tmp_path / "web.db"), "recordings_dir": str(tmp_path / "rec")},
    )
    store = EventStore(tmp_path / "web.db")
    src = SimulatedSource(center_freq=98.5e6, sample_rate=2.048e6, realtime=False)
    engine = SpectrumEngine(settings=settings, source=src, store=store)
    app = create_app(engine=engine, store=store, settings=settings)
    return TestClient(app, base_url="http://127.0.0.1:8080"), engine


class TestWebStudioApi:
    def test_static_and_csp_and_health(self, tmp_path: Path) -> None:
        client, _ = _build_test_client(tmp_path)
        with client:
            r = client.get("/")
            assert r.status_code == 200
            assert "rtl-sdr-analyzer" in r.text
            assert "Content-Security-Policy" in r.headers
            assert "default-src 'self'" in r.headers["Content-Security-Policy"]

            css = client.get("/static/amstech-ui/tokens.css")
            assert css.status_code == 200
            assert css.headers["content-type"].startswith("text/css")
            assert "--ams-fondo" in css.text

            for js_path in (
                "/static/js/theme-init.js",
                "/static/js/api.js",
                "/static/js/i18n.js",
                "/static/js/spectrum.js",
                "/static/js/waterfall.js",
                "/static/js/sweep.js",
                "/static/js/main.js",
            ):
                js_res = client.get(js_path)
                assert js_res.status_code == 200
                ct = js_res.headers["content-type"]
                assert ct.startswith(("text/javascript", "application/javascript"))
                assert not ct.startswith("text/plain")

            font_res = client.get("/static/amstech-ui/fuentes/figtree-latin-400-normal.woff2")
            assert font_res.status_code == 200
            assert font_res.headers["content-type"] == "font/woff2"

            svg_res = client.get("/static/img/logo.svg")
            assert svg_res.status_code == 200
            assert svg_res.headers["content-type"].startswith("image/svg+xml")

            h = client.get("/api/health")
            assert h.status_code == 200
            assert h.json()["status"] == "ok"

            d = client.get("/api/devices")
            assert d.status_code == 200
            assert "devices" in d.json()

    def test_receiver_dsp_detector_recording_sweep_and_events(self, tmp_path: Path) -> None:
        client, _ = _build_test_client(tmp_path)
        with client:
            # Tune and toggle manual/auto gain
            r1 = client.patch(
                "/api/receiver",
                json={"frequency": 98_500_000, "fft_size": 2048, "gain": 29.7},
            )
            assert r1.status_code == 200
            assert r1.json()["receiver"]["gain"] == 29.7

            r2 = client.patch("/api/receiver", json={"gain": None})
            assert r2.status_code == 200
            assert r2.json()["receiver"]["gain"] is None

            r3 = client.patch("/api/dsp", json={"window": "hann", "averaging": 2})
            assert r3.status_code == 200
            assert r3.json()["dsp"]["window"] == "hann"

            r4 = client.patch(
                "/api/detector", json={"power_threshold": -65.0, "snr_threshold": 8.0}
            )
            assert r4.status_code == 200
            assert r4.json()["detector"]["power_threshold"] == -65.0

            # Start and stop live recording
            rec_start = client.post("/api/recording/start", json={"format": "raw"})
            assert rec_start.status_code == 200
            filename = rec_start.json()["filename"]
            time.sleep(0.15)
            rec_stop = client.post("/api/recording/stop")
            assert rec_stop.status_code == 200

            recs = client.get("/api/recordings").json()["recordings"]
            assert any(item["filename"] == filename for item in recs)

            dl = client.get(f"/api/recordings/{filename}")
            assert dl.status_code == 200

            # Path traversal must be rejected
            bad = client.get("/api/recordings/..%5Cpyproject.toml")
            assert bad.status_code in (400, 404)

            # Sweep via API
            sw = client.post(
                "/api/sweep",
                json={
                    "start_freq_hz": 97.5e6,
                    "end_freq_hz": 99.5e6,
                    "dwell_seconds": 0.05,
                    "fft_size": 1024,
                },
            )
            assert sw.status_code == 200

            deadline = time.monotonic() + 5.0
            sweep_status = {}
            while time.monotonic() < deadline:
                sweep_status = client.get("/api/sweep").json()
                if not sweep_status.get("running"):
                    break
                time.sleep(0.05)
            assert sweep_status.get("result") is not None
            assert len(sweep_status["result"]["freqs_mhz"]) > 100

            # Events & export
            evs = client.get("/api/events").json()["events"]
            assert isinstance(evs, list)
            csv_exp = client.get("/api/events/export?format=csv")
            assert csv_exp.status_code == 200
            assert "frequency_mhz" in csv_exp.text

            cleared = client.delete("/api/events")
            assert cleared.status_code == 200

    def test_websocket_streams_decodable_frames(self, tmp_path: Path) -> None:
        client, _ = _build_test_client(tmp_path)
        with client, client.websocket_connect("/ws/spectrum", headers=LOCAL_WS) as ws:
            saw_status = False
            saw_frame = False
            for _ in range(15):
                msg = ws.receive_json()
                if msg["type"] == "status":
                    saw_status = True
                elif msg["type"] == "frame":
                    saw_frame = True
                    raw = base64.b64decode(msg["bins_b64"])
                    bins = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 10.0
                    assert len(bins) == msg["fft_size"]
                    assert np.isfinite(bins).all()
                    break
            assert saw_status
            assert saw_frame

    def test_sweep_error_reported_over_api_and_ws_and_engine_recovers(self, tmp_path: Path) -> None:
        client, _ = _build_test_client(tmp_path)
        with (
            client,
            client.websocket_connect("/ws/spectrum", headers=LOCAL_WS) as ws,
            patch(
                "rtl_sdr_analyzer.web.routes.FrequencySweeper.run",
                side_effect=SDRConfigurationError("Failed to tune to 88960000 Hz (rc=-9)"),
            ),
        ):
            # Drain initial status
            first = ws.receive_json()
            assert first["type"] == "status"

            sw = client.post(
                "/api/sweep",
                json={"start_freq_hz": 88e6, "end_freq_hz": 108e6, "dwell_seconds": 0.1},
            )
            assert sw.status_code == 200

            saw_sweep_error = False
            for _ in range(30):
                msg = ws.receive_json()
                if msg.get("type") == "sweep_error":
                    saw_sweep_error = True
                    assert "rc=-9" in msg["error"]
                    break
            assert saw_sweep_error

            deadline = time.monotonic() + 3.0
            sweep_status = {}
            while time.monotonic() < deadline:
                sweep_status = client.get("/api/sweep").json()
                if not sweep_status.get("running"):
                    break
                time.sleep(0.05)
            assert sweep_status.get("running") is False
            assert "rc=-9" in str(sweep_status.get("error", ""))

            # Engine must return cleanly to running state instead of getting stuck in sweeping
            health = client.get("/api/health").json()
            assert health["engine_state"] in ("running", "idle")
            assert health["engine_state"] != "sweeping"

    def test_cross_origin_and_dns_rebinding_are_blocked(self, tmp_path: Path) -> None:
        client, _engine = _build_test_client(tmp_path)
        with client:
            # Same-origin browser request is allowed
            ok = client.post("/api/stream/pause", headers={"Origin": "http://127.0.0.1:8080"})
            assert ok.status_code == 200

            # Another website trying to drive the radio (CSRF) is rejected
            evil = client.post("/api/stream/pause", headers={"Origin": "https://evil.example"})
            assert evil.status_code == 403

            # DNS rebinding: attacker hostname resolving to loopback is rejected
            rebind = client.get("/api/state", headers={"Host": "evil.example:8080"})
            assert rebind.status_code == 403

    def test_recordings_replay_and_delete(self, tmp_path: Path) -> None:
        client, engine = _build_test_client(tmp_path)
        rec_dir = Path(engine.settings.storage.recordings_dir)
        with client:
            name = client.post("/api/recording/start", json={"format": "raw"}).json()["filename"]
            time.sleep(0.3)
            client.post("/api/recording/stop")

            listed = client.get("/api/recordings").json()["recordings"]
            entry = next(r for r in listed if r["filename"] == name)
            assert entry["center_freq_hz"] == engine.settings.receiver.frequency
            assert entry["sample_rate_hz"] and entry["duration_s"] is not None

            # Replay by name only: arbitrary paths / traversal are rejected
            assert (
                client.post(
                    "/api/source", json={"mode": "file", "recording": "../x.raw"}
                ).status_code
                == 400
            )
            st = client.post("/api/source", json={"mode": "file", "recording": name}).json()
            assert st["source_type"] == "file" and st["replay_file"] == name

            # In use while replaying -> cannot delete
            assert client.delete(f"/api/recordings/{name}").status_code == 409

            client.post("/api/source", json={"mode": "simulated"})
            res = client.delete(f"/api/recordings/{name}")
            assert res.status_code == 200
            assert all(r["filename"] != name for r in res.json()["recordings"])
            assert not (rec_dir / name).exists()
            assert not (rec_dir / f"{name}.json").exists()

            # Moved/deleted outside the app -> 404, nothing else touched
            assert client.delete(f"/api/recordings/{name}").status_code == 404
            assert client.delete("/api/recordings/notes.txt").status_code == 400

    def test_replay_transport_seek_speed_and_step(self, tmp_path: Path) -> None:
        client, engine = _build_test_client(tmp_path)
        with client:
            name = client.post("/api/recording/start", json={"format": "raw"}).json()["filename"]
            time.sleep(0.4)
            client.post("/api/recording/stop")

            # Transport is only valid while replaying
            assert client.post("/api/stream/step", json={"direction": 1}).status_code == 409

            st = client.post("/api/source", json={"mode": "file", "recording": name}).json()
            replay = st["replay"]
            assert replay["filename"] == name and replay["duration_s"] > 0

            assert client.patch("/api/replay", json={"speed": 3.0}).status_code == 409
            assert client.patch("/api/replay", json={"speed": 2.0}).json()["replay"]["speed"] == 2.0

            client.post("/api/stream/pause")
            seeked = client.patch("/api/replay", json={"position_s": 0.0}).json()
            assert seeked["state"] == "paused"

            # Step forward renders exactly one 1x frame while staying paused
            time.sleep(0.2)
            before = engine.replay_summary()
            assert before is not None
            frame_s = before["frame_s"]
            step = client.post("/api/stream/step", json={"direction": 1}).json()
            assert step["state"] == "paused"
            time.sleep(0.3)
            after = engine.replay_summary()
            assert after is not None
            assert abs((after["position_s"] - before["position_s"]) - frame_s) < 1e-3

            # Step back returns one frame
            client.post("/api/stream/step", json={"direction": -1})
            time.sleep(0.3)
            back = engine.replay_summary()
            assert back is not None
            assert abs(back["position_s"] - before["position_s"]) < 1e-3

    def test_replay_frame_numbers_and_go_to_frame(self, tmp_path: Path) -> None:
        client, engine = _build_test_client(tmp_path)
        with client:
            name = client.post("/api/recording/start", json={"format": "raw"}).json()["filename"]
            time.sleep(0.4)
            client.post("/api/recording/stop")
            st = client.post("/api/source", json={"mode": "file", "recording": name}).json()
            count = st["replay"]["frame_count"]
            assert count >= 3

            # Jumping to a frame pauses and shows exactly that frame
            res = client.patch("/api/replay", json={"frame": 2}).json()
            assert res["state"] == "paused"
            time.sleep(0.3)
            summary = engine.replay_summary()
            assert summary is not None and summary["frame"] == 2

            client.post("/api/stream/step", json={"direction": 1})
            time.sleep(0.3)
            assert engine.replay_summary()["frame"] == 3  # type: ignore[index]
            client.post("/api/stream/step", json={"direction": -1})
            time.sleep(0.3)
            assert engine.replay_summary()["frame"] == 2  # type: ignore[index]

            assert client.patch("/api/replay", json={"frame": -1}).status_code == 422
