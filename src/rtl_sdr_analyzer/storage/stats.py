"""AMSTech-themed console statistics dashboard for detection events."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from rtl_sdr_analyzer.storage.database import EventStore

logger = logging.getLogger(__name__)
console = Console()

# AMSTech noche palette for terminal readability without imposing a background
AMS_BRAND = "#7F89E8"
AMS_THOR = "#9EA6F2"
AMS_TEXT = "#E9E6E0"
AMS_MUTED = "#9E9AA8"
AMS_LINE = "#4A4A57"
AMS_YELLOW = "#D9C26A"
AMS_OK = "#8FD3A4"
AMS_BAD = "#F0A094"


class StatsDashboard:
    """Rich terminal statistics dashboard styled with AMSTech tokens."""

    def __init__(self, db_path: Path | str = "rtl_sdr_analyzer.db") -> None:
        self.store = EventStore(db_path)

    def show_summary(self) -> None:
        """Display high-level event and session summary."""
        total_events = self.store.get_event_count()
        since_24h = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        recent_events = self.store.get_event_count(since=since_24h)
        sessions = self.store.get_sessions(limit=5)

        console.print()
        console.print(
            Panel.fit(
                f"[{AMS_TEXT}]Total events:[/{AMS_TEXT}] [bold {AMS_THOR}]{total_events}[/bold {AMS_THOR}]   "
                f"[{AMS_TEXT}]Last 24h:[/{AMS_TEXT}] [bold {AMS_OK}]{recent_events}[/bold {AMS_OK}]   "
                f"[{AMS_TEXT}]Recent sessions:[/{AMS_TEXT}] [bold {AMS_YELLOW}]{len(sessions)}[/bold {AMS_YELLOW}]",
                title=f"[bold {AMS_BRAND}]AMSTech · RTL-SDR Statistics[/bold {AMS_BRAND}]",
                border_style=AMS_BRAND,
                box=box.ROUNDED,
            )
        )

        if sessions:
            table = Table(
                title=f"[bold {AMS_TEXT}]Recent Sessions[/bold {AMS_TEXT}]",
                box=box.ROUNDED,
                border_style=AMS_LINE,
                header_style=f"bold {AMS_THOR}",
            )
            table.add_column("ID", style=AMS_MUTED, justify="right")
            table.add_column("Start Time (UTC)", style=AMS_TEXT)
            table.add_column("Center (MHz)", style=AMS_THOR, justify="right")
            table.add_column("Events", style=AMS_OK, justify="right")

            for session in sessions:
                freq = (
                    f"{session['center_freq_mhz']:.3f}"
                    if session["center_freq_mhz"] is not None
                    else "N/A"
                )
                table.add_row(
                    str(session["id"]),
                    str(session["start_time"])[:19].replace("T", " "),
                    freq,
                    str(session["total_events"]),
                )
            console.print(table)

    def show_top_frequencies(self, limit: int = 10) -> None:
        """Display most active frequencies."""
        freqs = self.store.get_top_frequencies(limit)
        if not freqs:
            console.print(f"[{AMS_MUTED}]No frequency detections recorded yet.[/{AMS_MUTED}]")
            return

        table = Table(
            title=f"[bold {AMS_TEXT}]Top Active Frequencies[/bold {AMS_TEXT}]",
            box=box.ROUNDED,
            border_style=AMS_LINE,
            header_style=f"bold {AMS_THOR}",
        )
        table.add_column("Frequency (MHz)", style=AMS_THOR, justify="right")
        table.add_column("Detections", style=AMS_TEXT, justify="right")
        table.add_column("Avg Power (dBFS)", style=AMS_MUTED, justify="right")
        table.add_column("Peak Power (dBFS)", style=AMS_YELLOW, justify="right")

        for item in freqs:
            table.add_row(
                f"{item['frequency_mhz']:.3f}",
                str(item["count"]),
                f"{item['avg_power']:.1f}",
                f"{item['max_power']:.1f}",
            )
        console.print(table)

    def show_hourly_activity(self) -> None:
        """Display hourly detection breakdown."""
        hours = self.store.get_hourly_activity()
        if not hours:
            console.print(f"[{AMS_MUTED}]No hourly activity recorded yet.[/{AMS_MUTED}]")
            return

        table = Table(
            title=f"[bold {AMS_TEXT}]Hourly Activity (UTC, Last 24h)[/bold {AMS_TEXT}]",
            box=box.ROUNDED,
            border_style=AMS_LINE,
            header_style=f"bold {AMS_THOR}",
        )
        table.add_column("Hour", style=AMS_TEXT)
        table.add_column("Detections", style=AMS_OK, justify="right")

        for h in hours:
            table.add_row(str(h["hour"]), str(h["count"]))
        console.print(table)

    def show_recent_events(self, limit: int = 20) -> None:
        """Display recent detection events."""
        events = self.store.get_recent_events(limit)
        if not events:
            console.print(f"[{AMS_MUTED}]No recent events.[/{AMS_MUTED}]")
            return

        table = Table(
            title=f"[bold {AMS_TEXT}]Last {limit} Detections[/bold {AMS_TEXT}]",
            box=box.ROUNDED,
            border_style=AMS_LINE,
            header_style=f"bold {AMS_THOR}",
        )
        table.add_column("Time (UTC)", style=AMS_MUTED)
        table.add_column("Freq (MHz)", style=AMS_THOR, justify="right")
        table.add_column("Power (dBFS)", style=AMS_YELLOW, justify="right")
        table.add_column("SNR (dB)", style=AMS_OK, justify="right")
        table.add_column("BW (kHz)", style=AMS_TEXT, justify="right")
        table.add_column("Dur (s)", style=AMS_MUTED, justify="right")

        for e in events:
            snr_str = f"{e['snr']:.1f}" if e["snr"] is not None else "—"
            table.add_row(
                str(e["timestamp"])[:19].replace("T", " "),
                f"{e['frequency_mhz']:.3f}",
                f"{e['power_db']:.1f}",
                snr_str,
                f"{e['bandwidth_hz'] / 1e3:.1f}",
                f"{e['duration_s']:.2f}",
            )
        console.print(table)

    def export_csv(self, output_path: Path, since_hours: int | None = None) -> int:
        """Export events to CSV and return exported count."""
        since = None
        if since_hours is not None:
            since = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()
        count = self.store.export_to_csv(output_path, since=since)
        console.print(f"[{AMS_OK}]Exported {count} events to {output_path}[/{AMS_OK}]")
        return count
