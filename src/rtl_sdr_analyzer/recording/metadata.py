"""Recording metadata: JSON sidecars for raw IQ files and lightweight file inspection."""

import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

IQ_SUFFIXES: frozenset[str] = frozenset({".raw", ".cu8", ".npz"})
_FREQ_IN_NAME = re.compile(r"(\d+(?:\.\d+)?)MHz", re.IGNORECASE)


def sidecar_path(iq_path: Path) -> Path:
    """``capture.raw`` -> ``capture.raw.json``."""
    return iq_path.with_name(iq_path.name + ".json")


def write_sidecar(
    iq_path: Path,
    *,
    center_freq_hz: float,
    sample_rate_hz: float,
    gain_db: float | None,
    samples: int,
) -> None:
    """Persist capture parameters next to a raw IQ file (raw files carry no header)."""
    payload = {
        "format": "cu8",
        "center_freq_hz": center_freq_hz,
        "sample_rate_hz": sample_rate_hz,
        "gain_db": gain_db,
        "samples": samples,
    }
    try:
        sidecar_path(iq_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write metadata sidecar for %s: %s", iq_path, exc)


def read_metadata(iq_path: Path) -> dict[str, float | None]:
    """Best-effort ``center_freq_hz`` / ``sample_rate_hz`` for an IQ file.

    Sources, in order: ``.npz`` arrays, JSON sidecar, ``<freq>MHz`` in the filename.
    Missing values are ``None``.
    """
    meta: dict[str, float | None] = {"center_freq_hz": None, "sample_rate_hz": None}
    if iq_path.suffix.lower() == ".npz":
        try:
            with np.load(iq_path) as archive:
                for key, field in (
                    ("center_freq", "center_freq_hz"),
                    ("sample_rate", "sample_rate_hz"),
                ):
                    if key in archive.files and float(archive[key]) > 0:
                        meta[field] = float(archive[key])
        except (OSError, ValueError) as exc:
            logger.debug("Unreadable npz metadata %s: %s", iq_path, exc)
        return meta

    side = sidecar_path(iq_path)
    if side.is_file():
        try:
            data: dict[str, Any] = json.loads(side.read_text(encoding="utf-8"))
            for field in ("center_freq_hz", "sample_rate_hz"):
                value = data.get(field)
                if isinstance(value, int | float) and value > 0:
                    meta[field] = float(value)
        except (OSError, ValueError) as exc:
            logger.debug("Unreadable sidecar %s: %s", side, exc)

    if meta["center_freq_hz"] is None:
        match = _FREQ_IN_NAME.search(iq_path.stem)
        if match:
            meta["center_freq_hz"] = float(match.group(1)) * 1e6
    return meta
