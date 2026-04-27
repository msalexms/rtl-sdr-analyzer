"""Tests for RTLSDRBase (pytest version, migrated from unittest)."""

import socket
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase, RTLSDRException


class TestConnection:
    @patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket")
    def test_connect_success(self, MockSocket: MagicMock) -> None:
        mock_socket_instance = MagicMock()
        MockSocket.return_value = mock_socket_instance

        rtl = RTLSDRBase(host="localhost", port=1234, center_freq=100e6)
        rtl.connect()

        MockSocket.assert_called_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_socket_instance.connect.assert_called_with(("localhost", 1234))

    @patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket")
    def test_connect_failure(self, MockSocket: MagicMock) -> None:
        MockSocket.side_effect = socket.error("Connection failed")

        rtl = RTLSDRBase(host="localhost", port=1234, center_freq=100e6)
        with pytest.raises(RTLSDRException):
            rtl.connect()


class TestReadSamples:
    @patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket")
    def test_read_samples_success(self, MockSocket: MagicMock) -> None:
        mock_socket_instance = MagicMock()
        MockSocket.return_value = mock_socket_instance

        raw_data = np.random.default_rng(42).integers(
            0, 256, 2 * 1024 * 64, dtype=np.uint8
        ).tobytes()
        mock_socket_instance.recv.return_value = raw_data

        rtl = RTLSDRBase(
            host="localhost",
            port=1234,
            center_freq=100e6,
            sample_rate=2.048e6,
            fft_size=1024,
        )
        rtl.sock = mock_socket_instance
        samples = rtl.read_samples()
        assert samples is not None
        assert samples.shape[0] == 1024

    @patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket")
    def test_read_samples_no_data(self, MockSocket: MagicMock) -> None:
        mock_socket_instance = MagicMock()
        MockSocket.return_value = mock_socket_instance
        mock_socket_instance.recv.return_value = b""

        rtl = RTLSDRBase(
            host="localhost",
            port=1234,
            center_freq=100e6,
            sample_rate=2.048e6,
            fft_size=1024,
        )
        rtl.sock = mock_socket_instance
        samples = rtl.read_samples()
        assert samples is None


class TestCommands:
    @patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket")
    def test_send_command_failure(self, MockSocket: MagicMock) -> None:
        mock_socket_instance = MagicMock()
        MockSocket.return_value = mock_socket_instance
        mock_socket_instance.send.side_effect = socket.error("Send failed")

        rtl = RTLSDRBase(
            host="localhost",
            port=1234,
            center_freq=100e6,
            sample_rate=2.048e6,
            fft_size=1024,
        )
        rtl.sock = mock_socket_instance
        with pytest.raises(RTLSDRException):
            rtl._send_command(0x01, int(100e6))


class TestCleanup:
    @patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket")
    def test_cleanup(self, MockSocket: MagicMock) -> None:
        mock_socket_instance = MagicMock()
        MockSocket.return_value = mock_socket_instance

        rtl = RTLSDRBase(host="localhost", port=1234, center_freq=100e6)
        rtl.sock = mock_socket_instance
        rtl._cleanup()

        mock_socket_instance.close.assert_called_once()
        assert rtl.sock is None

    @patch("rtl_sdr_analyzer.core.rtlsdr_base.socket.socket")
    def test_context_manager(self, MockSocket: MagicMock) -> None:
        mock_socket_instance = MagicMock()
        MockSocket.return_value = mock_socket_instance

        rtl = RTLSDRBase(host="localhost", port=1234, center_freq=100e6)
        with rtl as ctx:
            assert ctx is rtl
            assert rtl.sock is not None
        assert rtl.sock is None
