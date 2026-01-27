import marimo

__generated_with = "0.18.4"
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
    return Investigator, get_metadata, search


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

    # Create sample logs with a realistic request mix
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    sample_logs = []
    routes = ["/api/users", "/api/orders", "/api/search", "/api/reports"]
    users = ["alice", "bob", "carol", "dave", "erin"]
    methods = ["GET", "POST"]

    def _add_log(ts, level, message, component, thread_id, correlation_id):
        sample_logs.append(
            {
                "timestamp": ts.isoformat(),
                "level": level,
                "message": message,
                "component": component,
                "thread_id": thread_id,
                "correlation_id": correlation_id,
            }
        )

    request_count = 24
    for _i in range(request_count):
        correlation_id = f"req-{_i:03d}"
        thread_id = f"worker-{_i % 4}"
        route = routes[_i % len(routes)]
        method = methods[_i % len(methods)]
        user = users[_i % len(users)]
        start = base_time + timedelta(seconds=_i * 4)

        _add_log(start, "INFO", f"{method} {route} started", "api", thread_id, correlation_id)
        _add_log(
            start + timedelta(milliseconds=15),
            "DEBUG",
            f"JWT validated for user:{user}",
            "auth",
            thread_id,
            correlation_id,
        )

        query_ms = 40 + (_i % 5) * 20
        _add_log(
            start + timedelta(milliseconds=40),
            "INFO",
            "Database query: SELECT * FROM users",
            "db",
            thread_id,
            correlation_id,
        )

        if _i % 7 == 0:
            slow_ms = query_ms + 220
            _add_log(
                start + timedelta(milliseconds=55),
                "WARN",
                f"Slow query detected: {slow_ms}ms",
                "db",
                thread_id,
                correlation_id,
            )

        cache_result = "HIT" if _i % 4 else "MISS"
        _add_log(
            start + timedelta(milliseconds=80),
            "DEBUG",
            f"Cache {cache_result} for key user:{100 + _i}",
            "cache",
            thread_id,
            correlation_id,
        )

        if _i % 9 == 0:
            _add_log(
                start + timedelta(milliseconds=85),
                "ERROR",
                "Failed to connect to redis: connection refused",
                "cache",
                thread_id,
                correlation_id,
            )
            _add_log(
                start + timedelta(milliseconds=90),
                "INFO",
                "Retrying redis connection in 5s",
                "cache",
                thread_id,
                correlation_id,
            )
            _add_log(
                start + timedelta(milliseconds=120),
                "INFO",
                "Redis connection established",
                "cache",
                thread_id,
                correlation_id,
            )

        if _i == 13:
            _add_log(
                start + timedelta(milliseconds=140),
                "ERROR",
                "Unhandled exception in request handler",
                "api",
                thread_id,
                correlation_id,
            )

        duration_ms = 120 + (_i % 6) * 30 + (120 if _i % 7 == 0 else 0)
        _add_log(
            start + timedelta(milliseconds=duration_ms),
            "INFO",
            f"Request completed in {duration_ms}ms",
            "api",
            thread_id,
            correlation_id,
        )

    for _i in range(6):
        heartbeat_time = base_time + timedelta(seconds=request_count * 4 + _i * 10)
        _add_log(
            heartbeat_time,
            "INFO",
            f"Worker heartbeat {_i}",
            "worker",
            f"worker-{_i % 2}",
            f"job-{_i:03d}",
        )
        if _i == 3:
            _add_log(
                heartbeat_time + timedelta(milliseconds=500),
                "WARN",
                "Queue depth high: 142 pending jobs",
                "worker",
                f"worker-{_i % 2}",
                f"job-{_i:03d}",
            )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "app.log"
    with open(log_file, "w") as f:
        for log in sample_logs:
            f.write(json.dumps(log) + "\n")

    print(f"Created {len(sample_logs)} sample log entries")
    print(f"Log file: {log_file}")
    return log_file, temp_dir


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
        print("\nLog Levels:")
        for _level, _count in meta.get("log_levels", {}).items():
            print(f"  {_level}: {_count}")
        print(f"\nUnique Threads: {meta.get('unique_threads', 0)}")
        print(f"Unique Correlations: {meta.get('unique_correlation_ids', 0)}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Multi-Format Parsing

    Logler parses JSON, plaintext, and syslog-style lines. Here's what it can
    extract from each format.
    """)
    return


@app.cell
def _(temp_dir):
    import json as _json
    from pathlib import Path as _Path
    from logler.parser import LogParser

    parser = LogParser()
    samples = {
        "json": _json.dumps(
            {
                "timestamp": "2024-01-15T10:00:00Z",
                "level": "INFO",
                "message": "User login succeeded",
                "thread_id": "worker-9",
                "correlation_id": "req-900",
                "trace_id": "trace-ff0011",
            }
        ),
        "plain": "2024-01-15 10:00:01 INFO thread=worker-9 correlation_id=req-901 Cache warmed",
        "syslog": "<34>1 2024-01-15T10:00:02Z web-01 app 1234 - - WARN thread=worker-2 correlation_id=req-902 Cache miss",
    }

    print("=== Format Parsing ===")
    for _label, _line in samples.items():
        _entry = parser.parse_line(1, _line)
        _thread = _entry.thread_id or "-"
        _corr = _entry.correlation_id or "-"
        print(
            f"{_label.upper():6} level={_entry.level:<5} thread={_thread:<10} corr={_corr:<8} msg={_entry.message}"
        )

    format_file = _Path(temp_dir) / "formats.log"
    with open(format_file, "w") as _f:
        for _line in samples.values():
            _f.write(_line + "\n")

    print(f"\nWrote mixed-format file: {format_file}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Basic Search

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

    for _r in results["results"]:
        _entry = _r["entry"]
        print(f"[{_entry['level']}] {_entry['message']}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Filtering by Log Level

    Often you want to find just errors or warnings.
    `search()` accepts one level at a time, so we'll run two quick
    searches and combine the results.
    """)
    return


@app.cell
def _(log_file, search):
    # Find all ERROR logs
    error_only_results = search(files=[str(log_file)], level="ERROR", limit=10)

    print(f"Found {error_only_results['total_matches']} ERROR entries:\n")
    for _r in error_only_results["results"]:
        _entry = _r["entry"]
        component = _entry.get("fields", {}).get("component") or _entry.get("service_name")
        print(f"[{_entry['timestamp']}] {_entry['message']}")
        print(f"  Component: {component or 'unknown'}")
        print()
    return


@app.cell
def _(log_file, search):
    # Find all WARN and ERROR logs
    warn_results = search(files=[str(log_file)], level="WARN", limit=50)
    error_level_results = search(files=[str(log_file)], level="ERROR", limit=50)

    combined = warn_results["results"] + error_level_results["results"]
    combined.sort(key=lambda _r: _r["entry"]["timestamp"])

    print(
        f"Found {warn_results['total_matches']} WARN entries and {error_level_results['total_matches']} ERROR entries:\n"
    )
    for _r in combined[:10]:
        _entry = _r["entry"]
        print(f"[{_entry['level']}] {_entry['message']}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Using the Investigator Class

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
    return (inv,)


@app.cell
def _(inv):
    # Search using the investigator
    inv_results = inv.search(query="database")

    print(f"Found {inv_results['total_matches']} matches for 'database'")
    for _r in inv_results["results"]:
        print(f"  {_r['entry']['message']}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Context Around Results

    Sometimes you need to see what happened before and after a log entry.
    Use context lines to get surrounding entries:
    """)
    return


@app.cell
def _(inv, log_file):
    # Find a log line with a redis error and grab context around it
    redis_line = None
    with open(log_file, "r") as _f:
        for _idx, _line in enumerate(_f, start=1):
            if "redis" in _line:
                redis_line = _idx
                break

    context = inv.get_context(
        file=str(log_file),
        line_number=redis_line or 1,
        lines_before=2,
        lines_after=2,
    )

    print("=== Target Entry ===")
    print(f"[{context['target']['level']}] {context['target']['message']}")

    print("\n=== Context Before ===")
    for _entry in context["context_before"]:
        print(f"  [{_entry['level']}] {_entry['message']}")

    print("\n=== Context After ===")
    for _entry in context["context_after"]:
        print(f"  [{_entry['level']}] {_entry['message']}")
    return


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
    - **Tour 04**: Investigation sessions and reports
    - **Tour 05**: Pattern detection
    - **Tour 12**: Multi-file tracing across services
    """)
    return


@app.cell
def _(temp_dir):
    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
