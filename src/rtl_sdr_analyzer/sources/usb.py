"""Direct USB RTL-SDR source using ctypes bindings to librtlsdr."""

import contextlib
import ctypes
import ctypes.util
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

from .base import (
    DeviceInfo,
    SDRConfigurationError,
    SDRConnectionError,
    SDRDisconnectedError,
    SDRLibraryNotFoundError,
    TunerType,
    uint8_iq_to_complex64,
)

logger = logging.getLogger(__name__)

# Keep Windows DLL directory handles alive for process lifetime
_WIN_DLL_HANDLES: list[Any] = []
_LIB_LOCK = threading.Lock()
_LOADED_LIBS: dict[str, tuple[ctypes.CDLL, Path]] = {}


def _candidate_library_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("rtlsdr.dll", "librtlsdr.dll")
    if sys.platform == "darwin":
        return ("librtlsdr.dylib", "librtlsdr.0.dylib")
    return ("librtlsdr.so.0", "librtlsdr.so")


def find_librtlsdr(explicit_path: str | None = None) -> Path | None:
    """Locate ``librtlsdr`` shared library across standard and bundle paths."""
    names = _candidate_library_names()

    def _resolve_candidate(raw_path: str | Path) -> Path | None:
        p = Path(raw_path).expanduser()
        if p.is_file():
            return p.resolve()
        if p.is_dir():
            for name in names:
                cand = p / name
                if cand.is_file():
                    return cand.resolve()
        return None

    # 1. Explicit argument or RTL_SDR_LIB environment variable
    for raw in (explicit_path, os.environ.get("RTL_SDR_LIB")):
        if raw:
            found = _resolve_candidate(raw)
            if found is not None:
                return found

    # 2. System loader / PATH lookup
    which_lib = ctypes.util.find_library("rtlsdr")
    if which_lib:
        p = Path(which_lib)
        if p.is_file():
            return p.resolve()
        return p

    # 3. Project-local libs directory
    project_libs = Path.cwd() / "libs"
    if project_libs.is_dir():
        found = _resolve_candidate(project_libs)
        if found is not None:
            return found

    # 4. Platform-specific common directories
    search_dirs: list[Path] = []
    if sys.platform == "win32":
        search_dirs.extend(
            [
                Path(r"C:\Program Files\rtl-sdr"),
                Path(r"C:\Program Files (x86)\rtl-sdr"),
                Path(os.environ.get("LOCALAPPDATA", "")) / "rtl-sdr",
                Path.home() / "rtl-sdr",
            ]
        )
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            for pattern in ("sdrpp*", "rtl-sdr*", "rtlsdr*"):
                for entry in sorted(downloads.glob(pattern)):
                    if entry.is_dir():
                        search_dirs.append(entry)
                        for sub in entry.iterdir():
                            if sub.is_dir():
                                search_dirs.append(sub)
    elif sys.platform == "darwin":
        search_dirs.extend(
            [
                Path("/opt/homebrew/lib"),
                Path("/usr/local/lib"),
            ]
        )
    else:
        search_dirs.extend(
            [
                Path("/usr/local/lib"),
                Path("/usr/lib/x86_64-linux-gnu"),
                Path("/usr/lib/aarch64-linux-gnu"),
                Path("/usr/lib"),
            ]
        )

    for directory in search_dirs:
        if directory.is_dir():
            found = _resolve_candidate(directory)
            if found is not None:
                return found

    return None


def _configure_prototypes(lib: ctypes.CDLL) -> None:
    c_void_p = ctypes.c_void_p
    c_int = ctypes.c_int
    c_uint = ctypes.c_uint32
    c_char_p = ctypes.c_char_p

    lib.rtlsdr_get_device_count.argtypes = []
    lib.rtlsdr_get_device_count.restype = c_uint

    lib.rtlsdr_get_device_name.argtypes = [c_uint]
    lib.rtlsdr_get_device_name.restype = c_char_p

    lib.rtlsdr_get_device_usb_strings.argtypes = [c_uint, c_char_p, c_char_p, c_char_p]
    lib.rtlsdr_get_device_usb_strings.restype = c_int

    lib.rtlsdr_open.argtypes = [ctypes.POINTER(c_void_p), c_uint]
    lib.rtlsdr_open.restype = c_int

    lib.rtlsdr_close.argtypes = [c_void_p]
    lib.rtlsdr_close.restype = c_int

    lib.rtlsdr_get_tuner_type.argtypes = [c_void_p]
    lib.rtlsdr_get_tuner_type.restype = c_int

    lib.rtlsdr_get_tuner_gains.argtypes = [c_void_p, ctypes.POINTER(c_int)]
    lib.rtlsdr_get_tuner_gains.restype = c_int

    lib.rtlsdr_set_center_freq.argtypes = [c_void_p, c_uint]
    lib.rtlsdr_set_center_freq.restype = c_int

    lib.rtlsdr_get_center_freq.argtypes = [c_void_p]
    lib.rtlsdr_get_center_freq.restype = c_uint

    lib.rtlsdr_set_sample_rate.argtypes = [c_void_p, c_uint]
    lib.rtlsdr_set_sample_rate.restype = c_int

    lib.rtlsdr_get_sample_rate.argtypes = [c_void_p]
    lib.rtlsdr_get_sample_rate.restype = c_uint

    lib.rtlsdr_set_tuner_gain_mode.argtypes = [c_void_p, c_int]
    lib.rtlsdr_set_tuner_gain_mode.restype = c_int

    lib.rtlsdr_set_tuner_gain.argtypes = [c_void_p, c_int]
    lib.rtlsdr_set_tuner_gain.restype = c_int

    lib.rtlsdr_set_freq_correction.argtypes = [c_void_p, c_int]
    lib.rtlsdr_set_freq_correction.restype = c_int

    lib.rtlsdr_set_agc_mode.argtypes = [c_void_p, c_int]
    lib.rtlsdr_set_agc_mode.restype = c_int

    lib.rtlsdr_set_direct_sampling.argtypes = [c_void_p, c_int]
    lib.rtlsdr_set_direct_sampling.restype = c_int

    lib.rtlsdr_reset_buffer.argtypes = [c_void_p]
    lib.rtlsdr_reset_buffer.restype = c_int

    lib.rtlsdr_read_sync.argtypes = [
        c_void_p,
        ctypes.c_void_p,
        c_int,
        ctypes.POINTER(c_int),
    ]
    lib.rtlsdr_read_sync.restype = c_int


def _load_librtlsdr(library_path: str | None = None) -> tuple[ctypes.CDLL, Path]:
    resolved = find_librtlsdr(library_path)
    if resolved is None:
        raise SDRLibraryNotFoundError(
            "Could not locate librtlsdr (rtlsdr.dll / librtlsdr.so / librtlsdr.dylib). "
            "Install rtl-sdr or set RTL_SDR_LIB / --lib-path, or use --source simulated."
        )

    cache_key = str(resolved)
    with _LIB_LOCK:
        if cache_key in _LOADED_LIBS:
            return _LOADED_LIBS[cache_key]

        if sys.platform == "win32" and resolved.parent.is_dir():
            handle = os.add_dll_directory(str(resolved.parent))
            _WIN_DLL_HANDLES.append(handle)

        try:
            lib = ctypes.CDLL(str(resolved))
        except OSError as exc:
            raise SDRLibraryNotFoundError(
                f"Failed to load librtlsdr from {resolved}: {exc}"
            ) from exc

        _configure_prototypes(lib)
        _LOADED_LIBS[cache_key] = (lib, resolved)
        return lib, resolved


def enumerate_usb_devices(library_path: str | None = None) -> tuple[list[DeviceInfo], str | None]:
    """Enumerate attached USB RTL-SDR dongles.

    Returns:
        Tuple of ``(devices, detail_or_error)`` where ``detail_or_error`` is
        the resolved library path on success or a human-readable diagnostic on failure.
    """
    try:
        lib, resolved = _load_librtlsdr(library_path)
    except SDRLibraryNotFoundError as exc:
        return [], str(exc)

    count = int(lib.rtlsdr_get_device_count())
    devices: list[DeviceInfo] = []
    for idx in range(count):
        raw_name = lib.rtlsdr_get_device_name(idx)
        name = raw_name.decode("utf-8", errors="replace") if raw_name else f"RTL-SDR #{idx}"

        manufact_buf = ctypes.create_string_buffer(256)
        product_buf = ctypes.create_string_buffer(256)
        serial_buf = ctypes.create_string_buffer(256)
        manufacturer = ""
        product = ""
        serial = ""
        if lib.rtlsdr_get_device_usb_strings(idx, manufact_buf, product_buf, serial_buf) == 0:
            manufacturer = manufact_buf.value.decode("utf-8", errors="replace").strip()
            product = product_buf.value.decode("utf-8", errors="replace").strip()
            serial = serial_buf.value.decode("utf-8", errors="replace").strip()

        devices.append(
            DeviceInfo(
                index=idx,
                name=name,
                source_type="usb",
                manufacturer=manufacturer,
                product=product,
                serial=serial,
                connected=False,
                detail=str(resolved),
            )
        )
    return devices, str(resolved)


def get_usb_diagnostics(library_path: str | None = None) -> dict[str, Any]:
    """Return structured USB & librtlsdr diagnostic info for CLI and UI."""
    devices, detail = enumerate_usb_devices(library_path)
    lib_found = find_librtlsdr(library_path)
    return {
        "library_found": lib_found is not None,
        "library_path": str(lib_found) if lib_found else None,
        "device_count": len(devices),
        "devices": [d.model_dump() for d in devices],
        "message": detail,
    }


class LocalUsbSource:
    """Direct USB RTL-SDR IQ source backed by ``librtlsdr`` via ``ctypes``."""

    source_type: str = "usb"

    def __init__(
        self,
        device_index: int = 0,
        center_freq: float = 98.0e6,
        sample_rate: float = 2.048e6,
        gain: float | None = None,
        ppm: int = 0,
        direct_sampling: int = 0,
        agc: bool = False,
        library_path: str | None = None,
    ) -> None:
        self.device_index = device_index
        self.center_freq = float(center_freq)
        self.sample_rate = float(sample_rate)
        self.gain = gain
        self.ppm = int(ppm)
        self.direct_sampling = int(direct_sampling)
        self.agc = bool(agc)
        self.library_path = library_path

        self._lock = threading.RLock()
        self._lib: ctypes.CDLL | None = None
        self._lib_path: Path | None = None
        self._dev: ctypes.c_void_p | None = None
        self._carry: np.ndarray = np.empty(0, dtype=np.complex64)
        self._supported_gains: list[float] = []
        self._info = DeviceInfo(
            index=device_index,
            name=f"USB RTL-SDR #{device_index}",
            source_type="usb",
        )

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._dev is not None

    @property
    def info(self) -> DeviceInfo:
        with self._lock:
            return self._info.model_copy()

    def __enter__(self) -> "LocalUsbSource":
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
        """Open the USB RTL-SDR device and apply initial configuration."""
        with self._lock:
            if self._dev is not None:
                return
            self._open_handle_unlocked()

    def _open_handle_unlocked(self) -> None:
        lib, resolved = _load_librtlsdr(self.library_path)
        self._lib = lib
        self._lib_path = resolved

        count = int(lib.rtlsdr_get_device_count())
        if count <= 0:
            raise SDRConnectionError(
                "No USB RTL-SDR devices found. Check USB cable and WinUSB/libusb driver."
            )
        if self.device_index >= count:
            raise SDRConnectionError(
                f"USB device index {self.device_index} out of range (found {count} device(s))."
            )

        dev = ctypes.c_void_p()
        rc = lib.rtlsdr_open(ctypes.byref(dev), self.device_index)
        if rc != 0 or not dev.value:
            raise SDRConnectionError(
                f"Failed to open USB RTL-SDR device #{self.device_index} (error {rc}). "
                "Close other SDR software (SDR++, SDR#, rtl_tcp) if open."
            )

        self._dev = dev
        try:
            raw_name = lib.rtlsdr_get_device_name(self.device_index)
            name = (
                raw_name.decode("utf-8", errors="replace")
                if raw_name
                else f"RTL-SDR #{self.device_index}"
            )
            tuner_code = int(lib.rtlsdr_get_tuner_type(dev))
            tuner = TunerType.label(tuner_code)
            gains = self._query_tuner_gains(lib, dev)
            self._supported_gains = gains

            self._apply_initial_config(lib, dev)

            self._info = DeviceInfo(
                index=self.device_index,
                name=name,
                source_type="usb",
                tuner=tuner,
                supported_gains=gains,
                connected=True,
                detail=str(resolved),
            )
            logger.info(
                "Opened USB RTL-SDR #%d (%s, tuner=%s, freq=%.3f MHz, sr=%.3f MSPS)",
                self.device_index,
                name,
                tuner,
                self.center_freq / 1e6,
                self.sample_rate / 1e6,
            )
        except Exception:
            self.close()
            raise

    def _query_tuner_gains(self, lib: ctypes.CDLL, dev: ctypes.c_void_p) -> list[float]:
        n_gains = int(lib.rtlsdr_get_tuner_gains(dev, None))
        if n_gains <= 0:
            return []
        arr = (ctypes.c_int * n_gains)()
        actual = int(lib.rtlsdr_get_tuner_gains(dev, arr))
        return [round(arr[i] / 10.0, 1) for i in range(max(0, actual))]

    def _apply_initial_config(self, lib: ctypes.CDLL, dev: ctypes.c_void_p) -> None:
        if lib.rtlsdr_set_direct_sampling(dev, self.direct_sampling) != 0:
            raise SDRConfigurationError(
                f"Failed to set direct sampling mode={self.direct_sampling}"
            )
        if lib.rtlsdr_set_agc_mode(dev, 1 if self.agc else 0) != 0:
            raise SDRConfigurationError(f"Failed to set AGC mode={self.agc}")
        if lib.rtlsdr_set_center_freq(dev, int(round(self.center_freq))) != 0:
            raise SDRConfigurationError(f"Failed to set center freq={self.center_freq}")
        if lib.rtlsdr_set_sample_rate(dev, int(round(self.sample_rate))) != 0:
            raise SDRConfigurationError(f"Failed to set sample rate={self.sample_rate}")
        self._apply_gain_unlocked(lib, dev, self.gain)
        if self.ppm != 0:
            rc_ppm = lib.rtlsdr_set_freq_correction(dev, self.ppm)
            if rc_ppm not in (0, -2):
                raise SDRConfigurationError(f"Failed to set PPM correction={self.ppm}")

        self._carry = np.empty(0, dtype=np.complex64)
        if lib.rtlsdr_reset_buffer(dev) != 0:
            raise SDRConfigurationError("Failed to reset USB sample buffer")

        # Discard initial transient block
        self._discard_raw_block(lib, dev, 16384)

    def _apply_gain_unlocked(
        self, lib: ctypes.CDLL, dev: ctypes.c_void_p, gain_db: float | None
    ) -> None:
        if gain_db is None:
            if lib.rtlsdr_set_tuner_gain_mode(dev, 0) != 0:
                raise SDRConfigurationError("Failed to enable auto gain")
            self.gain = None
            return

        if lib.rtlsdr_set_tuner_gain_mode(dev, 1) != 0:
            raise SDRConfigurationError("Failed to enable manual gain mode")

        target = float(gain_db)
        if self._supported_gains:
            target = min(self._supported_gains, key=lambda g: abs(g - target))

        tenths = int(round(target * 10.0))
        if lib.rtlsdr_set_tuner_gain(dev, tenths) != 0:
            raise SDRConfigurationError(f"Failed to set tuner gain to {target} dB")
        self.gain = target

    def _discard_raw_block(self, lib: ctypes.CDLL, dev: ctypes.c_void_p, n_bytes: int) -> None:
        aligned = max(512, ((n_bytes + 511) // 512) * 512)
        buf = (ctypes.c_ubyte * aligned)()
        n_read = ctypes.c_int()
        lib.rtlsdr_read_sync(dev, buf, aligned, ctypes.byref(n_read))

    def _reopen_unlocked(self) -> None:
        if self._dev is not None and self._lib is not None:
            with contextlib.suppress(Exception):
                self._lib.rtlsdr_reset_buffer(self._dev)
            with contextlib.suppress(Exception):
                self._lib.rtlsdr_close(self._dev)
        self._dev = None
        self._carry = np.empty(0, dtype=np.complex64)
        time.sleep(0.05)
        self._open_handle_unlocked()

    def _call_ctrl_with_recovery(
        self,
        label: str,
        fn: Callable[[ctypes.CDLL, ctypes.c_void_p], int],
        *,
        accepted_codes: tuple[int, ...] = (0,),
        allow_reopen: bool = True,
    ) -> None:
        if self._dev is None or self._lib is None:
            raise SDRDisconnectedError("USB RTL-SDR device is not open")

        # Flush stale bulk IN pipe before I2C/demod control transfers (prevents WinUSB -9 stall)
        self._carry = np.empty(0, dtype=np.complex64)
        self._lib.rtlsdr_reset_buffer(self._dev)
        rc = int(fn(self._lib, self._dev))
        if rc in accepted_codes:
            return

        for attempt in range(1, 3):
            time.sleep(0.025)
            self._lib.rtlsdr_reset_buffer(self._dev)
            rc = int(fn(self._lib, self._dev))
            if rc in accepted_codes:
                logger.info(
                    "USB control '%s' recovered after reset/retry #%d",
                    label,
                    attempt,
                )
                return

        if allow_reopen:
            logger.warning("USB control '%s' failed (rc=%d); reopening USB handle", label, rc)
            self._reopen_unlocked()
            if self._dev is not None and self._lib is not None:
                self._lib.rtlsdr_reset_buffer(self._dev)
                rc = int(fn(self._lib, self._dev))
                if rc in accepted_codes:
                    logger.info("USB control '%s' recovered after USB reopen", label)
                    return

        raise SDRConfigurationError(f"Failed to {label} (rc={rc})")

    def close(self) -> None:
        """Close the USB device handle safely."""
        with self._lock:
            if self._dev is not None and self._lib is not None:
                with contextlib.suppress(Exception):
                    self._lib.rtlsdr_reset_buffer(self._dev)
                try:
                    self._lib.rtlsdr_close(self._dev)
                    logger.info("Closed USB RTL-SDR device #%d", self.device_index)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error closing USB device: %s", exc)
            self._dev = None
            self._carry = np.empty(0, dtype=np.complex64)
            self._info = self._info.model_copy(update={"connected": False})

    def read_samples(self, num_samples: int) -> np.ndarray:
        """Read ``num_samples`` normalized ``complex64`` IQ samples synchronously."""
        if num_samples <= 0:
            return np.empty(0, dtype=np.complex64)

        with self._lock:
            if self._dev is None or self._lib is None:
                raise SDRDisconnectedError("USB RTL-SDR device is not open")

            chunks: list[np.ndarray] = []
            collected = len(self._carry)
            if collected > 0:
                chunks.append(self._carry)
                self._carry = np.empty(0, dtype=np.complex64)

            while collected < num_samples:
                missing_bytes = (num_samples - collected) * 2
                # librtlsdr requires lengths that are multiples of 512 bytes
                read_bytes = max(16384, ((missing_bytes + 511) // 512) * 512)
                buf = (ctypes.c_ubyte * read_bytes)()
                n_read = ctypes.c_int()
                rc = self._lib.rtlsdr_read_sync(self._dev, buf, read_bytes, ctypes.byref(n_read))
                if rc != 0 or n_read.value <= 0:
                    logger.warning(
                        "USB RTL-SDR read stalled (rc=%s, bytes=%s); resetting buffer",
                        rc,
                        n_read.value,
                    )
                    self._lib.rtlsdr_reset_buffer(self._dev)
                    time.sleep(0.01)
                    n_read.value = 0
                    rc = self._lib.rtlsdr_read_sync(
                        self._dev, buf, read_bytes, ctypes.byref(n_read)
                    )
                    if rc != 0 or n_read.value <= 0:
                        raise SDRDisconnectedError(
                            f"USB RTL-SDR read failed (rc={rc}, bytes={n_read.value})"
                        )
                iq = uint8_iq_to_complex64(memoryview(buf)[: n_read.value])
                if len(iq) > 0:
                    chunks.append(iq)
                    collected += len(iq)

            merged = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
            out = merged[:num_samples]
            if len(merged) > num_samples:
                self._carry = merged[num_samples:]
            return out

    def set_center_freq(self, freq_hz: float) -> None:
        """Tune the USB device to ``freq_hz``."""
        with self._lock:
            hz = int(round(freq_hz))
            self._call_ctrl_with_recovery(
                f"tune to {freq_hz:.0f} Hz",
                lambda lib, dev: int(lib.rtlsdr_set_center_freq(dev, hz)),
            )
            self.center_freq = float(freq_hz)

    def set_sample_rate(self, rate_hz: float) -> None:
        """Update the USB device sample rate in Hz."""
        with self._lock:
            sr = int(round(rate_hz))
            self._call_ctrl_with_recovery(
                f"set sample rate {rate_hz:.0f} Hz",
                lambda lib, dev: int(lib.rtlsdr_set_sample_rate(dev, sr)),
            )
            self.sample_rate = float(rate_hz)

    def set_gain(self, gain_db: float | None) -> None:
        """Set manual gain in dB (snapped to tuner table) or auto gain when ``None``."""
        with self._lock:
            if gain_db is None:
                self._call_ctrl_with_recovery(
                    "enable auto gain",
                    lambda lib, dev: int(lib.rtlsdr_set_tuner_gain_mode(dev, 0)),
                )
                self.gain = None
                return

            target = float(gain_db)
            if self._supported_gains:
                target = min(self._supported_gains, key=lambda g: abs(g - target))
            tenths = int(round(target * 10.0))

            def _apply_manual(lib: ctypes.CDLL, dev: ctypes.c_void_p) -> int:
                rc_mode = int(lib.rtlsdr_set_tuner_gain_mode(dev, 1))
                if rc_mode != 0:
                    return rc_mode
                return int(lib.rtlsdr_set_tuner_gain(dev, tenths))

            self._call_ctrl_with_recovery(f"set tuner gain to {target} dB", _apply_manual)
            self.gain = target

    def set_ppm(self, ppm: int) -> None:
        """Set crystal frequency correction in ppm."""
        with self._lock:
            if self._dev is None or self._lib is None:
                raise SDRDisconnectedError("USB RTL-SDR device is not open")
            target_ppm = int(ppm)
            if target_ppm == self.ppm:
                return
            self._call_ctrl_with_recovery(
                f"set PPM to {target_ppm}",
                lambda lib, dev: int(lib.rtlsdr_set_freq_correction(dev, target_ppm)),
                accepted_codes=(0, -2),
            )
            self.ppm = target_ppm

    def flush_buffer(self, discard_samples: int = 16384) -> None:
        """Reset USB ring buffer and discard transient samples after retuning."""
        with self._lock:
            if self._dev is None or self._lib is None:
                return
            self._carry = np.empty(0, dtype=np.complex64)
            self._lib.rtlsdr_reset_buffer(self._dev)
            if discard_samples > 0:
                self._discard_raw_block(self._lib, self._dev, discard_samples * 2)
