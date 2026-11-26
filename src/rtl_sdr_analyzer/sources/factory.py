"""Factory for constructing the configured RF input source."""

import logging
import socket

from rtl_sdr_analyzer.config.models import Settings

from .base import SDRConnectionError, SDRSource
from .replay import FileReplaySource
from .rtl_tcp import RtlTcpSource
from .simulated import SimulatedSource
from .usb import LocalUsbSource, enumerate_usb_devices

logger = logging.getLogger(__name__)


def _tcp_endpoint_reachable(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def create_source(
    settings: Settings,
    *,
    allow_simulated_fallback: bool = True,
) -> SDRSource:
    """Create an :class:`SDRSource` from validated settings.

    In ``auto`` mode:
        1. Probes local USB RTL-SDR devices via ``librtlsdr``.
        2. If none found, probes configured ``rtl_tcp`` endpoint.
        3. Falls back to :class:`SimulatedSource` (when ``allow_simulated_fallback=True``)
           or raises :class:`SDRConnectionError`.
    """
    mode = settings.source.mode
    rx = settings.receiver

    if mode == "usb":
        return LocalUsbSource(
            device_index=settings.source.device_index,
            center_freq=rx.frequency,
            sample_rate=rx.sample_rate,
            gain=rx.gain,
            ppm=rx.ppm,
            direct_sampling=rx.direct_sampling,
            agc=rx.agc,
            library_path=settings.source.library_path,
        )

    if mode == "rtl_tcp":
        return RtlTcpSource(
            host=settings.rtl_tcp.host,
            port=settings.rtl_tcp.port,
            center_freq=rx.frequency,
            sample_rate=rx.sample_rate,
            gain=rx.gain,
            ppm=rx.ppm,
            direct_sampling=rx.direct_sampling,
            agc=rx.agc,
            connect_timeout=settings.rtl_tcp.connect_timeout,
            read_timeout=settings.rtl_tcp.read_timeout,
        )

    if mode == "simulated":
        return SimulatedSource(
            center_freq=rx.frequency,
            sample_rate=rx.sample_rate,
            gain=rx.gain,
            ppm=rx.ppm,
        )

    if mode == "file":
        if not settings.source.replay_path:
            raise SDRConnectionError("source.replay_path is required when source.mode='file'")
        return FileReplaySource(
            file_path=settings.source.replay_path,
            center_freq=rx.frequency,
            sample_rate=rx.sample_rate,
        )

    # Auto-detection
    devices, detail = enumerate_usb_devices(settings.source.library_path)
    if devices and settings.source.device_index < len(devices):
        logger.info(
            "Auto-selected USB RTL-SDR #%d (%s)",
            settings.source.device_index,
            devices[settings.source.device_index].name,
        )
        return LocalUsbSource(
            device_index=settings.source.device_index,
            center_freq=rx.frequency,
            sample_rate=rx.sample_rate,
            gain=rx.gain,
            ppm=rx.ppm,
            direct_sampling=rx.direct_sampling,
            agc=rx.agc,
            library_path=settings.source.library_path,
        )

    if _tcp_endpoint_reachable(settings.rtl_tcp.host, settings.rtl_tcp.port):
        logger.info(
            "Auto-selected RTL-TCP at %s:%d",
            settings.rtl_tcp.host,
            settings.rtl_tcp.port,
        )
        return RtlTcpSource(
            host=settings.rtl_tcp.host,
            port=settings.rtl_tcp.port,
            center_freq=rx.frequency,
            sample_rate=rx.sample_rate,
            gain=rx.gain,
            ppm=rx.ppm,
            direct_sampling=rx.direct_sampling,
            agc=rx.agc,
            connect_timeout=settings.rtl_tcp.connect_timeout,
            read_timeout=settings.rtl_tcp.read_timeout,
        )

    if allow_simulated_fallback:
        logger.warning(
            "No USB dongle (%s) or RTL-TCP server (%s:%d) available — starting Simulated RF mode.",
            detail or "none",
            settings.rtl_tcp.host,
            settings.rtl_tcp.port,
        )
        return SimulatedSource(
            center_freq=rx.frequency,
            sample_rate=rx.sample_rate,
            gain=rx.gain,
            ppm=rx.ppm,
        )

    raise SDRConnectionError(
        f"No USB RTL-SDR device ({detail}) or reachable RTL-TCP server at "
        f"{settings.rtl_tcp.host}:{settings.rtl_tcp.port}."
    )
