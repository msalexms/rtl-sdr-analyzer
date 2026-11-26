"""Integration tests for Typer CLI commands."""

import re
from pathlib import Path

from typer.testing import CliRunner

from rtl_sdr_analyzer.cli.app import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])").sub("", text)


class TestCliCommands:
    def test_version_and_help(self) -> None:
        res_v = runner.invoke(app, ["--version"])
        assert res_v.exit_code == 0
        assert "3.0.0" in res_v.output

        res_h = runner.invoke(app, ["serve", "--help"])
        assert res_h.exit_code == 0
        assert "--freq" in _strip_ansi(res_h.output)

    def test_devices_command(self) -> None:
        res = runner.invoke(app, ["devices"])
        assert res.exit_code == 0
        assert "librtlsdr" in _strip_ansi(res.output)

    def test_analyze_simulated_finite_frames(self, tmp_path: Path) -> None:
        db = tmp_path / "cli_events.db"
        csv_path = tmp_path / "cli_events.csv"
        res = runner.invoke(
            app,
            [
                "analyze",
                "--source",
                "simulated",
                "--freq",
                "98.5e6",
                "--max-frames",
                "5",
                "--db-path",
                str(db),
                "--export-format",
                "csv",
                "--export-path",
                str(csv_path),
            ],
        )
        assert res.exit_code == 0
        assert db.exists()

    def test_sweep_and_record_and_stats_simulated(self, tmp_path: Path) -> None:
        db = tmp_path / "sweep.db"
        res_sw = runner.invoke(
            app,
            [
                "sweep",
                "97e6",
                "101e6",
                "--source",
                "simulated",
                "--dwell",
                "0.05",
                "--db-path",
                str(db),
            ],
        )
        assert res_sw.exit_code == 0
        assert "Sweep complete" in _strip_ansi(res_sw.output)

        res_st = runner.invoke(app, ["stats", str(db)])
        assert res_st.exit_code == 0

        iq_out = tmp_path / "cap.npz"
        res_rec = runner.invoke(
            app,
            [
                "record",
                str(iq_out),
                "--source",
                "simulated",
                "--format",
                "numpy",
                "--duration",
                "0.05",
                "--freq",
                "98.5e6",
            ],
        )
        assert res_rec.exit_code == 0
        assert iq_out.exists()

    def test_config_validate_and_show(self, tmp_path: Path) -> None:
        valid_yml = tmp_path / "valid.yml"
        valid_yml.write_text("receiver:\n  frequency: 98000000\n", encoding="utf-8")
        res_ok = runner.invoke(app, ["config-validate", str(valid_yml)])
        assert res_ok.exit_code == 0
        assert "Configuration is valid" in res_ok.output

        bad_yml = tmp_path / "bad.yml"
        bad_yml.write_text("receiver:\n  frequency: -1\n", encoding="utf-8")
        res_bad = runner.invoke(app, ["config-validate", str(bad_yml)])
        assert res_bad.exit_code == 1

        res_show = runner.invoke(app, ["config-show", "--format", "json"])
        assert res_show.exit_code == 0
        assert "rtl_tcp" in res_show.output
