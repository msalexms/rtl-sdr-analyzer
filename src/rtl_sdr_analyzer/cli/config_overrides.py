"""Map flat CLI argument names to nested configuration paths."""

from typing import Any

CLI_TO_CONFIG_PATH: dict[str, str] = {
    "source": "source.mode",
    "device": "source.device_index",
    "lib_path": "source.library_path",
    "replay_path": "source.replay_path",
    "host": "rtl_tcp.host",
    "tcp_host": "rtl_tcp.host",
    "port": "rtl_tcp.port",
    "tcp_port": "rtl_tcp.port",
    "freq": "receiver.frequency",
    "sample_rate": "receiver.sample_rate",
    "fft_size": "receiver.fft_size",
    "gain": "receiver.gain",
    "ppm": "receiver.ppm",
    "direct_sampling": "receiver.direct_sampling",
    "power_threshold": "detector.power_threshold",
    "snr_threshold": "detector.snr_threshold",
    "bandwidth_threshold": "detector.bandwidth_threshold",
    "z_score_threshold": "detector.z_score_threshold",
    "detection_window": "detector.detection_window",
    "min_duration": "detector.min_duration",
    "test_mode": "detector.test_mode",
    "waterfall_length": "display.waterfall_length",
    "target_fps": "display.target_fps",
    "web_host": "web.host",
    "web_port": "web.port",
    "db_path": "storage.db_path",
    "recordings_dir": "storage.recordings_dir",
}


def build_cli_overrides(**kwargs: Any) -> dict[str, Any]:
    """Build a dot-notation override dictionary from flat CLI kwargs."""
    overrides: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is not None and key in CLI_TO_CONFIG_PATH:
            overrides[CLI_TO_CONFIG_PATH[key]] = value
    return overrides
