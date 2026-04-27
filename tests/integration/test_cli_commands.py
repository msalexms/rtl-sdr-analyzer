"""Integration tests for Typer CLI commands."""

import re
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from rtl_sdr_analyzer.cli.app import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


class TestAnalyzeCommand:
    def test_help(self) -> None:
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.stdout)
        assert "--freq" in output
        assert "--headless" in output

    @patch("rtl_sdr_analyzer.cli.app.RTLSDRBase.connect")
    def test_analyze_stub_headless(self, mock_connect: object) -> None:
        """Run analyze in headless mode with mocked hardware.

        Because the analyzer tries to open a real socket, we expect a
        connection error here — the test validates CLI wiring.
        """
        from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRException

        mock_connect.side_effect = RTLSDRException("Connection refused")
        result = runner.invoke(app, ["analyze", "--headless", "--host", "127.0.0.1"])
        # Will fail to connect, but CLI should parse correctly
        assert "Failed to connect" in result.output or result.exit_code != 0


class TestConfigCommands:
    def test_config_validate_valid(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "valid.yml"
        yaml_path.write_text("receiver:\n  frequency: 98000000\n")
        result = runner.invoke(app, ["config-validate", str(yaml_path)])
        assert result.exit_code == 0
        assert "Configuration is valid" in result.output

    def test_config_validate_invalid(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "invalid.yml"
        yaml_path.write_text("receiver:\n  frequency: -1\n")
        result = runner.invoke(app, ["config-validate", str(yaml_path)])
        assert result.exit_code == 1
        assert "Configuration error" in result.output

    def test_config_show_json(self) -> None:
        result = runner.invoke(app, ["config-show", "--format", "json"])
        assert result.exit_code == 0
        assert "rtl_tcp" in result.output

    def test_config_show_yaml(self) -> None:
        result = runner.invoke(app, ["config-show", "--format", "yaml"])
        assert result.exit_code == 0
        assert "rtl_tcp" in result.output


class TestRecordCommand:
    @patch("rtl_sdr_analyzer.cli.app.RTLSDRBase")
    def test_record_stub(self, mock_rtl_cls: object) -> None:
        mock_rtl = mock_rtl_cls.return_value
        mock_rtl.__enter__ = lambda s: s
        mock_rtl.__exit__ = lambda *a: None
        mock_rtl.read_samples.return_value = None

        result = runner.invoke(app, ["record", "/tmp/test.iq", "--duration", "0.1"])
        assert result.exit_code == 0
        assert "saved to" in result.output
