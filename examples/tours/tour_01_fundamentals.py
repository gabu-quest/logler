import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(r"""
    # Logler Tour: Fundamentals

    Welcome to Logler! This interactive notebook will teach you the fundamentals
    of this high-performance log investigation tool built with Rust + Python.

    **What you'll learn:**
    1. Loading log files and getting metadata
    2. Basic search operations
    3. Understanding log formats (JSON, plaintext, syslog)
    4. Filtering by log level
    5. Working with results

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up

    First, let's import Logler and check that the Rust backend is available.
    The Rust backend provides blazing-fast log parsing and indexing.
    """)
    return


@app.cell
def _():
    from logler.investigate import (
        search,
        get_metadata,
        Investigator,
        RUST_AVAILABLE,
    )

    print(f"Rust backend available: {RUST_AVAILABLE}")
    if RUST_AVAILABLE:
        print("Ready to process logs at maximum speed!")
    else:
        print("Warning: Rust backend not available, some features may be limited")
    return Investigator, RUST_AVAILABLE, get_metadata, search


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Creating Sample Logs

    For this tour, we'll create some sample JSON logs to work with.
    Logler supports multiple formats, but JSON logs are the richest.
    """)
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    # Create sample logs
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    sample_logs = []

    messages = [
        ("INFO", "Application starting up", "main"),
        ("DEBUG", "Loading configuration from /etc/app/config.yaml", "config"),
        ("INFO", "Connected to database", "db"),
        ("DEBUG", "Executing query: SELECT * FROM users", "db"),
        ("INFO", "User alice@example.com logged in", "auth"),
        ("WARN", "Rate limit approaching for API endpoint /api/users", "api"),
        ("INFO", "Processing batch job #1234", "worker"),
        ("ERROR", "Failed to connect to redis: connection refused", "cache"),
        ("INFO", "Retrying redis connection in 5s", "cache"),
        ("INFO", "Redis connection established", "cache"),
        ("DEBUG", "Cache hit for key: user:123", "cache"),
        ("INFO", "Request completed in 45ms", "api"),
        ("WARN", "Slow query detected: 250ms", "db"),
        ("ERROR", "Unhandled exception in request handler", "api"),
        ("INFO", "Application shutting down gracefully", "main"),
    ]

    for i, (level, message, component) in enumerate(messages):
        sample_logs.append({
            "timestamp": (base_time + timedelta(seconds=i * 10)).isoformat(),
            "level": level,
            "message": message,
            "component": component,
            "thread_id": f"worker-{i % 3}",
            "correlation_id": f"req-{i // 5:03d}",
        })

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "app.log"
    with open(log_file, "w") as f:
        for log in sample_logs:
            f.write(json.dumps(log) + "\n")

    print(f"Created {len(sample_logs)} sample log entries")
    print(f"Log file: {log_file}")
    return Path, base_time, json, log_file, sample_logs, temp_dir, tempfile


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Getting File Metadata

    Before searching, let's understand what's in our log file.
    The `get_metadata()` function provides useful information about the logs.
    """)
    return


@app.cell
def _(get_metadata, log_file):
    # Get metadata about the log file
    metadata = get_metadata([str(log_file)])

    print("=== Log File Metadata ===")
    for meta in metadata:
        print(f"Path: {meta['path']}")
        print(f"Lines: {meta['lines']}")
        print(f"Format: {meta['format']}")
        print(f"Size: {meta['size_bytes']} bytes")
        print(f"\nLog Levels:")
        for level, count in meta.get('log_levels', {}).items():
            print(f"  {level}: {count}")
        print(f"\nUnique Threads: {meta.get('unique_threads', 0)}")
        print(f"Unique Correlations: {meta.get('unique_correlation_ids', 0)}")
    return (metadata,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Basic Search

    Now let's search our logs! The `search()` function is the primary way
    to find entries. You can search by:
    - Text query (searches message content)
    - Log level
    - Limit (max results)
    """)
    return


@app.cell
def _(log_file, search):
    # Search for all logs containing "redis"
    results = search(files=[str(log_file)], query="redis", limit=10)

    print(f"Found {results['total_matches']} matches for 'redis'")
    print(f"Search time: {results['search_time_ms']}ms\n")

    for r in results['results']:
        entry = r['entry']
        print(f"[{entry['level']}] {entry['message']}")
    return (results,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Filtering by Log Level

    Often you want to find just errors or warnings.
    Use the `level` parameter to filter:
    """)
    return


@app.cell
def _(log_file, search):
    # Find all ERROR logs
    errors = search(files=[str(log_file)], level="ERROR", limit=10)

    print(f"Found {errors['total_matches']} ERROR entries:\n")
    for r in errors['results']:
        entry = r['entry']
        print(f"[{entry['timestamp']}] {entry['message']}")
        print(f"  Component: {entry.get('component', 'unknown')}")
        print()
    return (errors,)


@app.cell
def _(log_file, search):
    # Find all WARN and ERROR logs
    warnings = search(files=[str(log_file)], level="WARN", limit=10)

    print(f"Found {warnings['total_matches']} WARN entries:\n")
    for r in warnings['results']:
        entry = r['entry']
        print(f"[{entry['level']}] {entry['message']}")
    return (warnings,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Using the Investigator Class

    For more advanced operations, use the `Investigator` class.
    It keeps files loaded in memory for faster repeated queries.
    """)
    return


@app.cell
def _(Investigator, log_file):
    # Create an investigator and load the log file
    inv = Investigator()
    inv.load_files([str(log_file)])

    print("Investigator loaded!")
    print(f"Files: {[str(log_file)]}")

    # Get metadata through the investigator
    inv_metadata = inv.get_metadata()
    print(f"Total lines indexed: {inv_metadata[0]['lines']}")
    return inv, inv_metadata


@app.cell
def _(inv):
    # Search using the investigator
    inv_results = inv.search(query="database")

    print(f"Found {inv_results['total_matches']} matches for 'database'")
    for r in inv_results['results']:
        print(f"  {r['entry']['message']}")
    return (inv_results,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Context Around Results

    Sometimes you need to see what happened before and after a log entry.
    Use context lines to get surrounding entries:
    """)
    return


@app.cell
def _(inv, log_file):
    # Get context around a specific line
    context = inv.get_context(
        file=str(log_file),
        line_number=8,  # The ERROR about redis
        lines_before=2,
        lines_after=2
    )

    print("=== Target Entry ===")
    print(f"[{context['target']['level']}] {context['target']['message']}")

    print("\n=== Context Before ===")
    for entry in context['context_before']:
        print(f"  [{entry['level']}] {entry['message']}")

    print("\n=== Context After ===")
    for entry in context['context_after']:
        print(f"  [{entry['level']}] {entry['message']}")
    return (context,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned the fundamentals of Logler:

    - **`get_metadata(files)`** - Get information about log files
    - **`search(files, query, level, limit)`** - Find log entries
    - **`Investigator`** - Keep files loaded for faster repeated queries
    - **Context** - See surrounding log entries

    **Next Steps:**
    - **Tour 02**: Thread and correlation tracking
    - **Tour 03**: Hierarchy visualization
    - **Tour 04**: Investigation sessions
    - **Tour 05**: Pattern detection
    """)
    return


@app.cell
def _(temp_dir):
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return (shutil,)


if __name__ == "__main__":
    app.run()
