"""Unit tests for RF sources: RTL-TCP, USB (mocked ctypes), Simulated, Replay, Factory."""

import ctypes
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rtl_sdr_analyzer.config.models import Settings
from rtl_sdr_analyzer.sources.base import (
    SDRConfigurationError,
    SDRConnectionError,
    SDRDisconnectedError,
    uint8_iq_to_complex64,
)
from rtl_sdr_analyzer.sources.factory import create_source
from rtl_sdr_analyzer.sources.replay import FileReplaySource
from rtl_sdr_analyzer.sources.rtl_tcp import RtlTcpCommand, RtlTcpSource
from rtl_sdr_analyzer.sources.simulated import SimulatedSource
from rtl_sdr_analyzer.sources.usb import LocalUsbSource, enumerate_usb_devices


class TestIqLut:
    def test_uint8_iq_conversion_bounds(self) -> None:
        raw = bytes([0, 255, 128, 127])
        iq = uint8_iq_to_complex64(raw)
        assert iq.dtype == np.complex64
        assert len(iq) == 2
        assert iq[0].real == pytest.approx(-1.0, abs=1e-4)
        assert iq[0].imag == pytest.approx(1.0, abs=1e-4)
        assert abs(iq[1].real) < 0.01


class TestRtlTcpSource:
    @patch("rtl_sdr_analyzer.sources.rtl_tcp.socket.socket")
    def test_rtl0_handshake_and_opcodes(self, mock_sock_cls: MagicMock) -> None:
        sock = MagicMock()
        mock_sock_cls.return_value = sock
        header = struct.pack(">4sII", b"RTL0", 5, 29)
        iq_bytes = bytes([128, 128] * 64)
        sock.recv.side_effect = [header, iq_bytes]

        src = RtlTcpSource(
            host="127.0.0.1", port=1234, center_freq=98e6, sample_rate=2.048e6, ppm=-3
        )
        with src:
            assert src.is_open
            assert src.info.tuner == "R820T"
            samples = src.read_samples(64)
            assert len(samples) == 64

        sent = b"".join(call.args[0] for call in sock.sendall.call_args_list)
        # Verify correct official opcodes present in command stream
        opcodes = [sent[i] for i in range(0, len(sent), 5)]
        assert RtlTcpCommand.SET_DIRECT_SAMPLING in opcodes
        assert RtlTcpCommand.SET_AGC_MODE in opcodes
        assert RtlTcpCommand.SET_SAMPLE_RATE in opcodes
        assert RtlTcpCommand.SET_GAIN_MODE in opcodes
        assert RtlTcpCommand.SET_FREQ_CORRECTION in opcodes
        assert RtlTcpCommand.SET_FREQUENCY in opcodes
        assert not src.is_open

    @patch("rtl_sdr_analyzer.sources.rtl_tcp.socket.socket")
    def test_odd_byte_framing_preserved_and_eof_raises(self, mock_sock_cls: MagicMock) -> None:
        sock = MagicMock()
        mock_sock_cls.return_value = sock
        header = struct.pack(">4sII", b"RTL0", 5, 29)
        # Split 8 bytes (4 IQ samples) across odd boundaries: 3 + 5 bytes
        chunk1 = bytes([255, 0, 255])
        chunk2 = bytes([0, 255, 0, 255, 0])
        sock.recv.side_effect = [header, chunk1, chunk2, b""]

        src = RtlTcpSource()
        with src:
            iq = src.read_samples(4)
            # Every sample must remain I=+1.0, Q=-1.0 without byte slip
            assert np.all(iq.real > 0.99)
            assert np.all(iq.imag < -0.99)
            with pytest.raises(SDRDisconnectedError):
                src.read_samples(4)


class TestLocalUsbSourceMocked:
    def _make_fake_lib(self) -> MagicMock:
        lib = MagicMock()
        lib.rtlsdr_get_device_count.return_value = 1
        lib.rtlsdr_get_device_name.return_value = b"Generic RTL2832U OEM"
        lib.rtlsdr_get_device_usb_strings.return_value = 0

        def fake_open(dev_ptr: ctypes.c_void_p, _idx: int) -> int:
            # ctypes.byref writes via _obj when called in mock, simulate via side effect
            obj = ctypes.cast(dev_ptr, ctypes.POINTER(ctypes.c_void_p))
            obj[0] = ctypes.c_void_p(0x123456)
            return 0

        def fake_gains(_dev: object, arr: object) -> int:
            if arr is None:
                return 3
            arr[0] = 0  # type: ignore[index]
            arr[1] = 197  # type: ignore[index]
            arr[2] = 297  # type: ignore[index]
            return 3

        def fake_read(_dev: object, buf: object, length: int, n_read_ptr: object) -> int:
            n_obj = ctypes.cast(n_read_ptr, ctypes.POINTER(ctypes.c_int))
            n_obj[0] = length
            return 0

        lib.rtlsdr_open.side_effect = fake_open
        lib.rtlsdr_get_tuner_type.return_value = 5
        lib.rtlsdr_get_tuner_gains.side_effect = fake_gains
        lib.rtlsdr_set_direct_sampling.return_value = 0
        lib.rtlsdr_set_agc_mode.return_value = 0
        lib.rtlsdr_set_sample_rate.return_value = 0
        lib.rtlsdr_set_tuner_gain_mode.return_value = 0
        lib.rtlsdr_set_tuner_gain.return_value = 0
        lib.rtlsdr_set_freq_correction.return_value = -2  # tolerate already-set code
        lib.rtlsdr_set_center_freq.return_value = 0
        lib.rtlsdr_reset_buffer.return_value = 0
        lib.rtlsdr_read_sync.side_effect = fake_read
        lib.rtlsdr_close.return_value = 0
        return lib

    def test_open_gain_snap_and_read(self) -> None:
        fake_lib = self._make_fake_lib()
        with patch(
            "rtl_sdr_analyzer.sources.usb._load_librtlsdr",
            return_value=(fake_lib, Path("rtlsdr.dll")),
        ):
            devices, detail = enumerate_usb_devices()
            assert len(devices) == 1
            assert "Generic RTL2832U" in devices[0].name
            assert detail == "rtlsdr.dll"

            src = LocalUsbSource(center_freq=98e6, sample_rate=2.048e6, gain=28.0, ppm=2)
            with src:
                assert src.is_open
                assert src.info.tuner == "R820T"
                # 28.0 snaps to nearest in [0.0, 19.7, 29.7] -> 29.7
                assert src.gain == 29.7
                iq = src.read_samples(2048)
                assert len(iq) == 2048
                assert iq.dtype == np.complex64
                src.set_center_freq(100e6)
                src.flush_buffer()
            assert not src.is_open

    def test_tune_resets_buffer_and_recovers_transient_error(self) -> None:
        fake_lib = self._make_fake_lib()
        # 1st call in open() -> 0; then in set_center_freq: -9 (fail), 0 (recovered)
        fake_lib.rtlsdr_set_center_freq.side_effect = [0, -9, 0]
        with (
            patch(
                "rtl_sdr_analyzer.sources.usb._load_librtlsdr",
                return_value=(fake_lib, Path("rtlsdr.dll")),
            ),
            patch("rtl_sdr_analyzer.sources.usb.time.sleep"),
        ):
            src = LocalUsbSource(center_freq=98e6, sample_rate=2.048e6)
            with src:
                reset_before = fake_lib.rtlsdr_reset_buffer.call_count
                src.set_center_freq(100.5e6)
                assert src.center_freq == pytest.approx(100.5e6)
                assert fake_lib.rtlsdr_reset_buffer.call_count >= reset_before + 2

    def test_tune_recovers_by_reopening_persistent_error(self) -> None:
        fake_lib = self._make_fake_lib()
        # open() -> 0; 1st attempt + 2 retries -> -9, -9, -9; reopen() -> 0; post-reopen tune -> 0
        fake_lib.rtlsdr_set_center_freq.side_effect = [0, -9, -9, -9, 0, 0]
        with (
            patch(
                "rtl_sdr_analyzer.sources.usb._load_librtlsdr",
                return_value=(fake_lib, Path("rtlsdr.dll")),
            ),
            patch("rtl_sdr_analyzer.sources.usb.time.sleep"),
        ):
            src = LocalUsbSource(center_freq=98e6, sample_rate=2.4e6)
            with src:
                src.set_center_freq(102.3e6)
                assert src.center_freq == pytest.approx(102.3e6)
                assert fake_lib.rtlsdr_open.call_count == 2
                assert fake_lib.rtlsdr_close.call_count >= 1
            # Closing also resets buffer first
            assert fake_lib.rtlsdr_reset_buffer.call_count >= 6

    def test_tune_raises_when_recovery_exhausted(self) -> None:
        fake_lib = self._make_fake_lib()
        # open() -> 0; attempts -> -9; reopen() -> 0; retry -> -9
        fake_lib.rtlsdr_set_center_freq.side_effect = [0, -9, -9, -9, 0, -9]
        with (
            patch(
                "rtl_sdr_analyzer.sources.usb._load_librtlsdr",
                return_value=(fake_lib, Path("rtlsdr.dll")),
            ),
            patch("rtl_sdr_analyzer.sources.usb.time.sleep"),
        ):
            src = LocalUsbSource(center_freq=98e6, sample_rate=2.4e6)
            with src:
                with pytest.raises(SDRConfigurationError, match="rc=-9"):
                    src.set_center_freq(105.0e6)
                # Center frequency state must remain at previous valid frequency
                assert src.center_freq == pytest.approx(98e6)


class TestSimulatedAndReplayAndFactory:
    def test_simulated_source_places_fm_carriers(self) -> None:
        src = SimulatedSource(center_freq=98.5e6, sample_rate=2.048e6, realtime=False)
        with src:
            iq = src.read_samples(2048)
            assert len(iq) == 2048
            assert iq.dtype == np.complex64
            spec = np.abs(np.fft.fftshift(np.fft.fft(iq)))
            # Center bin (1024) corresponds to 98.5 MHz carrier
            assert spec[1024] > np.median(spec) * 10

    def test_file_replay_raw_and_npz(self, tmp_path: Path) -> None:
        raw_path = tmp_path / "sample.raw"
        raw_path.write_bytes(bytes([200, 100] * 1024))
        with FileReplaySource(
            raw_path, center_freq=433.92e6, sample_rate=2.048e6, realtime=False
        ) as src:
            iq = src.read_samples(1500)  # wraps cleanly past EOF
            assert len(iq) == 1500

        npz_path = tmp_path / "sample.npz"
        np.savez(
            npz_path,
            iq=np.ones(512, dtype=np.complex64) * 0.25,
            sample_rate=1.024e6,
            center_freq=446.0e6,
        )
        with FileReplaySource(npz_path, realtime=False) as src:
            assert src.sample_rate == 1.024e6
            assert src.center_freq == 446.0e6
            iq = src.read_samples(256)
            assert len(iq) == 256

    def test_factory_auto_falls_back_to_simulated(self) -> None:
        s = Settings(source={"mode": "auto"})
        with (
            patch(
                "rtl_sdr_analyzer.sources.factory.enumerate_usb_devices",
                return_value=([], "missing"),
            ),
            patch("rtl_sdr_analyzer.sources.factory._tcp_endpoint_reachable", return_value=False),
        ):
            src = create_source(s, allow_simulated_fallback=True)
            assert isinstance(src, SimulatedSource)

    def test_factory_auto_strict_raises_when_no_hardware(self) -> None:
        s = Settings(source={"mode": "auto"})
        with (
            patch(
                "rtl_sdr_analyzer.sources.factory.enumerate_usb_devices",
                return_value=([], "missing"),
            ),
            patch("rtl_sdr_analyzer.sources.factory._tcp_endpoint_reachable", return_value=False),
            pytest.raises(SDRConnectionError),
        ):
            create_source(s, allow_simulated_fallback=False)

    def test_replay_uses_recording_metadata_and_keeps_tuning_fixed(self, tmp_path: Path) -> None:
        from rtl_sdr_analyzer.recording.recorder import IQRecorder
        from rtl_sdr_analyzer.sources.base import SDRConfigurationError

        rec_path = tmp_path / "iq_433.920MHz_test.raw"
        with IQRecorder(rec_path, format="raw", sample_rate=1.024e6, center_freq=433.92e6) as rec:
            rec.write_samples(np.full(4096, 0.5 - 0.25j, dtype=np.complex64))
        assert (tmp_path / "iq_433.920MHz_test.raw.json").is_file()

        # Defaults are deliberately wrong: metadata from the sidecar must win.
        with FileReplaySource(
            rec_path, center_freq=98e6, sample_rate=2.048e6, realtime=False
        ) as src:
            assert src.center_freq == 433.92e6
            assert src.sample_rate == 1.024e6
            iq = src.read_samples(6000)  # wraps past EOF from a memmap
            assert len(iq) == 6000
            assert np.allclose(iq[:10], 0.5 - 0.25j, atol=0.01)
            src.set_center_freq(433.92e6)  # no-op is fine
            with pytest.raises(SDRConfigurationError):
                src.set_center_freq(100e6)

    def test_replay_without_metadata_parses_frequency_from_name(self, tmp_path: Path) -> None:
        path = tmp_path / "capture_868.300MHz.cu8"
        path.write_bytes(bytes([128, 128] * 64))
        with FileReplaySource(path, sample_rate=2.4e6, realtime=False) as src:
            assert src.center_freq == 868.3e6
            assert src.sample_rate == 2.4e6
