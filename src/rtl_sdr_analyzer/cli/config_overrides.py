"""Map flat CLI argument names to nested configuration paths."""

from typing import Any

CLI_TO_CONFIG_PATH: dict[str, str] = {
    "host": "rtl_tcp.host",
    "port": "rtl_tcp.port",
    "freq": "receiver.frequency",
    "sample_rate": "receiver.sample_rate",
    "fft_size": "receiver.fft_size",
    "power_threshold": "detector.power_threshold",
    "bandwidth_threshold": "detector.bandwidth_threshold",
    "z_score_threshold": "detector.z_score_threshold",
    "detection_window": "detector.detection_window",
    "min_duration": "detector.min_duration",
    "test_mode": "detector.test_mode",
    "waterfall_length": "display.waterfall_length",
    "update_interval": "display.update_interval",
}


def build_cli_overrides(**kwargs: Any) -> dict[str, Any]:
    """Build a dot-notation override dict from flat CLI kwargs.

    Only includes keys whose value is not None and are known config paths.
    """
    overrides: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is not None and key in CLI_TO_CONFIG_PATH:
            overrides[CLI_TO_CONFIG_PATH[key]] = value
    return overrides
