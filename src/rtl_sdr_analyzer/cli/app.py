"""Typer CLI application for RTL-SDR Analyzer."""

import logging
import os
from pathlib import Path
from typing import Optional

import typer

from rtl_sdr_analyzer.cli.config_overrides import build_cli_overrides
from rtl_sdr_analyzer.config.loader import load_settings
from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase
from rtl_sdr_analyzer.core.signal_processor import SignalProcessor
from rtl_sdr_analyzer.detection.detector import SignalDetector
from rtl_sdr_analyzer.exporters.csv_exporter import CsvExporter
from rtl_sdr_analyzer.exporters.json_exporter import JsonExporter
from rtl_sdr_analyzer.logging_config import setup_logging
from rtl_sdr_analyzer.orchestrator.analyzer import Analyzer
from rtl_sdr_analyzer.orchestrator.event_bus import EventBus
from rtl_sdr_analyzer.visualization.headless import HeadlessVisualization
from rtl_sdr_analyzer.visualization.plotter import MatplotlibVisualization

logger = logging.getLogger(__name__)

app = typer.Typer(name="rtl-sdr-analyzer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _display_available() -> bool:
    """Check if a graphical display is available for matplotlib."""
    # Linux/Unix: check $DISPLAY
    if os.name == "posix" and not os.environ.get("DISPLAY"):
        return False
    # Try importing a GUI backend
    try:
        import matplotlib

        backend = matplotlib.get_backend()
        return backend not in ("agg", "Agg", "pdf", "svg", "ps")
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

_config_option = typer.Option(None, "--config", "-c", help="Path to YAML configuration file")
_log_level_option = typer.Option("INFO", "--log-level", help="Logging level")
_log_format_option = typer.Option("text", "--log-format", help="Log format: text or json")

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def analyze(
    config: Optional[Path] = _config_option,
    host: Optional[str] = typer.Option(None, "--host", help="RTL-TCP server host"),
    port: Optional[int] = typer.Option(None, "--port", help="RTL-TCP server port"),
    freq: Optional[float] = typer.Option(None, "--freq", help="Center frequency in Hz"),
    sample_rate: Optional[float] = typer.Option(None, "--sample-rate", help="Sample rate in Hz"),
    fft_size: Optional[int] = typer.Option(None, "--fft-size", help="FFT size"),
    power_threshold: Optional[float] = typer.Option(None, "--power-threshold", help="Power threshold in dB"),
    bandwidth_threshold: Optional[float] = typer.Option(None, "--bandwidth-threshold", help="Bandwidth threshold in Hz"),
    z_score_threshold: Optional[float] = typer.Option(None, "--z-score-threshold", help="Z-score threshold"),
    detection_window: Optional[int] = typer.Option(None, "--detection-window", help="Detection window size"),
    min_duration: Optional[float] = typer.Option(None, "--min-duration", help="Minimum event duration in seconds"),
    test_mode: bool = typer.Option(False, "--test-mode", help="Enable sensitive test mode"),
    waterfall_length: Optional[int] = typer.Option(None, "--waterfall-length", help="Waterfall history length"),
    update_interval: Optional[int] = typer.Option(None, "--update-interval", help="Display update interval in ms"),
    headless: bool = typer.Option(False, "--headless", help="Run without GUI"),
    export_format: Optional[str] = typer.Option(None, "--export-format", help="Event export format: csv or json"),
    export_path: Optional[Path] = typer.Option(None, "--export-path", help="Path for exported events"),
    log_level: str = _log_level_option,
    log_format: str = _log_format_option,
) -> None:
    """Run real-time spectrum analysis and signal detection."""
    setup_logging(level=log_level, json_format=(log_format == "json"))

    overrides = build_cli_overrides(
        host=host,
        port=port,
        freq=freq,
        sample_rate=sample_rate,
        fft_size=fft_size,
        power_threshold=power_threshold,
        bandwidth_threshold=bandwidth_threshold,
        z_score_threshold=z_score_threshold,
        detection_window=detection_window,
        min_duration=min_duration,
        test_mode=test_mode,
        waterfall_length=waterfall_length,
        update_interval=update_interval,
    )

    settings = load_settings(config_path=config, cli_overrides=overrides)

    # Build components
    rtlsdr = RTLSDRBase(
        host=settings.rtl_tcp.host,
        port=settings.rtl_tcp.port,
        center_freq=settings.receiver.frequency,
        sample_rate=settings.receiver.sample_rate,
        fft_size=settings.receiver.fft_size,
    )
    processor = SignalProcessor(
        fft_size=settings.receiver.fft_size,
        sample_rate=settings.receiver.sample_rate,
    )
    detector = SignalDetector(
        power_threshold=settings.detector.power_threshold,
        bandwidth_threshold=settings.detector.bandwidth_threshold,
        z_score_threshold=settings.detector.z_score_threshold,
        detection_window=settings.detector.detection_window,
        min_duration=settings.detector.min_duration,
        test_mode=settings.detector.test_mode,
    )

    if headless or not _display_available():
        if not headless:
            logger.warning(
                "No graphical display detected — falling back to headless mode. "
                "Install a GUI backend (e.g. PyQt6) or use --headless to suppress this warning."
            )
        visualization = HeadlessVisualization(
            freq_range=rtlsdr.freq_range,
            waterfall_length=settings.display.waterfall_length,
            update_interval=settings.display.update_interval,
        )
    else:
        visualization = MatplotlibVisualization(
            freq_range=rtlsdr.freq_range,
            waterfall_length=settings.display.waterfall_length,
            update_interval=settings.display.update_interval,
        )

    event_bus = EventBus()

    if export_format and not export_path:
        typer.echo("--export-path is required when --export-format is set", err=True)
        raise typer.Exit(1)

    if export_path and not export_format:
        typer.echo("--export-format is required when --export-path is set", err=True)
        raise typer.Exit(1)

    if export_format and export_path:
        if export_format.lower() == "csv":
            exporter = CsvExporter(output_path=export_path)
        elif export_format.lower() == "json":
            exporter = JsonExporter(output_path=export_path)
        else:
            typer.echo(f"Unknown export format: {export_format}", err=True)
            raise typer.Exit(1)
        event_bus.subscribe(exporter.export)

    analyzer = Analyzer(
        rtlsdr=rtlsdr,
        processor=processor,
        detector=detector,
        visualization=visualization,
        event_bus=event_bus,
    )

    if export_format and export_path:
        analyzer.add_exporter(exporter)

    try:
        analyzer.start()
    finally:
        logger.info("Exiting rtl-sdr-analyzer.")


@app.command()
def record(
    output: Path = typer.Argument(..., help="Output file path for IQ samples"),
    duration: float = typer.Option(10.0, "--duration", help="Recording duration in seconds"),
    config: Optional[Path] = _config_option,
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
    freq: Optional[float] = typer.Option(None, "--freq"),
    sample_rate: Optional[float] = typer.Option(None, "--sample-rate"),
    fft_size: Optional[int] = typer.Option(None, "--fft-size"),
    log_level: str = _log_level_option,
) -> None:
    """Record raw IQ samples to a file."""
    setup_logging(level=log_level)
    typer.echo(f"Recording {duration}s of IQ data to {output} ...")
    typer.echo("(Not yet implemented — stub for Phase 8+)")


@app.command(name="config-validate")
def config_validate(
    config_path: Path = typer.Argument(..., help="Path to YAML configuration file"),
) -> None:
    """Validate a configuration file against the schema."""
    try:
        settings = load_settings(config_path=config_path)
        typer.echo("Configuration is valid.")
        typer.echo(settings.model_dump_json(indent=2))
    except Exception as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="config-show")
def config_show(
    config: Optional[Path] = _config_option,
    format: str = typer.Option("yaml", "--format", help="Output format: yaml or json"),
) -> None:
    """Show the resolved configuration (defaults + env + file + CLI)."""
    settings = load_settings(config_path=config)
    if format.lower() == "json":
        typer.echo(settings.model_dump_json(indent=2))
    else:
        import yaml
        typer.echo(yaml.safe_dump(settings.model_dump(), sort_keys=False))


if __name__ == "__main__":
    app()
