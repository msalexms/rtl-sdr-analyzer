"""Entry point for standalone (PyInstaller) builds."""

from rtl_sdr_analyzer.cli.app import app

if __name__ == "__main__":
    app(prog_name="rtl-sdr-analyzer")
