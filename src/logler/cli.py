"""
Command-line interface for Logler.
"""

import click
import sys
from pathlib import Path
from typing import Optional
import asyncio
import socket
from contextlib import closing

from .terminal import TerminalViewer
from .web.app import run_server
from .llm_cli import llm as llm_group


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
@click.option(
    "--auto-port/--no-auto-port",
    default=True,
    help="Pick the next free port if the chosen one is busy",
)
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
def view(
    files: tuple,
    lines: Optional[int],
    follow: bool,
    level: Optional[str],
    grep: Optional[str],
    thread: Optional[str],
    no_color: bool,
):
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
            asyncio.run(
                viewer.view_file(
                    file_path=file_path,
                    lines=lines,
                    follow=follow,
                    level_filter=level,
                    pattern=grep,
                    thread_filter=thread,
                )
            )
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

    console = Console()
    parser = LogParser()

    for file_path in files:
        with open(file_path, "r") as f:
            entries = [parser.parse_line(i + 1, line.rstrip()) for i, line in enumerate(f)]

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
                stats_data["by_thread"][entry.thread_id] = (
                    stats_data["by_thread"].get(entry.thread_id, 0) + 1
                )

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
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--auto-insights", is_flag=True, help="Run automatic insights analysis")
@click.option("--errors", is_flag=True, help="Show only errors with analysis")
@click.option("--patterns", is_flag=True, help="Find repeated patterns")
@click.option("--thread", type=str, help="Follow specific thread ID")
@click.option("--correlation", type=str, help="Follow specific correlation ID")
@click.option(
    "--hierarchy", is_flag=True, help="Show thread hierarchy tree (with --thread or --correlation)"
)
@click.option("--waterfall", is_flag=True, help="Show waterfall timeline (with --hierarchy)")
@click.option("--flamegraph", is_flag=True, help="Show flamegraph visualization (with --hierarchy)")
@click.option(
    "--show-error-flow",
    is_flag=True,
    help="Analyze error propagation through hierarchy (with --hierarchy)",
)
@click.option("--max-depth", type=int, help="Maximum hierarchy depth to display")
@click.option(
    "--min-confidence",
    type=float,
    default=0.0,
    help="Minimum confidence for hierarchy detection (0.0-1.0)",
)
@click.option("--context", type=int, default=3, help="Number of context lines (default: 3)")
@click.option(
    "--output",
    type=click.Choice(["full", "summary", "count", "compact"]),
    default="summary",
    help="Output format (default: summary)",
)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option(
    "--min-occurrences", type=int, default=3, help="Minimum pattern occurrences (default: 3)"
)
def investigate(
    files: tuple,
    auto_insights: bool,
    errors: bool,
    patterns: bool,
    thread: Optional[str],
    correlation: Optional[str],
    hierarchy: bool,
    waterfall: bool,
    flamegraph: bool,
    show_error_flow: bool,
    max_depth: Optional[int],
    min_confidence: float,
    context: int,
    output: str,
    output_json: bool,
    min_occurrences: int,
):
    """
    Investigate log files with smart analysis and insights.

    Examples:
        logler investigate app.log --auto-insights     # Auto-detect issues
        logler investigate app.log --errors            # Analyze errors
        logler investigate app.log --patterns          # Find repeated patterns
        logler investigate app.log --thread worker-1   # Follow specific thread
        logler investigate app.log --correlation req-123  # Follow request
        logler investigate app.log --thread req-123 --hierarchy   # Show hierarchy tree
        logler investigate app.log --thread req-123 --hierarchy --waterfall  # Show waterfall timeline
        logler investigate app.log --thread req-123 --hierarchy --flamegraph  # Show flamegraph
        logler investigate app.log --hierarchy --show-error-flow  # Analyze error propagation
        logler investigate app.log --output summary    # Token-efficient output
    """
    from .investigate import (
        analyze_with_insights,
        search,
        find_patterns,
        follow_thread,
        follow_thread_hierarchy,
        get_hierarchy_summary,
        analyze_error_flow,
        format_error_flow,
    )
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()
    file_list = list(files)

    try:
        # Auto-insights mode (most powerful)
        if auto_insights:
            console.print("[bold cyan]🎯 Running automatic insights analysis...[/bold cyan]\n")
            result = analyze_with_insights(files=file_list, auto_investigate=True)

            if output_json:
                console.print_json(data=result)
                return

            # Display overview
            overview = result["overview"]
            console.print(
                Panel(
                    f"[bold]Total Logs:[/bold] {overview['total_logs']}\n"
                    f"[bold]Error Count:[/bold] {overview['error_count']}\n"
                    f"[bold]Error Rate:[/bold] {overview['error_rate']:.1%}\n"
                    f"[bold]Log Levels:[/bold] {overview['log_levels']}",
                    title="📊 Overview",
                    border_style="cyan",
                )
            )

            # Display insights
            if result["insights"]:
                console.print("\n[bold cyan]💡 Automatic Insights[/bold cyan]\n")
                for i, insight in enumerate(result["insights"], 1):
                    severity_color = {"high": "red", "medium": "yellow", "low": "green"}.get(
                        insight["severity"], "white"
                    )

                    severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                        insight["severity"], "⚪"
                    )

                    console.print(
                        f"{severity_icon} [bold {severity_color}]Insight #{i}:[/bold {severity_color}] {insight['type']}"
                    )
                    console.print(
                        f"   [dim]Severity:[/dim] [{severity_color}]{insight['severity'].upper()}[/{severity_color}]"
                    )
                    console.print(f"   [dim]Description:[/dim] {insight['description']}")
                    console.print(f"   [dim]Suggestion:[/dim] {insight['suggestion']}\n")

            # Display suggestions
            if result["suggestions"]:
                console.print("[bold cyan]📝 Suggestions[/bold cyan]\n")
                for i, suggestion in enumerate(result["suggestions"], 1):
                    console.print(f"  {i}. {suggestion}")

            # Display next steps
            if result["next_steps"]:
                console.print("\n[bold cyan]🚀 Next Steps[/bold cyan]\n")
                for i, step in enumerate(result["next_steps"], 1):
                    console.print(f"  {i}. {step}")

        # Pattern detection mode
        elif patterns:
            console.print(
                f"[bold cyan]🔍 Finding repeated patterns (min {min_occurrences} occurrences)...[/bold cyan]\n"
            )
            result = find_patterns(files=file_list, min_occurrences=min_occurrences)

            if output_json:
                console.print_json(data=result)
                return

            pattern_list = result.get("patterns", [])
            if pattern_list:
                table = Table(title=f"Found {len(pattern_list)} Patterns")
                table.add_column("Pattern", style="cyan", no_wrap=False)
                table.add_column("Count", justify="right", style="green")
                table.add_column("First Seen", style="yellow")
                table.add_column("Last Seen", style="yellow")

                for pattern in pattern_list[:20]:  # Show top 20
                    pattern_text = pattern.get("pattern", "")[:80]
                    count = pattern.get("occurrences", 0)
                    first = pattern.get("first_seen", "N/A")
                    last = pattern.get("last_seen", "N/A")
                    table.add_row(pattern_text, str(count), first, last)

                console.print(table)
            else:
                console.print("[yellow]No repeated patterns found.[/yellow]")

        # Thread/correlation following mode
        elif thread or correlation:
            identifier = thread or correlation
            id_type = "thread" if thread else "correlation"

            # Hierarchy mode
            if hierarchy:
                console.print(
                    f"[bold cyan]🌳 Building hierarchy for {id_type}: {identifier}...[/bold cyan]\n"
                )

                try:
                    hier_result = follow_thread_hierarchy(
                        files=file_list,
                        root_identifier=identifier,
                        max_depth=max_depth,
                        min_confidence=min_confidence,
                    )

                    if output_json:
                        console.print_json(data=hier_result)
                        return

                    # Import tree formatter
                    from .tree_formatter import format_tree, format_waterfall, format_flamegraph

                    # Show summary first
                    summary = get_hierarchy_summary(hier_result)
                    console.print(summary)
                    console.print()

                    # Show tree visualization
                    if waterfall:
                        console.print("[bold cyan]📊 Waterfall Timeline[/bold cyan]\n")
                        waterfall_str = format_waterfall(hier_result, width=100)
                        console.print(waterfall_str)
                    elif flamegraph:
                        console.print("[bold cyan]🔥 Flamegraph Visualization[/bold cyan]\n")
                        flamegraph_str = format_flamegraph(hier_result, width=100)
                        console.print(flamegraph_str)
                    else:
                        console.print("[bold cyan]🌲 Hierarchy Tree[/bold cyan]\n")
                        tree_str = format_tree(
                            hier_result,
                            mode="detailed",
                            show_duration=True,
                            show_errors=True,
                            max_depth=max_depth,
                            use_colors=True,
                        )
                        console.print(tree_str)

                    # Show error flow analysis if requested
                    if show_error_flow:
                        console.print()
                        console.print("[bold cyan]🔍 Error Flow Analysis[/bold cyan]\n")
                        error_analysis = analyze_error_flow(hier_result)
                        if output_json:
                            console.print_json(data=error_analysis)
                        else:
                            error_flow_str = format_error_flow(error_analysis)
                            console.print(error_flow_str)

                except Exception as e:
                    console.print(f"[red]❌ Error building hierarchy: {e}[/red]")
                    console.print("[yellow]Falling back to regular thread following...[/yellow]\n")
                    hierarchy = False  # Fall through to regular mode

            # Regular thread following mode
            if not hierarchy:
                console.print(f"[bold cyan]🧵 Following {id_type}: {identifier}...[/bold cyan]\n")

                result = follow_thread(
                    files=file_list, thread_id=thread, correlation_id=correlation
                )

                if output_json:
                    console.print_json(data=result)
                    return

                entries = result.get("entries", [])
                total = result.get("total_entries", len(entries))
                duration = result.get("duration_ms", 0)

                console.print(f"[bold]Found {total} entries[/bold]")
                if duration:
                    console.print(f"[bold]Duration:[/bold] {duration}ms\n")

                # Display entries
                for entry in entries[:50]:  # Limit display to 50
                    timestamp = entry.get("timestamp", "N/A")
                    level = entry.get("level", "INFO")
                    message = entry.get("message", "")[:100]

                    level_color = {
                        "ERROR": "red",
                        "FATAL": "red",
                        "WARN": "yellow",
                        "WARNING": "yellow",
                        "INFO": "cyan",
                        "DEBUG": "dim",
                        "TRACE": "dim",
                    }.get(level, "white")

                    console.print(
                        f"[dim]{timestamp}[/dim] [{level_color}]{level:8s}[/{level_color}] {message}"
                    )

                if len(entries) > 50:
                    console.print(f"\n[dim]... and {len(entries) - 50} more entries[/dim]")

        # Error analysis mode
        elif errors:
            console.print("[bold cyan]❌ Analyzing errors...[/bold cyan]\n")
            result = search(
                files=file_list, level="ERROR", context_lines=context, output_format=output
            )

            if output_json:
                console.print_json(data=result)
                return

            if output == "summary":
                total = result.get("total_matches", 0)
                unique = result.get("unique_messages", 0)
                console.print(f"[bold]Total Errors:[/bold] {total}")
                console.print(f"[bold]Unique Messages:[/bold] {unique}\n")

                top_messages = result.get("top_messages", [])
                if top_messages:
                    table = Table(title="Top Error Messages")
                    table.add_column("Message", style="red", no_wrap=False)
                    table.add_column("Count", justify="right", style="green")
                    table.add_column("First Seen", style="yellow")

                    for msg in top_messages[:10]:
                        message = msg.get("message", "")[:80]
                        count = msg.get("count", 0)
                        first = msg.get("first_seen", "N/A")
                        table.add_row(message, str(count), first)

                    console.print(table)

            elif output == "count":
                console.print_json(data=result)

            elif output == "compact":
                matches = result.get("matches", [])
                for match in matches[:50]:
                    time = match.get("time", "N/A")
                    msg = match.get("msg", "")
                    console.print(f"[dim]{time}[/dim] [red]ERROR[/red] {msg}")

            else:  # full
                results = result.get("results", [])
                for item in results[:50]:
                    entry = item.get("entry", {})
                    timestamp = entry.get("timestamp", "N/A")
                    message = entry.get("message", "")
                    console.print(f"[dim]{timestamp}[/dim] [red]ERROR[/red] {message}")

        # Default search mode
        else:
            console.print("[bold cyan]🔍 Searching logs...[/bold cyan]\n")
            result = search(files=file_list, context_lines=context, output_format=output)

            if output_json:
                console.print_json(data=result)
                return

            total = result.get("total_matches", 0)
            console.print(f"[bold]Total matches:[/bold] {total}\n")

            if output == "summary":
                console.print_json(data=result)
            elif output == "count":
                console.print_json(data=result)
            else:
                results = result.get("results", [])
                for item in results[:50]:
                    entry = item.get("entry", {})
                    timestamp = entry.get("timestamp", "N/A")
                    level = entry.get("level", "INFO")
                    message = entry.get("message", "")[:100]
                    console.print(f"[dim]{timestamp}[/dim] {level:8s} {message}")

    except Exception as e:
        console.print(f"[red]❌ Error:[/red] {e}", err=True)
        if "--debug" in sys.argv:
            import traceback

            traceback.print_exc()
        sys.exit(1)


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


# Register the LLM command group
main.add_command(llm_group)


if __name__ == "__main__":
    main()
