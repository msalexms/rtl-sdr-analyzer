"""Unit tests for configuration models and hierarchical loader."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rtl_sdr_analyzer.config.loader import load_settings
from rtl_sdr_analyzer.config.models import Settings


class TestConfigDefaults:
    def test_safe_defaults(self) -> None:
        s = Settings()
        assert s.source.mode == "auto"
        assert s.source.device_index == 0
        assert s.rtl_tcp.host == "127.0.0.1"
        assert s.rtl_tcp.port == 1234
        assert s.receiver.frequency == 98.0e6
        assert s.receiver.sample_rate == 2.048e6
        assert s.receiver.fft_size == 2048
        assert s.receiver.gain is None
        assert s.receiver.direct_sampling == 0
        assert s.dsp.window == "blackmanharris"
        assert s.detector.enabled is True
        assert s.web.host == "127.0.0.1"
        assert s.web.port == 8080


class TestConfigValidation:
    def test_invalid_port_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(rtl_tcp={"host": "127.0.0.1", "port": 70000})

    def test_invalid_fft_size_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(receiver={"fft_size": 1000})

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(unknown_section=True)  # type: ignore[call-arg]

    def test_missing_explicit_config_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_settings(config_path=tmp_path / "missing.yml")


class TestConfigPrecedenceAndEnvCoercion:
    def test_numeric_zero_env_stays_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RTL_SDR__SOURCE__DEVICE_INDEX", "0")
        monkeypatch.setenv("RTL_SDR__RECEIVER__DIRECT_SAMPLING", "0")
        monkeypatch.setenv("RTL_SDR__RECEIVER__PPM", "-5")
        monkeypatch.setenv("RTL_SDR__DETECTOR__TEST_MODE", "true")

        s = load_settings()
        assert s.source.device_index == 0
        assert type(s.source.device_index) is int
        assert s.receiver.direct_sampling == 0
        assert s.receiver.ppm == -5
        assert s.detector.test_mode is True

    def test_yaml_env_cli_precedence(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "source:\n  mode: rtl_tcp\nreceiver:\n  frequency: 100000000\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("RTL_SDR__RECEIVER__FREQUENCY", "145000000")
        s = load_settings(
            config_path=cfg,
            cli_overrides={"receiver.frequency": 446.0e6},
        )
        assert s.source.mode == "rtl_tcp"
        assert s.receiver.frequency == 446.0e6
