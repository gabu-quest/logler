import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
    # Logler Tour: Investigation Sessions

    When debugging complex issues, you need to track what you've already
    investigated. Logler's `InvestigationSession` helps you maintain context.

    **What you'll learn:**
    1. Creating investigation sessions
    2. Tracking investigation history
    3. Undo/redo operations
    4. Saving and resuming investigations
    5. Generating investigation reports
    6. SQL queries for quick aggregation

    Let's dive in!
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Setting Up - Sample Logs

    Let's create some logs to investigate:
    """
    )
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    # Normal operations
    for i in range(20):
        logs.append(
            {
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "level": "INFO" if i % 4 != 0 else "DEBUG",
                "message": f"Processing request {i}",
                "thread_id": f"worker-{i % 3}",
                "correlation_id": f"req-{i:03d}",
                "component": "api",
            }
        )

    # Inject some errors
    logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=25)).isoformat(),
            "level": "ERROR",
            "message": "Database connection timeout",
            "thread_id": "worker-1",
            "correlation_id": "req-025",
            "component": "database",
            "error_code": "DB_TIMEOUT",
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=26)).isoformat(),
            "level": "ERROR",
            "message": "Failed to process request: database unavailable",
            "thread_id": "worker-1",
            "correlation_id": "req-025",
            "component": "api",
            "error_code": "API_500",
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=30)).isoformat(),
            "level": "WARN",
            "message": "Retrying database connection",
            "thread_id": "worker-1",
            "correlation_id": "req-030",
            "component": "database",
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(seconds=35)).isoformat(),
            "level": "INFO",
            "message": "Database connection restored",
            "thread_id": "worker-1",
            "correlation_id": "req-030",
            "component": "database",
        }
    )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "investigation.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries")
    print("Including 2 errors and 1 warning to investigate")
    return log_file, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Creating an Investigation Session

    An `InvestigationSession` tracks all your analysis steps,
    allowing you to review what you've done and undo if needed.
    """
    )
    return


@app.cell
def _():
    from logler.investigate import InvestigationSession

    return (InvestigationSession,)


@app.cell
def _(InvestigationSession, log_file):
    # Create a new investigation session
    session = InvestigationSession(files=[str(log_file)], name="db_timeout_investigation")

    print("=== Investigation Session Created ===")
    print(f"Name: {session.name}")
    print(f"Files: {session.files}")
    return (session,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Conducting the Investigation

    Each operation is automatically tracked in the session history:
    """
    )
    return


@app.cell
def _(session):
    # Step 1: Search for errors
    print("Step 1: Finding all errors...")
    errors = session.search(level="ERROR")
    print(f"  Found {errors['total_matches']} errors\n")

    # Step 2: Search for database-related logs
    print("Step 2: Finding database logs...")
    db_logs = session.search(query="database")
    print(f"  Found {db_logs['total_matches']} database-related entries\n")

    # Step 3: Follow the correlation ID of the error
    print("Step 3: Following the failed request...")
    timeline = session.follow_thread(correlation_id="req-025")
    print(f"  Found {timeline['total_entries']} entries for req-025")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Viewing Investigation History

    See all the steps you've taken:
    """
    )
    return


@app.cell
def _(session):
    # Get investigation history
    history = session.get_history()

    print("=== Investigation History ===\n")
    for _i, _entry in enumerate(history):
        _op = _entry["operation"]
        _desc = _entry["description"]
        _summary = _entry.get("result_summary", {})

        print(f"{_i + 1}. [{_op}] {_desc}")
        if _summary:
            for _key, _value in _summary.items():
                print(f"      {_key}: {_value}")
        print()
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Undo/Redo Operations

    Made a wrong turn? Undo your last step:
    """
    )
    return


@app.cell
def _(session):
    print(f"Current position in history: {session.current_index + 1}/{len(session.history)}")

    # Undo last operation
    if session.undo():
        print("Undid last operation")
        print(f"Now at position: {session.current_index + 1}/{len(session.history)}")
    else:
        print("Nothing to undo")

    # Undo again
    if session.undo():
        print("Undid another operation")
        print(f"Now at position: {session.current_index + 1}/{len(session.history)}")

    # Redo
    if session.redo():
        print("\nRedid operation")
        print(f"Now at position: {session.current_index + 1}/{len(session.history)}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 6. Adding Notes

    Document your findings as you go:
    """
    )
    return


@app.cell
def _(session):
    # Add investigation notes
    session.add_note("Found database timeout at 10:00:25 - caused by connection pool exhaustion")
    session.add_note("req-025 was affected, subsequent requests recovered after retry")

    print("Notes added to investigation history")

    # View updated history
    print("\n=== Updated History (last 3) ===")
    for _entry in session.get_history()[-3:]:
        print(f"[{_entry['operation']}] {_entry['description']}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 7. Saving and Loading Sessions

    Save your investigation to continue later:
    """
    )
    return


@app.cell
def _(session, temp_dir):
    from pathlib import Path as P

    # Save the session
    save_path = P(temp_dir) / "investigation_session.json"
    session.save(str(save_path))
    print(f"Session saved to: {save_path}")

    # Show what was saved
    import json as _json

    with open(save_path) as _f:
        saved = _json.load(_f)
    print("\nSaved session contains:")
    print(f"  Name: {saved['name']}")
    print(f"  Files: {saved['files']}")
    print(f"  History entries: {len(saved['history'])}")
    return (save_path,)


@app.cell
def _(InvestigationSession, save_path):
    # Load the session back
    loaded_session = InvestigationSession.load(str(save_path))

    print("=== Loaded Session ===")
    print(f"Name: {loaded_session.name}")
    print(f"History entries: {len(loaded_session.history)}")
    print("\nCan continue investigation from where you left off!")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 8. Generating Reports

    Summarize your investigation for documentation or sharing:
    """
    )
    return


@app.cell
def _(session):
    report = session.generate_report(format="markdown", include_evidence=True)

    print("=== Investigation Report (truncated) ===\n")
    _lines = report.splitlines()
    print("\n".join(_lines[:30]))
    if len(_lines) > 30:
        print("\n... (truncated)")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 9. SQL Queries for Aggregation

    Use SQL to summarize large logs quickly (powered by DuckDB).
    """
    )
    return


@app.cell
def _(log_file):
    from logler.investigate import Investigator

    inv = Investigator()
    inv.load_files([str(log_file)])

    rows = inv.sql_query(
        """
        SELECT level, COUNT(*) AS count
        FROM logs
        GROUP BY level
        ORDER BY count DESC
        """
    )

    print("=== SQL: Counts by Level ===")
    for _row in rows:
        print(f"{_row['level']}: {_row['count']}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned how to use Investigation Sessions:

    - **`InvestigationSession(files, name)`** - Create a session
    - **`.search()`, `.follow_thread()`, etc.** - Operations are tracked
    - **`.get_history()`** - View all steps taken
    - **`.undo()` / `.redo()`** - Navigate history
    - **`.add_note()`** - Document findings
    - **`.save()` / `.load()`** - Persist and resume
    - **`.generate_report()`** - Auto-generate a report
    - **`Investigator.sql_query()`** - SQL summaries over logs

    **Key Benefits:**
    - Never lose track of what you've investigated
    - Easy to resume complex debugging sessions
    - Generate reports of your investigation process

    **Next Steps:**
    - **Tour 06**: Flamegraph visualization (performance analysis)
    """
    )
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
