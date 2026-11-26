"""Typer CLI application for RTL-SDR Analyzer (AMSTech)."""

import logging
import threading
import webbrowser
from pathlib import Path

import typer
import uvicorn
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from rtl_sdr_analyzer import __version__
from rtl_sdr_analyzer.cli.config_overrides import build_cli_overrides
from rtl_sdr_analyzer.config.loader import load_settings
from rtl_sdr_analyzer.config.models import SourceMode
from rtl_sdr_analyzer.engine.event_bus import EventBus
from rtl_sdr_analyzer.engine.spectrum_engine import SpectrumEngine
from rtl_sdr_analyzer.engine.sweeper import FrequencySweeper, SweepConfig, SweepProgress
from rtl_sdr_analyzer.exporters.csv_exporter import CsvExporter
from rtl_sdr_analyzer.exporters.json_exporter import JsonExporter
from rtl_sdr_analyzer.logging_config import setup_logging
from rtl_sdr_analyzer.recording.recorder import IQRecorder
from rtl_sdr_analyzer.sources.base import SDRSourceError
from rtl_sdr_analyzer.sources.factory import create_source
from rtl_sdr_analyzer.sources.usb import get_usb_diagnostics
from rtl_sdr_analyzer.storage.database import EventStore
from rtl_sdr_analyzer.storage.stats import (
    AMS_BRAND,
    AMS_LINE,
    AMS_MUTED,
    AMS_OK,
    AMS_TEXT,
    AMS_THOR,
    AMS_YELLOW,
    StatsDashboard,
)
from rtl_sdr_analyzer.visualization.headless import HeadlessRunner
from rtl_sdr_analyzer.web.app import create_app

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    name="rtl-sdr-analyzer",
    help="Real-time RF spectrum analyzer, signal detector, and wideband sweeper by AMSTech.",
    no_args_is_help=False,
)

_config_option = typer.Option(None, "--config", "-c", help="Path to YAML configuration file")
_log_level_option = typer.Option(
    "INFO", "--log-level", help="Logging level (DEBUG, INFO, WARNING, ERROR)"
)
_log_format_option = typer.Option("text", "--log-format", help="Log format: text or json")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"rtl-sdr-analyzer {__version__} (AMSTech)")
        raise typer.Exit(0)


def _attach_exporter(
    event_bus: EventBus,
    export_format: str | None,
    export_path: Path | None,
) -> CsvExporter | JsonExporter | None:
    if export_format and not export_path:
        typer.echo("--export-path is required when --export-format is set", err=True)
        raise typer.Exit(1)
    if export_path and not export_format:
        typer.echo("--export-format is required when --export-path is set", err=True)
        raise typer.Exit(1)
    if not export_format or not export_path:
        return None
    fmt = export_format.lower()
    if fmt == "csv":
        exporter: CsvExporter | JsonExporter = CsvExporter(output_path=export_path)
    elif fmt == "json":
        exporter = JsonExporter(output_path=export_path)
    else:
        typer.echo(f"Unknown export format: {export_format}", err=True)
        raise typer.Exit(1)
    event_bus.subscribe(exporter.export)
    return exporter


def _launch_studio(
    *,
    config: Path | None = None,
    source: SourceMode | None = None,
    device: int | None = None,
    lib_path: str | None = None,
    replay_path: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    tcp_host: str | None = None,
    tcp_port: int | None = None,
    freq: float | None = None,
    sample_rate: float | None = None,
    fft_size: int | None = None,
    gain: float | None = None,
    db_path: Path | None = None,
    open_browser: bool = False,
    log_level: str = "INFO",
    log_format: str = "text",
) -> None:
    setup_logging(level=log_level, json_format=(log_format == "json"))
    overrides = build_cli_overrides(
        source=source,
        device=device,
        lib_path=lib_path,
        replay_path=str(replay_path) if replay_path else None,
        web_host=host,
        web_port=port,
        tcp_host=tcp_host,
        tcp_port=tcp_port,
        freq=freq,
        sample_rate=sample_rate,
        fft_size=fft_size,
        gain=gain,
        db_path=str(db_path) if db_path else None,
    )
    settings = load_settings(config_path=config, cli_overrides=overrides)
    store = EventStore(settings.storage.db_path) if settings.storage.db_path else None
    engine = SpectrumEngine(settings=settings, store=store)
    web_app = create_app(engine=engine, store=store, settings=settings)

    url = f"http://{settings.web.host}:{settings.web.port}"
    console.print(
        Panel.fit(
            f"[{AMS_TEXT}]Studio:[/{AMS_TEXT}] [bold {AMS_THOR}]{url}[/bold {AMS_THOR}]\n"
            f"[{AMS_TEXT}]Source:[/{AMS_TEXT}] [bold {AMS_YELLOW}]{settings.source.mode}[/bold {AMS_YELLOW}]   "
            f"[{AMS_TEXT}]Center:[/{AMS_TEXT}] [bold {AMS_OK}]{settings.receiver.frequency / 1e6:.3f} MHz[/bold {AMS_OK}]   "
            f"[{AMS_TEXT}]Rate:[/{AMS_TEXT}] [{AMS_MUTED}]{settings.receiver.sample_rate / 1e6:.3f} MSPS[/{AMS_MUTED}]",
            title=f"[bold {AMS_BRAND}]AMSTech · rtl-sdr-analyzer v{__version__}[/bold {AMS_BRAND}]",
            border_style=AMS_BRAND,
            box=box.ROUNDED,
        )
    )

    if open_browser:
        threading.Timer(0.9, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        web_app,
        host=settings.web.host,
        port=settings.web.port,
        log_level=log_level.lower(),
    )


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Launch the AMSTech Web Studio when invoked without a subcommand."""
    if ctx.invoked_subcommand is None:
        _launch_studio()


@app.command()
def serve(
    config: Path | None = _config_option,
    source: SourceMode | None = typer.Option(
        None, "--source", help="RF source: auto, usb, rtl_tcp, simulated, file"
    ),
    device: int | None = typer.Option(None, "--device", help="USB RTL-SDR device index"),
    lib_path: str | None = typer.Option(
        None, "--lib-path", help="Path to librtlsdr shared library"
    ),
    replay_path: Path | None = typer.Option(
        None, "--replay", help="IQ file path for file replay mode"
    ),
    host: str | None = typer.Option(None, "--host", help="Web server bind host"),
    port: int | None = typer.Option(None, "--port", help="Web server port"),
    tcp_host: str | None = typer.Option(None, "--tcp-host", help="RTL-TCP server host"),
    tcp_port: int | None = typer.Option(None, "--tcp-port", help="RTL-TCP server port"),
    freq: float | None = typer.Option(None, "--freq", help="Center frequency in Hz"),
    sample_rate: float | None = typer.Option(None, "--sample-rate", help="Sample rate in Hz"),
    fft_size: int | None = typer.Option(None, "--fft-size", help="FFT size (power of 2)"),
    gain: float | None = typer.Option(None, "--gain", help="Manual RF gain in dB"),
    db_path: Path | None = typer.Option(None, "--db-path", help="SQLite database path"),
    open_browser: bool = typer.Option(False, "--open", help="Open Web Studio in browser"),
    log_level: str = _log_level_option,
    log_format: str = _log_format_option,
) -> None:
    """Start the local AMSTech Web Studio (spectrum, waterfall, sweep, events)."""
    _launch_studio(
        config=config,
        source=source,
        device=device,
        lib_path=lib_path,
        replay_path=replay_path,
        host=host,
        port=port,
        tcp_host=tcp_host,
        tcp_port=tcp_port,
        freq=freq,
        sample_rate=sample_rate,
        fft_size=fft_size,
        gain=gain,
        db_path=db_path,
        open_browser=open_browser,
        log_level=log_level,
        log_format=log_format,
    )


@app.command()
def devices(
    lib_path: str | None = typer.Option(None, "--lib-path", help="Optional path to librtlsdr"),
) -> None:
    """List attached USB RTL-SDR dongles and librtlsdr library status."""
    diag = get_usb_diagnostics(lib_path)
    lib_status = (
        f"[{AMS_OK}]{diag['library_path']}[/{AMS_OK}]"
        if diag["library_found"]
        else f"[{AMS_YELLOW}]Not found[/{AMS_YELLOW}] ({diag['message']})"
    )
    console.print(f"[{AMS_TEXT}]librtlsdr:[/{AMS_TEXT}] {lib_status}")

    devs = diag["devices"]
    if not devs:
        console.print(f"[{AMS_MUTED}]No USB RTL-SDR devices detected.[/{AMS_MUTED}]")
        return

    table = Table(
        title=f"[bold {AMS_BRAND}]Detected USB RTL-SDR Devices[/bold {AMS_BRAND}]",
        box=box.ROUNDED,
        border_style=AMS_LINE,
        header_style=f"bold {AMS_THOR}",
    )
    table.add_column("Index", style=AMS_THOR, justify="right")
    table.add_column("Name", style=AMS_TEXT)
    table.add_column("Manufacturer", style=AMS_MUTED)
    table.add_column("Product", style=AMS_MUTED)
    table.add_column("Serial", style=AMS_YELLOW)

    for d in devs:
        table.add_row(
            str(d["index"]),
            str(d["name"]),
            str(d.get("manufacturer") or "—"),
            str(d.get("product") or "—"),
            str(d.get("serial") or "—"),
        )
    console.print(table)


@app.command()
def analyze(
    config: Path | None = _config_option,
    source: SourceMode | None = typer.Option(
        None, "--source", help="RF source: auto, usb, rtl_tcp, simulated, file"
    ),
    device: int | None = typer.Option(None, "--device", help="USB RTL-SDR device index"),
    lib_path: str | None = typer.Option(None, "--lib-path", help="Path to librtlsdr"),
    host: str | None = typer.Option(None, "--host", help="RTL-TCP server host"),
    port: int | None = typer.Option(None, "--port", help="RTL-TCP server port"),
    freq: float | None = typer.Option(None, "--freq", help="Center frequency in Hz"),
    sample_rate: float | None = typer.Option(None, "--sample-rate", help="Sample rate in Hz"),
    fft_size: int | None = typer.Option(None, "--fft-size", help="FFT size"),
    gain: float | None = typer.Option(None, "--gain", help="Manual RF gain in dB"),
    power_threshold: float | None = typer.Option(
        None, "--power-threshold", help="Power threshold in dBFS"
    ),
    snr_threshold: float | None = typer.Option(None, "--snr-threshold", help="Minimum SNR in dB"),
    bandwidth_threshold: float | None = typer.Option(
        None, "--bandwidth-threshold", help="Minimum bandwidth in Hz"
    ),
    z_score_threshold: float | None = typer.Option(
        None, "--z-score-threshold", help="Z-score threshold"
    ),
    detection_window: int | None = typer.Option(
        None, "--detection-window", help="Baseline window frames"
    ),
    min_duration: float | None = typer.Option(
        None, "--min-duration", help="Minimum event duration in seconds"
    ),
    test_mode: bool | None = typer.Option(
        None, "--test-mode", help="Enable sensitive any-criterion detection"
    ),
    max_frames: int | None = typer.Option(
        None, "--max-frames", help="Stop after N frames (optional)"
    ),
    export_format: str | None = typer.Option(
        None, "--export-format", help="Event export format: csv or json"
    ),
    export_path: Path | None = typer.Option(None, "--export-path", help="Path for exported events"),
    db_path: Path | None = typer.Option(None, "--db-path", help="SQLite database path"),
    log_level: str = _log_level_option,
    log_format: str = _log_format_option,
) -> None:
    """Run headless real-time spectrum analysis and signal detection."""
    setup_logging(level=log_level, json_format=(log_format == "json"))

    overrides = build_cli_overrides(
        source=source,
        device=device,
        lib_path=lib_path,
        host=host,
        port=port,
        freq=freq,
        sample_rate=sample_rate,
        fft_size=fft_size,
        gain=gain,
        power_threshold=power_threshold,
        snr_threshold=snr_threshold,
        bandwidth_threshold=bandwidth_threshold,
        z_score_threshold=z_score_threshold,
        detection_window=detection_window,
        min_duration=min_duration,
        test_mode=test_mode,
        db_path=str(db_path) if db_path else None,
    )
    settings = load_settings(config_path=config, cli_overrides=overrides)
    allow_sim = settings.source.mode in ("auto", "simulated")

    try:
        rf_source = create_source(settings, allow_simulated_fallback=allow_sim)
    except SDRSourceError as exc:
        typer.echo(f"Source error: {exc}", err=True)
        raise typer.Exit(1)

    event_bus = EventBus()
    exporter = _attach_exporter(event_bus, export_format, export_path)
    store = EventStore(settings.storage.db_path) if settings.storage.db_path else None
    engine = SpectrumEngine(settings=settings, source=rf_source, store=store, event_bus=event_bus)

    runner = HeadlessRunner(engine=engine, max_frames=max_frames, console=console)
    try:
        runner.run()
    finally:
        if exporter is not None:
            exporter.close()


@app.command()
def record(
    output: Path = typer.Argument(..., help="Output file path (.raw, .cu8, or .npz)"),
    duration: float = typer.Option(10.0, "--duration", help="Recording duration in seconds"),
    format: str = typer.Option("raw", "--format", help="Output format: raw or numpy"),
    config: Path | None = _config_option,
    source: SourceMode | None = typer.Option(
        None, "--source", help="RF source: auto, usb, rtl_tcp, simulated"
    ),
    device: int | None = typer.Option(None, "--device", help="USB device index"),
    lib_path: str | None = typer.Option(None, "--lib-path", help="Path to librtlsdr"),
    host: str | None = typer.Option(None, "--host", help="RTL-TCP host"),
    port: int | None = typer.Option(None, "--port", help="RTL-TCP port"),
    freq: float | None = typer.Option(None, "--freq", help="Center frequency in Hz"),
    sample_rate: float | None = typer.Option(None, "--sample-rate", help="Sample rate in Hz"),
    gain: float | None = typer.Option(None, "--gain", help="Manual RF gain in dB"),
    log_level: str = _log_level_option,
) -> None:
    """Record raw IQ samples to a file for offline analysis."""
    setup_logging(level=log_level)
    overrides = build_cli_overrides(
        source=source,
        device=device,
        lib_path=lib_path,
        host=host,
        port=port,
        freq=freq,
        sample_rate=sample_rate,
        gain=gain,
    )
    settings = load_settings(config_path=config, cli_overrides=overrides)
    allow_sim = settings.source.mode == "simulated"

    try:
        rf_source = create_source(settings, allow_simulated_fallback=allow_sim)
        with (
            rf_source,
            IQRecorder(
                output_path=output,
                format=format,
                sample_rate=settings.receiver.sample_rate,
                center_freq=settings.receiver.frequency,
                gain=settings.receiver.gain,
            ) as recorder,
        ):
            total = recorder.record(rf_source, duration=duration)
    except KeyboardInterrupt:
        logger.info("Recording interrupted.")
    except Exception as exc:
        typer.echo(f"Recording failed: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Recording saved to {output} ({total:,} samples)")


@app.command()
def sweep(
    start_freq: float = typer.Argument(..., help="Start frequency in Hz"),
    end_freq: float = typer.Argument(..., help="End frequency in Hz"),
    step: float | None = typer.Option(
        None, "--step", help="Frequency step in Hz (default 80% of sample rate)"
    ),
    dwell: float = typer.Option(0.35, "--dwell", help="Dwell time per step in seconds"),
    config: Path | None = _config_option,
    source: SourceMode | None = typer.Option(
        None, "--source", help="RF source: auto, usb, rtl_tcp, simulated"
    ),
    device: int | None = typer.Option(None, "--device", help="USB device index"),
    lib_path: str | None = typer.Option(None, "--lib-path", help="Path to librtlsdr"),
    host: str | None = typer.Option(None, "--host", help="RTL-TCP host"),
    port: int | None = typer.Option(None, "--port", help="RTL-TCP port"),
    sample_rate: float | None = typer.Option(None, "--sample-rate", help="Sample rate in Hz"),
    fft_size: int | None = typer.Option(None, "--fft-size", help="FFT size"),
    gain: float | None = typer.Option(None, "--gain", help="Manual RF gain in dB"),
    power_threshold: float | None = typer.Option(
        None, "--power-threshold", help="Peak power threshold in dBFS"
    ),
    snr_threshold: float | None = typer.Option(None, "--snr-threshold", help="Minimum SNR in dB"),
    export_format: str | None = typer.Option(None, "--export-format", help="csv or json"),
    export_path: Path | None = typer.Option(None, "--export-path", help="Export file path"),
    db_path: Path | None = typer.Option(None, "--db-path", help="SQLite database path"),
    log_level: str = _log_level_option,
) -> None:
    """Sweep a frequency range and report detected spectral peaks."""
    setup_logging(level=log_level)
    overrides = build_cli_overrides(
        source=source,
        device=device,
        lib_path=lib_path,
        host=host,
        port=port,
        sample_rate=sample_rate,
        fft_size=fft_size,
        gain=gain,
        power_threshold=power_threshold,
        snr_threshold=snr_threshold,
        db_path=str(db_path) if db_path else None,
    )
    settings = load_settings(config_path=config, cli_overrides=overrides)
    allow_sim = settings.source.mode in ("auto", "simulated")

    event_bus = EventBus()
    exporter = _attach_exporter(event_bus, export_format, export_path)
    store: EventStore | None = None
    if settings.storage.db_path:
        store = EventStore(settings.storage.db_path)
        store.init_schema()
        store.start_session(
            center_freq_mhz=0.5 * (start_freq + end_freq) / 1e6,
            sample_rate_hz=settings.receiver.sample_rate,
        )

    try:
        rf_source = create_source(settings, allow_simulated_fallback=allow_sim)
        sweeper = FrequencySweeper(event_bus=event_bus, store=store)
        sweep_cfg = SweepConfig(
            start_freq_hz=start_freq,
            end_freq_hz=end_freq,
            step_hz=step,
            dwell_seconds=dwell,
            fft_size=min(8192, max(256, settings.receiver.fft_size)),
            sample_rate_hz=settings.receiver.sample_rate,
            power_threshold_db=settings.detector.power_threshold,
            snr_threshold_db=settings.detector.snr_threshold,
        )

        with (
            rf_source,
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress,
        ):
            task_id = progress.add_task("Sweeping…", total=None)

            def _on_prog(p: SweepProgress) -> None:
                progress.update(
                    task_id,
                    description=f"Sweeping {p.current_freq_mhz:.2f} MHz ({p.step_index}/{p.total_steps}) · {p.peaks_found} peaks",
                )

            result = sweeper.run(rf_source, sweep_cfg, on_progress=_on_prog)
    except Exception as exc:
        typer.echo(f"Sweep failed: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        if store is not None:
            store.end_session()
        if exporter is not None:
            exporter.close()

    console.print(
        f"[{AMS_TEXT}]Sweep complete:[/{AMS_TEXT}] "
        f"[{AMS_THOR}]{result.start_freq_mhz:.2f}–{result.end_freq_mhz:.2f} MHz[/{AMS_THOR}]  "
        f"noise=[{AMS_MUTED}]{result.noise_floor_db:.1f} dBFS[/{AMS_MUTED}]  "
        f"peaks=[{AMS_OK}]{len(result.peaks)}[/{AMS_OK}]  "
        f"time=[{AMS_MUTED}]{result.duration_s:.2f}s[/{AMS_MUTED}]"
    )
    if result.peaks:
        table = Table(
            box=box.ROUNDED,
            border_style=AMS_LINE,
            header_style=f"bold {AMS_THOR}",
        )
        table.add_column("Freq (MHz)", style=AMS_THOR, justify="right")
        table.add_column("Power (dBFS)", style=AMS_YELLOW, justify="right")
        table.add_column("SNR (dB)", style=AMS_OK, justify="right")
        table.add_column("BW (kHz)", style=AMS_MUTED, justify="right")
        for pk in result.peaks[:20]:
            table.add_row(
                f"{pk.frequency_mhz:.4f}",
                f"{pk.power_db:.1f}",
                f"+{pk.snr_db:.1f}",
                f"{pk.bandwidth_hz / 1e3:.1f}",
            )
        console.print(table)


@app.command(name="stats")
def stats(
    db_path: Path = typer.Argument(Path("rtl_sdr_analyzer.db"), help="Path to SQLite database"),
    top_freqs: bool = typer.Option(True, "--top-freqs", help="Show top frequencies"),
    hourly: bool = typer.Option(True, "--hourly", help="Show hourly activity"),
    recent: int = typer.Option(10, "--recent", help="Number of recent events to show"),
    export_csv: Path | None = typer.Option(None, "--export-csv", help="Export events to CSV"),
    since_hours: int | None = typer.Option(None, "--since-hours", help="Filter events by hours"),
) -> None:
    """Display AMSTech statistics dashboard for detection events."""
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
    """Validate a configuration file against the Pydantic schema."""
    try:
        settings = load_settings(config_path=config_path)
        typer.echo("Configuration is valid.")
        typer.echo(settings.model_dump_json(indent=2))
    except Exception as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="config-show")
def config_show(
    config: Path | None = _config_option,
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
