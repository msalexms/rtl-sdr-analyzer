"""Integration tests for SpectrumEngine and FrequencySweeper."""

import threading
from pathlib import Path

from rtl_sdr_analyzer.config.models import Settings
from rtl_sdr_analyzer.detection.events import SpectrumFrame
from rtl_sdr_analyzer.engine.spectrum_engine import SpectrumEngine
from rtl_sdr_analyzer.engine.sweeper import FrequencySweeper, SweepConfig
from rtl_sdr_analyzer.sources.simulated import SimulatedSource
from rtl_sdr_analyzer.storage.database import EventStore


class TestSpectrumEngineAndSweeper:
    def test_engine_live_reconfigure_record_and_pause(self, tmp_path: Path) -> None:
        settings = Settings(
            source={"mode": "simulated"},
            receiver={"frequency": 98.0e6, "sample_rate": 2.048e6, "fft_size": 1024},
            detector={"min_duration": 0.0, "detection_window": 2, "cooldown_seconds": 0.0},
            display={"target_fps": 60},
            storage={"recordings_dir": str(tmp_path / "rec")},
        )
        store = EventStore(tmp_path / "events.db")
        src = SimulatedSource(center_freq=98.0e6, sample_rate=2.048e6, realtime=False)
        engine = SpectrumEngine(settings=settings, source=src, store=store)

        frames: list[SpectrumFrame] = []
        done = threading.Event()

        def on_frame(frame: SpectrumFrame) -> None:
            frames.append(frame)
            if len(frames) >= 6:
                done.set()

        engine.subscribe_frames(on_frame)
        engine.start()
        try:
            assert done.wait(timeout=4.0), "Engine did not produce 6 frames in time"

            rec_info = engine.start_recording(output_format="raw")
            assert rec_info["format"] == "raw"

            engine.update_receiver(frequency=98.5e6, fft_size=2048, gain=29.7)
            engine.update_dsp(window="hann", averaging=2)
            engine.update_detector({"power_threshold": -65.0})

            engine.pause()
            assert engine.get_status()["state"] == "paused"
            engine.resume()
            assert engine.get_status()["state"] == "running"

            stopped = engine.stop_recording()
            assert stopped is not None
            assert Path(stopped["path"]).exists()

            # Exclusive sweep while engine is running
            with engine.pause_for_exclusive_use() as exclusive_src:
                sweeper = FrequencySweeper(event_bus=engine.event_bus, store=store)
                res = sweeper.run(
                    exclusive_src,
                    SweepConfig(
                        start_freq_hz=97.0e6,
                        end_freq_hz=101.0e6,
                        dwell_seconds=0.02,
                        min_frames=2,
                        fft_size=1024,
                        snr_threshold_db=6.0,
                    ),
                )
                assert len(res.freqs_mhz) > 500
                assert any(abs(p.frequency_mhz - 98.5) < 0.2 for p in res.peaks)
        finally:
            engine.stop()

        assert store.get_event_count() >= 1
        sessions = store.get_sessions()
        assert len(sessions) == 1
        assert sessions[0]["end_time"] is not None

    def test_recording_captures_the_full_stream_without_gaps(self, tmp_path: Path) -> None:
        """Every sample read while recording must reach the file (no per-frame decimation)."""
        settings = Settings(
            source={"mode": "simulated"},
            receiver={"sample_rate": 1.024e6, "fft_size": 1024},
            dsp={"averaging": 1},
            display={"target_fps": 10},
            storage={"recordings_dir": str(tmp_path / "rec")},
        )
        src = SimulatedSource(center_freq=98.0e6, sample_rate=1.024e6, realtime=False)
        engine = SpectrumEngine(settings=settings, source=src)
        reads: list[int] = []
        original_read = src.read_samples

        def counting_read(n: int):  # type: ignore[no-untyped-def]
            out = original_read(n)
            reads.append(len(out))
            return out

        src.read_samples = counting_read  # type: ignore[method-assign]
        engine.start()
        try:
            engine.start_recording(output_format="raw")
            reads.clear()
            threading.Event().wait(0.5)
            summary = engine.stop_recording()
        finally:
            engine.stop()

        assert summary is not None
        # One frame's worth of samples (sample_rate / fps) per read, not just fft_size.
        assert reads and max(reads) == int(1.024e6 / 10)
        assert summary["samples"] >= sum(reads[:-1])
