"""
Beautiful terminal output using Rich.
"""

import asyncio
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .parser import LogParser, LogEntry


class TerminalViewer:
    """Beautiful terminal log viewer with Rich."""

    LEVEL_COLORS = {
        "TRACE": "bright_black",
        "DEBUG": "cyan",
        "INFO": "green",
        "WARN": "yellow",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold red",
        "FATAL": "bold red on white",
        "UNKNOWN": "white",
    }

    def __init__(self, use_colors: bool = True):
        self.console = Console(
            force_terminal=use_colors, color_system="auto" if use_colors else None
        )
        self.parser = LogParser()

    async def view_file(
        self,
        file_path: str,
        lines: Optional[int] = None,
        follow: bool = False,
        level_filter: Optional[str] = None,
        pattern: Optional[str] = None,
        thread_filter: Optional[str] = None,
    ):
        """View a log file with beautiful formatting."""
        path = Path(file_path)

        if not path.exists():
            self.console.print(f"[red]❌ File not found: {file_path}[/red]")
            return

        self.console.print(f"\n[bold cyan]📄 {path.name}[/bold cyan]")
        self.console.print(f"[dim]{path.absolute()}[/dim]\n")

        # Read file
        with open(file_path, "r") as f:
            all_lines = f.readlines()

        # Parse entries
        entries = [self.parser.parse_line(i + 1, line.rstrip()) for i, line in enumerate(all_lines)]

        # Apply filters
        entries = self._apply_filters(entries, level_filter, pattern, thread_filter)

        # Apply line limit
        if lines and not follow:
            entries = entries[-lines:]

        # Display entries
        if follow:
            await self._follow_mode(
                path, entries[-lines:] if lines else entries, level_filter, pattern, thread_filter
            )
        else:
            self._display_entries(entries)

    def _apply_filters(
        self,
        entries: list,
        level_filter: Optional[str],
        pattern: Optional[str],
        thread_filter: Optional[str],
    ) -> list:
        """Apply filters to log entries."""
        filtered = entries

        if level_filter:
            level_upper = level_filter.upper()
            filtered = [e for e in filtered if e.level == level_upper]

        if pattern:
            filtered = [e for e in filtered if pattern.lower() in e.message.lower()]

        if thread_filter:
            filtered = [e for e in filtered if e.thread_id == thread_filter]

        return filtered

    def _display_entries(self, entries: list):
        """Display log entries with beautiful formatting."""
        if not entries:
            self.console.print("[yellow]No matching log entries found.[/yellow]")
            return

        for entry in entries:
            self._print_entry(entry)

    def _print_entry(self, entry: LogEntry):
        """Print a single log entry with rich formatting."""
        # Build the line components
        parts = []

        # Line number
        parts.append(Text(f"{entry.line_number:6}", style="dim"))

        # Timestamp
        if entry.timestamp:
            ts_str = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            parts.append(Text(ts_str, style="cyan"))

        # Level with color
        level_color = self.LEVEL_COLORS.get(entry.level, "white")
        parts.append(Text(f"{entry.level:8}", style=level_color))

        # Thread ID if present
        if entry.thread_id:
            parts.append(Text(f"[{entry.thread_id}]", style="magenta"))

        # Correlation ID if present
        if entry.correlation_id:
            parts.append(Text(f"[{entry.correlation_id}]", style="blue"))

        # Message
        parts.append(Text(entry.message, style="white"))

        # Combine and print
        line = Text(" ").join(parts)
        self.console.print(line)

        # Print trace info if present
        if entry.trace_id or entry.span_id:
            trace_info = []
            if entry.trace_id:
                trace_info.append(f"trace:{entry.trace_id}")
            if entry.span_id:
                trace_info.append(f"span:{entry.span_id}")
            self.console.print(f"  [dim]└─ {' '.join(trace_info)}[/dim]")

        # Print additional fields if present
        if entry.fields:
            for key, value in entry.fields.items():
                self.console.print(f"  [dim]  {key}: {value}[/dim]")

    async def _follow_mode(
        self,
        path: Path,
        initial_entries: list,
        level_filter: Optional[str],
        pattern: Optional[str],
        thread_filter: Optional[str],
    ):
        """Follow log file in real-time."""
        # Display initial entries
        self._display_entries(initial_entries)

        self.console.print("\n[bold green]📡 Following log file... (Ctrl+C to stop)[/bold green]\n")

        # Track file position
        with open(path, "r") as f:
            f.seek(0, 2)  # Go to end
            line_number = len(initial_entries)

            while True:
                line = f.readline()
                if line:
                    line_number += 1
                    entry = self.parser.parse_line(line_number, line.rstrip())

                    # Apply filters
                    filtered = self._apply_filters([entry], level_filter, pattern, thread_filter)
                    if filtered:
                        self._print_entry(entry)
                else:
                    await asyncio.sleep(0.1)

    def display_thread_view(self, entries: list):
        """Display beautiful thread-correlated view."""
        from .tracker import ThreadTracker

        tracker = ThreadTracker()
        for entry in entries:
            tracker.track(entry)

        self.console.print("\n[bold]🧵 Thread View[/bold]\n")

        threads = tracker.get_all_threads()

        if not threads:
            self.console.print("[yellow]No thread information found.[/yellow]")
            return

        table = Table(title="Threads", show_header=True, header_style="bold magenta")
        table.add_column("Thread ID", style="cyan", no_wrap=True)
        table.add_column("Logs", justify="right", style="green")
        table.add_column("Errors", justify="right", style="red")
        table.add_column("Duration", style="yellow")

        for thread in threads:
            duration = ""
            if thread["first_seen"] and thread["last_seen"]:
                delta = thread["last_seen"] - thread["first_seen"]
                duration = f"{delta.total_seconds():.2f}s"

            table.add_row(
                thread["thread_id"],
                str(thread["log_count"]),
                str(thread["error_count"]),
                duration,
            )

        self.console.print(table)

        # Show thread timeline
        for thread in threads[:5]:  # Show top 5
            self._display_thread_timeline(thread, entries)

    def _display_thread_timeline(self, thread: dict, all_entries: list):
        """Display timeline for a specific thread."""
        thread_entries = [e for e in all_entries if e.thread_id == thread["thread_id"]]

        if not thread_entries:
            return

        panel_title = f"🧵 Thread: {thread['thread_id']}"
        panel_content = []

        for entry in thread_entries[:10]:  # Show first 10
            level_color = self.LEVEL_COLORS.get(entry.level, "white")
            panel_content.append(f"[{level_color}]●[/{level_color}] {entry.message[:80]}")

        if len(thread_entries) > 10:
            panel_content.append(f"[dim]... and {len(thread_entries) - 10} more[/dim]")

        self.console.print(
            Panel(
                "\n".join(panel_content),
                title=panel_title,
                border_style="cyan",
            )
        )
        self.console.print()
