"""Statistics dashboard for detection events."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

from rich.console import Console
from rich.table import Table

from rtl_sdr_analyzer.storage.database import EventStore

logger = logging.getLogger(__name__)
console = Console()


class StatsDashboard:
    """Console-based statistics dashboard for RTL-SDR events.

    Example::

        dashboard = StatsDashboard("events.db")
        dashboard.show_summary()
        dashboard.show_top_frequencies()
        dashboard.show_hourly_activity()
    """

    def __init__(self, db_path: Union[Path, str] = "rtl_sdr_analyzer.db"):
        self.store = EventStore(db_path)

    def show_summary(self) -> None:
        """Display a high-level summary of all activity."""
        total_events = self.store.get_event_count()
        recent_events = self.store.get_event_count(
            since=(datetime.now() - timedelta(hours=24)).isoformat()
        )
        sessions = self.store.get_sessions(limit=5)

        console.print()
        console.print("[bold cyan]📊 RTL-SDR Analyzer Statistics[/bold cyan]")
        console.print("=" * 50)
        console.print(f"Total detection events: [bold]{total_events}[/bold]")
        console.print(f"Events in last 24h: [bold green]{recent_events}[/bold green]")
        console.print(f"Recent sessions: [bold]{len(sessions)}[/bold]")

        if sessions:
            console.print("\n[bold]Recent Sessions[/bold]")
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("ID")
            table.add_column("Start Time")
            table.add_column("Frequency (MHz)")
            table.add_column("Events")

            for session in sessions:
                table.add_row(
                    str(session["id"]),
                    session["start_time"],
                    f"{session['center_freq_mhz']:.3f}" if session["center_freq_mhz"] else "N/A",
                    str(session["total_events"]),
                )
            console.print(table)

    def show_top_frequencies(self, limit: int = 10) -> None:
        """Display the most active frequencies."""
        freqs = self.store.get_top_frequencies(limit)

        if not freqs:
            console.print("[yellow]No frequency data available.[/yellow]")
            return

        console.print("\n[bold]🔥 Top Frequencies by Activity[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Frequency (MHz)")
        table.add_column("Detections")
        table.add_column("Avg Power (dB)")
        table.add_column("Max Power (dB)")

        for f in freqs:
            table.add_row(
                f"{f['frequency_mhz']:.3f}",
                str(f["count"]),
                f"{f['avg_power']:.1f}",
                f"{f['max_power']:.1f}",
            )
        console.print(table)

    def show_hourly_activity(self) -> None:
        """Display hourly detection activity."""
        hours = self.store.get_hourly_activity()

        if not hours:
            console.print("[yellow]No hourly data available.[/yellow]")
            return

        console.print("\n[bold]📈 Hourly Activity (Last 24h)[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Hour")
        table.add_column("Detections")

        for h in hours:
            table.add_row(h["hour"], str(h["count"]))
        console.print(table)

    def show_recent_events(self, limit: int = 20) -> None:
        """Display recent detection events."""
        events = self.store.get_recent_events(limit)

        if not events:
            console.print("[yellow]No recent events.[/yellow]")
            return

        console.print(f"\n[bold]🔍 Last {limit} Detection Events[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Time")
        table.add_column("Freq (MHz)")
        table.add_column("Power (dB)")
        table.add_column("BW (Hz)")
        table.add_column("Duration (s)")
        table.add_column("Confidence")

        for e in events:
            table.add_row(
                e["timestamp"][:19],
                f"{e['frequency_mhz']:.3f}",
                f"{e['power_db']:.1f}",
                f"{e['bandwidth_hz']:.0f}",
                f"{e['duration_s']:.2f}",
                f"{e['confidence']:.2f}",
            )
        console.print(table)

    def export_csv(self, output_path: Path, since_hours: Optional[int] = None) -> int:
        """Export events to CSV and return count."""
        since = None
        if since_hours:
            since = (datetime.now() - timedelta(hours=since_hours)).isoformat()

        count = self.store.export_to_csv(output_path, since=since)
        console.print(f"\n[green]Exported {count} events to {output_path}[/green]")
        return count
