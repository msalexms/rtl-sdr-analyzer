"""Typer CLI application for RTL-SDR Analyzer."""

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import typer

from rtl_sdr_analyzer.cli.config_overrides import build_cli_overrides
from rtl_sdr_analyzer.config.loader import load_settings
from rtl_sdr_analyzer.core.rtlsdr_base import RTLSDRBase
from rtl_sdr_analyzer.core.signal_processor import SignalProcessor
from rtl_sdr_analyzer.detection.detector import SignalDetector
from rtl_sdr_analyzer.detection.events import JammingEvent
from rtl_sdr_analyzer.exporters.csv_exporter import CsvExporter
from rtl_sdr_analyzer.exporters.json_exporter import JsonExporter
from rtl_sdr_analyzer.logging_config import setup_logging
from rtl_sdr_analyzer.orchestrator.analyzer import Analyzer
from rtl_sdr_analyzer.orchestrator.event_bus import EventBus
from rtl_sdr_analyzer.recording.recorder import IQRecorder
from rtl_sdr_analyzer.storage.database import EventStore
from rtl_sdr_analyzer.storage.stats import StatsDashboard
from rtl_sdr_analyzer.visualization.headless import HeadlessVisualization
from rtl_sdr_analyzer.visualization.plotter import MatplotlibVisualization

logger = logging.getLogger(__name__)

app = typer.Typer(name="rtl-sdr-analyzer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _display_available() -> bool:
    """Check if a graphical display is available for matplotlib."""
    if os.name == "posix" and not os.environ.get("DISPLAY"):
        return False
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
    db_path: Optional[Path] = typer.Option(None, "--db-path", help="SQLite database path for event storage"),
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
        visualization: Any = HeadlessVisualization(
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

    # Validate export args
    if export_format and not export_path:
        typer.echo("--export-path is required when --export-format is set", err=True)
        raise typer.Exit(1)
    if export_path and not export_format:
        typer.echo("--export-format is required when --export-path is set", err=True)
        raise typer.Exit(1)

    # Setup file exporters
    exporter: Optional[Any] = None
    if export_format and export_path:
        if export_format.lower() == "csv":
            exporter = CsvExporter(output_path=export_path)
        elif export_format.lower() == "json":
            exporter = JsonExporter(output_path=export_path)
        else:
            typer.echo(f"Unknown export format: {export_format}", err=True)
            raise typer.Exit(1)
        event_bus.subscribe(exporter.export)

    # Setup SQLite storage
    store: Optional[EventStore] = None
    if db_path:
        store = EventStore(db_path)
        store.init_schema()
        store.start_session(
            center_freq_mhz=settings.receiver.frequency / 1e6,
            sample_rate_hz=settings.receiver.sample_rate,
        )

        def save_to_db(event: JammingEvent) -> None:
            if store:
                store.insert_event(event)

        event_bus.subscribe(save_to_db)
        logger.info("SQLite storage enabled: %s", db_path)

    analyzer = Analyzer(
        rtlsdr=rtlsdr,
        processor=processor,
        detector=detector,
        visualization=visualization,
        event_bus=event_bus,
    )

    if exporter is not None:
        analyzer.add_exporter(exporter)

    try:
        analyzer.start()
    finally:
        if store:
            store.end_session(total_events=store.get_event_count())
        logger.info("Exiting rtl-sdr-analyzer.")


@app.command()
def record(
    output: Path = typer.Argument(..., help="Output file path for IQ samples"),
    duration: float = typer.Option(10.0, "--duration", help="Recording duration in seconds"),
    format: str = typer.Option("raw", "--format", help="Output format: raw or numpy"),
    config: Optional[Path] = _config_option,
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
    freq: Optional[float] = typer.Option(None, "--freq"),
    sample_rate: Optional[float] = typer.Option(None, "--sample-rate"),
    log_level: str = _log_level_option,
) -> None:
    """Record raw IQ samples to a file for offline analysis."""
    setup_logging(level=log_level)

    overrides = build_cli_overrides(host=host, port=port, freq=freq, sample_rate=sample_rate)
    settings = load_settings(config_path=config, cli_overrides=overrides)

    rtlsdr = RTLSDRBase(
        host=settings.rtl_tcp.host,
        port=settings.rtl_tcp.port,
        center_freq=settings.receiver.frequency,
        sample_rate=settings.receiver.sample_rate,
        fft_size=settings.receiver.fft_size,
    )

    try:
        with rtlsdr:
            recorder = IQRecorder(output_path=output, format=format)
            with recorder:
                recorder.record(rtlsdr, duration=duration)
    except KeyboardInterrupt:
        logger.info("Recording interrupted.")
    except Exception as exc:
        logger.error("Recording failed: %s", exc)
        raise typer.Exit(1)

    typer.echo(f"Recording saved to {output}")


@app.command()
def sweep(
    start_freq: float = typer.Argument(..., help="Start frequency in Hz"),
    end_freq: float = typer.Argument(..., help="End frequency in Hz"),
    step: float = typer.Option(1e6, "--step", help="Frequency step in Hz"),
    dwell: float = typer.Option(2.0, "--dwell", help="Dwell time per frequency in seconds"),
    config: Optional[Path] = _config_option,
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
    sample_rate: Optional[float] = typer.Option(None, "--sample-rate"),
    fft_size: Optional[int] = typer.Option(None, "--fft-size"),
    power_threshold: Optional[float] = typer.Option(None, "--power-threshold"),
    bandwidth_threshold: Optional[float] = typer.Option(None, "--bandwidth-threshold"),
    z_score_threshold: Optional[float] = typer.Option(None, "--z-score-threshold"),
    headless: bool = typer.Option(True, "--headless", help="Run without GUI"),
    export_format: Optional[str] = typer.Option(None, "--export-format"),
    export_path: Optional[Path] = typer.Option(None, "--export-path"),
    db_path: Optional[Path] = typer.Option(None, "--db-path"),
    log_level: str = _log_level_option,
) -> None:
    """Sweep a frequency range and detect signals at each step."""
    setup_logging(level=log_level)

    overrides = build_cli_overrides(
        host=host, port=port, sample_rate=sample_rate, fft_size=fft_size,
        power_threshold=power_threshold,
        bandwidth_threshold=bandwidth_threshold,
        z_score_threshold=z_score_threshold,
    )
    settings = load_settings(config_path=config, cli_overrides=overrides)

    typer.echo(f"Sweeping {start_freq/1e6:.1f} MHz to {end_freq/1e6:.1f} MHz (step={step/1e6:.1f} MHz, dwell={dwell}s)")

    # Build components
    rtlsdr = RTLSDRBase(
        host=settings.rtl_tcp.host,
        port=settings.rtl_tcp.port,
        center_freq=start_freq,
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
        min_duration=0.05,
        test_mode=False,
    )

    event_bus = EventBus()

    # Setup exporters
    exporter: Optional[Any] = None
    if export_format and export_path:
        if export_format.lower() == "csv":
            exporter = CsvExporter(output_path=export_path)
        elif export_format.lower() == "json":
            exporter = JsonExporter(output_path=export_path)
        else:
            typer.echo(f"Unknown export format: {export_format}", err=True)
            raise typer.Exit(1)
        event_bus.subscribe(exporter.export)

    # Setup SQLite
    store: Optional[EventStore] = None
    if db_path:
        store = EventStore(db_path)
        store.init_schema()
        store.start_session(
            center_freq_mhz=(start_freq + end_freq) / 2e6,
            sample_rate_hz=settings.receiver.sample_rate,
        )

        def save_to_db(event: JammingEvent) -> None:
            if store:
                store.insert_event(event)

        event_bus.subscribe(save_to_db)

    # Sweep loop
    current_freq = start_freq
    total_events = 0

    try:
        with rtlsdr:
            while current_freq <= end_freq:
                logger.info("Tuning to %.3f MHz", current_freq / 1e6)
                rtlsdr._send_command(0x01, int(current_freq))
                rtlsdr.center_freq = current_freq
                rtlsdr.freq_range = np.linspace(
                    -settings.receiver.sample_rate / 2e6 + current_freq / 1e6,
                    settings.receiver.sample_rate / 2e6 + current_freq / 1e6,
                    settings.receiver.fft_size,
                )

                # Reset detector baseline for new frequency
                detector.power_history.clear()
                detector.baseline_mean = None
                detector.baseline_std = None

                end_time = time.time() + dwell
                while time.time() < end_time:
                    iq_data = rtlsdr.read_samples()
                    if iq_data is None:
                        continue

                    spectrum = processor.process_samples(iq_data)
                    if spectrum is None:
                        continue

                    event = detector.detect_signal(
                        spectrum, rtlsdr.freq_range, time.time()
                    )
                    if event is not None:
                        event_bus.publish(event)
                        total_events += 1
                        logger.info(
                            "[%.3f MHz] Detection: power=%.1f dB, bw=%.0f Hz",
                            current_freq / 1e6, event.power, event.bandwidth,
                        )

                current_freq += step

    except KeyboardInterrupt:
        logger.info("Sweep interrupted.")
    finally:
        if store:
            store.end_session(total_events=total_events)
        logger.info("Sweep complete. Total events: %d", total_events)


@app.command(name="stats")
def stats(
    db_path: Path = typer.Argument("rtl_sdr_analyzer.db", help="Path to SQLite database"),
    top_freqs: bool = typer.Option(True, "--top-freqs", help="Show top frequencies"),
    hourly: bool = typer.Option(True, "--hourly", help="Show hourly activity"),
    recent: int = typer.Option(10, "--recent", help="Number of recent events to show"),
    export_csv: Optional[Path] = typer.Option(None, "--export-csv", help="Export events to CSV"),
    since_hours: Optional[int] = typer.Option(None, "--since-hours", help="Filter events by hours"),
) -> None:
    """Display statistics dashboard for detection events."""
    if not db_path.exists():
        typer.echo(f"Database not found: {db_path}", err=True)
        raise typer.Exit(1)

    dashboard = StatsDashboard(db_path)
    dashboard.show_summary()

    if top_freqs:
        dashboard.show_top_frequencies()

    if hourly:
        dashboard.show_hourly_activity()

    if recent > 0:
        dashboard.show_recent_events(limit=recent)

    if export_csv:
        dashboard.export_csv(export_csv, since_hours=since_hours)


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
        import yaml  # type: ignore[import-untyped]
        typer.echo(yaml.safe_dump(settings.model_dump(), sort_keys=False))


if __name__ == "__main__":
    app()
