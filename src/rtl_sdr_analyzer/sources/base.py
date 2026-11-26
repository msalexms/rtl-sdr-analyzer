"""Base protocols, data models, exceptions, and IQ conversion helpers."""

from enum import IntEnum
from types import TracebackType
from typing import Protocol, runtime_checkable

import numpy as np
from pydantic import BaseModel, Field


class SDRSourceError(Exception):
    """Base exception for all SDR input source failures."""


class SDRConnectionError(SDRSourceError):
    """Raised when connecting to or reading from an SDR source fails."""


class SDRDisconnectedError(SDRConnectionError):
    """Raised when an active SDR device or server disconnects."""


class SDRConfigurationError(SDRSourceError):
    """Raised when applying receiver settings fails."""


class SDRLibraryNotFoundError(SDRSourceError):
    """Raised when native librtlsdr shared library cannot be located."""


class TunerType(IntEnum):
    """Known RTL-SDR tuner chipset identifiers."""

    UNKNOWN = 0
    E4000 = 1
    FC0012 = 2
    FC0013 = 3
    FC2580 = 4
    R820T = 5
    R828D = 6

    @classmethod
    def label(cls, value: int) -> str:
        """Return human-readable tuner name for a numeric code."""
        try:
            return cls(value).name
        except ValueError:
            return f"UNKNOWN({value})"


class DeviceInfo(BaseModel):
    """Metadata describing an SDR source or hardware dongle."""

    index: int = 0
    name: str
    source_type: str
    tuner: str = "UNKNOWN"
    manufacturer: str = ""
    product: str = ""
    serial: str = ""
    supported_gains: list[float] = Field(default_factory=list)
    connected: bool = False
    detail: str = ""


@runtime_checkable
class SDRSource(Protocol):
    """Protocol implemented by all RF sample sources."""

    source_type: str
    center_freq: float
    sample_rate: float
    gain: float | None
    ppm: int

    @property
    def is_open(self) -> bool:
        """Return whether the source is currently open and ready."""
        ...

    @property
    def info(self) -> DeviceInfo:
        """Return metadata about the active source."""
        ...

    def open(self) -> None:
        """Open and configure the RF source."""
        ...

    def close(self) -> None:
        """Close the RF source and release resources."""
        ...

    def __enter__(self) -> "SDRSource": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    def read_samples(self, num_samples: int) -> np.ndarray:
        """Read ``num_samples`` normalized ``complex64`` IQ samples."""
        ...

    def set_center_freq(self, freq_hz: float) -> None:
        """Tune the receiver to ``freq_hz``."""
        ...

    def set_sample_rate(self, rate_hz: float) -> None:
        """Update the receiver sample rate in Hz."""
        ...

    def set_gain(self, gain_db: float | None) -> None:
        """Set manual gain in dB, or ``None`` for automatic gain."""
        ...

    def set_ppm(self, ppm: int) -> None:
        """Set crystal frequency correction in parts per million."""
        ...

    def flush_buffer(self, discard_samples: int = 16384) -> None:
        """Discard stale buffered samples after retuning."""
        ...


# Precomputed 256-entry uint8 -> float32 normalized LUT in [-1.0, +1.0]
_IQ_LUT: np.ndarray = (np.arange(256, dtype=np.float32) - np.float32(127.5)) / np.float32(127.5)


def uint8_iq_to_complex64(raw: bytes | bytearray | memoryview | np.ndarray) -> np.ndarray:
    """Convert interleaved ``uint8`` I/Q bytes to normalized ``complex64`` samples.

    Drops at most one trailing byte if ``raw`` has odd length; callers streaming
    framed packets should preserve odd remainder bytes externally.
    """
    arr = raw if isinstance(raw, np.ndarray) else np.frombuffer(raw, dtype=np.uint8)
    even_len = (len(arr) // 2) * 2
    if even_len == 0:
        return np.empty(0, dtype=np.complex64)
    if even_len != len(arr):
        arr = arr[:even_len]
    floats = np.ascontiguousarray(_IQ_LUT[arr], dtype=np.float32)
    return floats.view(np.complex64).copy()
