"""Osmocom RTL-TCP network RF source."""

import logging
import socket
import struct
import threading
from enum import IntEnum
from types import TracebackType

import numpy as np

from .base import (
    DeviceInfo,
    SDRConfigurationError,
    SDRConnectionError,
    SDRDisconnectedError,
    SDRSourceError,
    TunerType,
    uint8_iq_to_complex64,
)

logger = logging.getLogger(__name__)

RECV_BUFFER_SIZE: int = 1024 * 1024
RTL0_HEADER_SIZE: int = 12


class RtlTcpCommand(IntEnum):
    """Official Osmocom RTL-TCP protocol command codes."""

    SET_FREQUENCY = 0x01
    SET_SAMPLE_RATE = 0x02
    SET_GAIN_MODE = 0x03
    SET_GAIN = 0x04
    SET_FREQ_CORRECTION = 0x05
    SET_AGC_MODE = 0x08
    SET_DIRECT_SAMPLING = 0x09
    SET_BIAS_TEE = 0x0E


class RtlTcpSource:
    """RTL-TCP network client with proper RTL0 header parsing and I/Q framing."""

    source_type: str = "rtl_tcp"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1234,
        center_freq: float = 98.0e6,
        sample_rate: float = 2.048e6,
        gain: float | None = None,
        ppm: int = 0,
        direct_sampling: int = 0,
        agc: bool = False,
        connect_timeout: float = 5.0,
        read_timeout: float = 2.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.center_freq = float(center_freq)
        self.sample_rate = float(sample_rate)
        self.gain = gain
        self.ppm = int(ppm)
        self.direct_sampling = int(direct_sampling)
        self.agc = bool(agc)
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)

        self._lock = threading.RLock()
        self._sock: socket.socket | None = None
        self._rx_buf = bytearray()
        self._info = DeviceInfo(
            index=0,
            name=f"RTL-TCP ({host}:{port})",
            source_type="rtl_tcp",
        )

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._sock is not None

    @property
    def info(self) -> DeviceInfo:
        with self._lock:
            return self._info.model_copy()

    def __enter__(self) -> "RtlTcpSource":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def open(self) -> None:
        """Connect to RTL-TCP, read the 12-byte RTL0 header, and configure tuner."""
        with self._lock:
            if self._sock is not None:
                return

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUFFER_SIZE)
                sock.settimeout(self.connect_timeout)

                logger.info("Connecting to RTL-TCP server at %s:%d", self.host, self.port)
                sock.connect((self.host, self.port))
                sock.settimeout(self.read_timeout)

                self._sock = sock
                self._rx_buf.clear()

                header = self._recv_exact_bytes(RTL0_HEADER_SIZE)
                magic, tuner_code, gain_count = struct.unpack(">4sII", header)
                if magic != b"RTL0":
                    raise SDRConnectionError(f"Unexpected RTL-TCP header magic: {magic!r}")

                tuner = TunerType.label(tuner_code)
                self._send_initial_config()

                self._info = DeviceInfo(
                    index=0,
                    name=f"RTL-TCP {self.host}:{self.port}",
                    source_type="rtl_tcp",
                    tuner=tuner,
                    connected=True,
                    detail=f"gain_steps={gain_count}",
                )
                logger.info("Connected to RTL-TCP (%s:%d, tuner=%s)", self.host, self.port, tuner)
            except SDRSourceError:
                self.close()
                raise
            except OSError as exc:
                self.close()
                raise SDRConnectionError(
                    f"Failed to connect to RTL-TCP at {self.host}:{self.port}: {exc}"
                ) from exc

    def _send_initial_config(self) -> None:
        self._send_command(RtlTcpCommand.SET_DIRECT_SAMPLING, self.direct_sampling)
        self._send_command(RtlTcpCommand.SET_AGC_MODE, 1 if self.agc else 0)
        self._send_command(RtlTcpCommand.SET_SAMPLE_RATE, int(round(self.sample_rate)))
        if self.gain is None:
            self._send_command(RtlTcpCommand.SET_GAIN_MODE, 0)
        else:
            self._send_command(RtlTcpCommand.SET_GAIN_MODE, 1)
            self._send_command(RtlTcpCommand.SET_GAIN, int(round(self.gain * 10.0)))
        if self.ppm != 0:
            self._send_command(RtlTcpCommand.SET_FREQ_CORRECTION, self.ppm)
        self._send_command(RtlTcpCommand.SET_FREQUENCY, int(round(self.center_freq)))

    def _send_command(self, command: int, value: int) -> None:
        if self._sock is None:
            raise SDRDisconnectedError("RTL-TCP socket is not connected")
        # Frequency correction uses signed 32-bit in Osmocom rtl_tcp; pack accordingly
        fmt = ">Bi" if command == RtlTcpCommand.SET_FREQ_CORRECTION else ">BI"
        try:
            self._sock.sendall(struct.pack(fmt, int(command), int(value)))
        except OSError as exc:
            raise SDRConfigurationError(
                f"Failed to send RTL-TCP command {command:#x}: {exc}"
            ) from exc

    def _recv_exact_bytes(self, num_bytes: int) -> bytes:
        if self._sock is None:
            raise SDRDisconnectedError("RTL-TCP socket is not connected")

        while len(self._rx_buf) < num_bytes:
            want = max(16384, num_bytes - len(self._rx_buf))
            try:
                chunk = self._sock.recv(want)
            except TimeoutError as exc:
                raise SDRConnectionError(
                    f"Timed out waiting for RTL-TCP data ({self.host}:{self.port})"
                ) from exc
            except OSError as exc:
                raise SDRDisconnectedError(f"RTL-TCP receive error: {exc}") from exc

            if not chunk:
                raise SDRDisconnectedError("RTL-TCP server closed connection")
            self._rx_buf.extend(chunk)

        out = bytes(self._rx_buf[:num_bytes])
        del self._rx_buf[:num_bytes]
        return out

    def close(self) -> None:
        """Close the TCP socket and clear receive buffers."""
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                    logger.info("Closed RTL-TCP connection (%s:%d)", self.host, self.port)
                except OSError as exc:
                    logger.warning("Error closing RTL-TCP socket: %s", exc)
            self._sock = None
            self._rx_buf.clear()
            self._info = self._info.model_copy(update={"connected": False})

    def read_samples(self, num_samples: int) -> np.ndarray:
        """Read ``num_samples`` framed ``complex64`` IQ samples without losing byte alignment."""
        if num_samples <= 0:
            return np.empty(0, dtype=np.complex64)
        with self._lock:
            raw = self._recv_exact_bytes(num_samples * 2)
            return uint8_iq_to_complex64(raw)

    def set_center_freq(self, freq_hz: float) -> None:
        """Tune the remote RTL-TCP server to ``freq_hz``."""
        with self._lock:
            self._send_command(RtlTcpCommand.SET_FREQUENCY, int(round(freq_hz)))
            self.center_freq = float(freq_hz)

    def set_sample_rate(self, rate_hz: float) -> None:
        """Update remote sample rate in Hz."""
        with self._lock:
            self._send_command(RtlTcpCommand.SET_SAMPLE_RATE, int(round(rate_hz)))
            self.sample_rate = float(rate_hz)

    def set_gain(self, gain_db: float | None) -> None:
        """Set manual gain in dB or automatic gain when ``None``."""
        with self._lock:
            if gain_db is None:
                self._send_command(RtlTcpCommand.SET_GAIN_MODE, 0)
                self.gain = None
            else:
                self._send_command(RtlTcpCommand.SET_GAIN_MODE, 1)
                self._send_command(RtlTcpCommand.SET_GAIN, int(round(gain_db * 10.0)))
                self.gain = float(gain_db)

    def set_ppm(self, ppm: int) -> None:
        """Set crystal frequency correction in ppm."""
        with self._lock:
            self._send_command(RtlTcpCommand.SET_FREQ_CORRECTION, int(ppm))
            self.ppm = int(ppm)

    def flush_buffer(self, discard_samples: int = 16384) -> None:
        """Drain buffered TCP samples so stale pre-retune data is discarded."""
        with self._lock:
            if self._sock is None:
                return
            self._rx_buf.clear()
            if discard_samples > 0:
                self._recv_exact_bytes(discard_samples * 2)
