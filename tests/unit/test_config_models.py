"""Tests for Pydantic configuration models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rtl_sdr_analyzer.config.loader import load_settings
from rtl_sdr_analyzer.config.models import Settings


class TestDefaults:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.rtl_tcp.host == "192.168.31.34"
        assert s.rtl_tcp.port == 1234
        assert s.receiver.frequency == 915e6
        assert s.receiver.sample_rate == 2.048e6
        assert s.receiver.fft_size == 2048
        assert s.detector.power_threshold == -70.0
        assert s.detector.test_mode is False


class TestValidation:
    def test_invalid_port(self) -> None:
        with pytest.raises(ValidationError):
            Settings(rtl_tcp={"host": "localhost", "port": 70000})

    def test_invalid_frequency(self) -> None:
        with pytest.raises(ValidationError):
            Settings(receiver={"frequency": -1})

    def test_fft_size_not_power_of_two(self) -> None:
        with pytest.raises(ValidationError):
            Settings(receiver={"fft_size": 1000})

    def test_negative_bandwidth_threshold(self) -> None:
        with pytest.raises(ValidationError):
            Settings(detector={"bandwidth_threshold": -1})

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(unknown_field=True)


class TestEnvVars:
    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RTL_SDR__RECEIVER__FREQUENCY", "98000000")
        s = load_settings()
        assert s.receiver.frequency == 98e6

    def test_env_nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RTL_SDR__RTL_TCP__PORT", "5678")
        s = load_settings()
        assert s.rtl_tcp.port == 5678

    def test_env_override_priority(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """CLI overrides should take precedence over env vars."""
        monkeypatch.setenv("RTL_SDR__RECEIVER__FREQUENCY", "98000000")
        s = load_settings(cli_overrides={"receiver.frequency": 88e6})
        assert s.receiver.frequency == 88e6


class TestLoader:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "test_config.yml"
        yaml_path.write_text(
            "receiver:\n  frequency: 100000000\ndetector:\n  power_threshold: -60\n"
        )
        s = load_settings(config_path=yaml_path)
        assert s.receiver.frequency == 100e6
        assert s.detector.power_threshold == -60.0

    def test_cli_overrides(self) -> None:
        s = load_settings(cli_overrides={"receiver.frequency": 88e6})
        assert s.receiver.frequency == 88e6

    def test_yaml_and_cli_merge(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "test_config.yml"
        yaml_path.write_text("receiver:\n  frequency: 100000000\n")
        s = load_settings(
            config_path=yaml_path,
            cli_overrides={"detector.power_threshold": -55.0},
        )
        assert s.receiver.frequency == 100e6
        assert s.detector.power_threshold == -55.0
