"""
Command-line interface for Logler.
"""

import click
import sys
from pathlib import Path
from typing import Optional, List
import asyncio
import socket
from contextlib import closing

from .terminal import TerminalViewer
from .web.app import run_server


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option()
def main(ctx):
    """
    🔍 Logler - Beautiful local log viewer

    A modern log viewer with thread tracking, real-time updates, and beautiful output.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _find_open_port(host: str, start_port: int, max_tries: int = 20) -> int:
    """Find the next available port starting from start_port."""
    for candidate in range(start_port, start_port + max_tries):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    raise RuntimeError(f"No open port found in range {start_port}-{start_port + max_tries - 1}")


@main.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=7607, help="Port to bind to (default 7607 ~ 'LOGL')")
@click.option("--auto-port/--no-auto-port", default=True, help="Pick the next free port if the chosen one is busy")
@click.option("--open", "-o", is_flag=True, help="Open browser automatically")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
def serve(host: str, port: int, auto_port: bool, open: bool, files: tuple):
    """
    Start the web server interface.

    Examples:
        logler serve                    # Start with file picker
        logler serve app.log            # Start with specific file
        logler serve *.log              # Start with multiple files
    """
    if auto_port:
        chosen_port = _find_open_port(host, port)
        if chosen_port != port:
            click.echo(f"⚠️  Port {port} busy, using {chosen_port} instead")
        port = chosen_port

    click.echo(f"🚀 Starting Logler web server on http://{host}:{port}")

    file_paths = [str(Path(f).absolute()) for f in files] if files else []

    if open:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    asyncio.run(run_server(host, port, file_paths))


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("-n", "--lines", type=int, help="Number of lines to show")
@click.option("-f", "--follow", is_flag=True, help="Follow log file in real-time")
@click.option("--level", type=str, help="Filter by log level (DEBUG, INFO, WARN, ERROR)")
@click.option("--grep", type=str, help="Search for pattern")
@click.option("--thread", type=str, help="Filter by thread ID")
@click.option("--no-color", is_flag=True, help="Disable colored output")
def view(files: tuple, lines: Optional[int], follow: bool, level: Optional[str],
         grep: Optional[str], thread: Optional[str], no_color: bool):
    """
    View log files in the terminal with beautiful output.

    Examples:
        logler view app.log                      # View entire file
        logler view app.log -n 100               # Last 100 lines
        logler view app.log -f                   # Follow in real-time
        logler view app.log --level ERROR        # Show only errors
        logler view app.log --grep "timeout"     # Search for pattern
        logler view app.log --thread worker-1    # Filter by thread
    """
    viewer = TerminalViewer(use_colors=not no_color)

    for file_path in files:
        try:
            asyncio.run(viewer.view_file(
                file_path=file_path,
                lines=lines,
                follow=follow,
                level_filter=level,
                pattern=grep,
                thread_filter=thread,
            ))
        except KeyboardInterrupt:
            click.echo("\n👋 Goodbye!")
            sys.exit(0)
        except Exception as e:
            click.echo(f"❌ Error: {e}", err=True)
            sys.exit(1)


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def stats(files: tuple, output_json: bool):
    """
    Show statistics for log files.

    Examples:
        logler stats app.log             # Show statistics
        logler stats app.log --json      # Output as JSON
    """
    from .parser import LogParser
    from rich.console import Console
    from rich.table import Table
    import json as json_module

    console = Console()
    parser = LogParser()

    for file_path in files:
        with open(file_path, 'r') as f:
            entries = [parser.parse_line(i+1, line.rstrip()) for i, line in enumerate(f)]

        stats_data = {
            "total": len(entries),
            "by_level": {},
            "by_thread": {},
            "errors": 0,
        }

        for entry in entries:
            level = str(entry.level)
            stats_data["by_level"][level] = stats_data["by_level"].get(level, 0) + 1

            if entry.level in ["ERROR", "FATAL", "CRITICAL"]:
                stats_data["errors"] += 1

            if entry.thread_id:
                stats_data["by_thread"][entry.thread_id] = stats_data["by_thread"].get(entry.thread_id, 0) + 1

        if output_json:
            console.print_json(data=stats_data)
        else:
            console.print(f"\n[bold]📊 Statistics for {file_path}[/bold]\n")

            table = Table(title="Log Levels")
            table.add_column("Level", style="cyan")
            table.add_column("Count", justify="right", style="green")

            for level, count in sorted(stats_data["by_level"].items()):
                table.add_row(level, str(count))

            console.print(table)

            console.print(f"\n[bold red]Errors:[/bold red] {stats_data['errors']}")
            console.print(f"[bold]Total:[/bold] {stats_data['total']} entries\n")


@main.command()
@click.argument("pattern", required=True)
@click.option("--directory", "-d", default=".", help="Directory to watch")
@click.option("--recursive", "-r", is_flag=True, help="Watch recursively")
def watch(pattern: str, directory: str, recursive: bool):
    """
    Watch for new log files matching a pattern.

    Examples:
        logler watch "*.log"                # Watch current directory
        logler watch "app-*.log" -d /var/log  # Watch specific directory
        logler watch "*.log" -r             # Watch recursively
    """
    from .watcher import FileWatcher
    from rich.console import Console

    console = Console()
    console.print(f"👀 Watching for files matching: [cyan]{pattern}[/cyan]")
    console.print(f"📂 Directory: [yellow]{directory}[/yellow]")

    watcher = FileWatcher(pattern, directory, recursive)

    try:
        asyncio.run(watcher.watch())
    except KeyboardInterrupt:
        console.print("\n👋 Stopped watching")


if __name__ == "__main__":
    main()
