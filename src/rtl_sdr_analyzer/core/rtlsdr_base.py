"""RTL-SDR Base Module.

Handles the core RTL-SDR functionality including device connection, configuration,
and sample acquisition with proper error handling and logging.
"""

import errno
import logging
import socket
import struct
from enum import IntEnum
from types import TracebackType
from typing import Optional, Type

import numpy as np
from scipy.signal.windows import blackmanharris

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DC_OFFSET: float = 127.5
IQ_SCALE: float = 127.5
EPSILON: float = 1e-12
RECV_BUFFER_SIZE: int = 1024 * 1024
SOCKET_TIMEOUT: float = 1.0


class RTLSDRException(Exception):
    """Custom exception for RTL-SDR related errors."""


class RtlTcpCommand(IntEnum):
    """RTL-TCP protocol command codes."""

    SET_FREQUENCY = 0x01
    SET_SAMPLE_RATE = 0x02
    SET_GAIN_MODE = 0x03
    SET_AGC_MODE = 0x05
    SET_DIRECT_SAMPLING = 0x08


class RTLSDRBase:
    """Base class for RTL-SDR operations with robust error handling.

    Supports use as a context manager to guarantee connection cleanup:

        with RTLSDRBase(host, port, freq) as rtl:
            samples = rtl.read_samples()
    """

    def __init__(
        self,
        host: str,
        port: int,
        center_freq: float,
        sample_rate: float = 2.048e6,
        fft_size: int = 1024,
    ):
        self.host = host
        self.port = port
        self.center_freq = center_freq
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.sock: Optional[socket.socket] = None
        self.window = blackmanharris(fft_size)

        # Frequency range in MHz for spectrum plotting
        self.freq_range = np.linspace(
            -sample_rate / 2e6 + center_freq / 1e6,
            sample_rate / 2e6 + center_freq / 1e6,
            fft_size,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "RTLSDRBase":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._cleanup()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Establish connection to the RTL-TCP server.

        Raises:
            RTLSDRException: If the connection or device configuration fails.
        """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUFFER_SIZE)
            self.sock.settimeout(SOCKET_TIMEOUT)

            logger.info("Connecting to RTL-TCP server at %s:%d", self.host, self.port)
            self.sock.connect((self.host, self.port))

            self._configure_device()
            logger.info("Successfully connected to RTL-TCP server")
        except socket.error as exc:
            self._cleanup()
            raise RTLSDRException(f"Failed to connect to RTL-TCP server: {exc}") from exc

    def _configure_device(self) -> None:
        """Send initial configuration commands to the RTL-SDR device.

        Raises:
            RTLSDRException: If any command fails.
        """
        commands: list[tuple[int, int]] = [
            (RtlTcpCommand.SET_FREQUENCY, int(self.center_freq)),
            (RtlTcpCommand.SET_SAMPLE_RATE, int(self.sample_rate)),
            (RtlTcpCommand.SET_GAIN_MODE, 0),          # auto gain
            (RtlTcpCommand.SET_AGC_MODE, 0),           # AGC off
            (RtlTcpCommand.SET_DIRECT_SAMPLING, 1),    # direct sampling
        ]

        try:
            for cmd, value in commands:
                self._send_command(cmd, value)
        except Exception as exc:
            raise RTLSDRException(f"Failed to configure device: {exc}") from exc

    def _send_command(self, command: int, value: int) -> None:
        """Send a single command to the RTL-SDR device.

        Args:
            command: RTL-TCP command byte.
            value: 32-bit unsigned value.

        Raises:
            RTLSDRException: If the socket is not connected or the send fails.
        """
        if self.sock is None:
            raise RTLSDRException("No connection to RTL-TCP server")

        try:
            self.sock.send(struct.pack(">BI", command, value))
        except socket.error as exc:
            raise RTLSDRException(f"Failed to send command: {exc}") from exc

    # ------------------------------------------------------------------
    # Sample acquisition
    # ------------------------------------------------------------------

    def read_samples(self) -> Optional[np.ndarray]:
        """Read IQ samples from the RTL-SDR device.

        Returns:
            Complex numpy array of length ``fft_size``, or ``None`` if no
            data is available.

        Raises:
            RTLSDRException: If the socket is not connected.
        """
        if self.sock is None:
            raise RTLSDRException("No connection to RTL-TCP server")

        try:
            raw_data = self.sock.recv(self.fft_size * 2 * 64)
            if not raw_data:
                return None

            # Convert interleaved uint8 → complex float64
            data = np.frombuffer(raw_data, dtype=np.uint8).reshape(-1, 2)
            iq = ((data[:, 0] + 1j * data[:, 1]) - DC_OFFSET - 1j * DC_OFFSET) / IQ_SCALE

            if len(iq) >= self.fft_size:
                logger.debug("Received %d samples", self.fft_size)
                return iq[: self.fft_size]
            return None

        except socket.error as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                logger.warning("Error reading samples: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        """Close the TCP socket and reset state."""
        if self.sock is not None:
            try:
                self.sock.close()
                logger.info("Closed RTL-TCP connection")
            except Exception as exc:  # noqa: BLE001
                logger.error("Error during cleanup: %s", exc)
            finally:
                self.sock = None
