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
    # Logler Tour: Investigation Sessions

    When debugging complex issues, you need to track what you've already
    investigated. Logler's `InvestigationSession` helps you maintain context.

    **What you'll learn:**
    1. Creating investigation sessions
    2. Tracking investigation history
    3. Undo/redo operations
    4. Saving and resuming investigations
    5. Generating investigation reports

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up - Sample Logs

    Let's create some logs to investigate:
    """)
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
        logs.append({
            "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
            "level": "INFO" if i % 4 != 0 else "DEBUG",
            "message": f"Processing request {i}",
            "thread_id": f"worker-{i % 3}",
            "correlation_id": f"req-{i:03d}",
            "component": "api"
        })

    # Inject some errors
    logs.append({
        "timestamp": (base_time + timedelta(seconds=25)).isoformat(),
        "level": "ERROR",
        "message": "Database connection timeout",
        "thread_id": "worker-1",
        "correlation_id": "req-025",
        "component": "database",
        "error_code": "DB_TIMEOUT"
    })

    logs.append({
        "timestamp": (base_time + timedelta(seconds=26)).isoformat(),
        "level": "ERROR",
        "message": "Failed to process request: database unavailable",
        "thread_id": "worker-1",
        "correlation_id": "req-025",
        "component": "api",
        "error_code": "API_500"
    })

    logs.append({
        "timestamp": (base_time + timedelta(seconds=30)).isoformat(),
        "level": "WARN",
        "message": "Retrying database connection",
        "thread_id": "worker-1",
        "correlation_id": "req-030",
        "component": "database"
    })

    logs.append({
        "timestamp": (base_time + timedelta(seconds=35)).isoformat(),
        "level": "INFO",
        "message": "Database connection restored",
        "thread_id": "worker-1",
        "correlation_id": "req-030",
        "component": "database"
    })

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "investigation.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries")
    print(f"Including 2 errors and 1 warning to investigate")
    return Path, base_time, log_file, logs, temp_dir


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Creating an Investigation Session

    An `InvestigationSession` tracks all your analysis steps,
    allowing you to review what you've done and undo if needed.
    """)
    return


@app.cell
def _():
    from logler.investigate import InvestigationSession

    return (InvestigationSession,)


@app.cell
def _(InvestigationSession, log_file):
    # Create a new investigation session
    session = InvestigationSession(
        files=[str(log_file)],
        name="db_timeout_investigation"
    )

    print(f"=== Investigation Session Created ===")
    print(f"Name: {session.name}")
    print(f"Files: {session.files}")
    return (session,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Conducting the Investigation

    Each operation is automatically tracked in the session history:
    """)
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
    print(f"  Found {timeline['total_entries']} entries for req-025\n")

    # Step 4: Look for patterns
    print("Step 4: Finding patterns...")
    patterns = session.find_patterns(min_occurrences=2)
    print(f"  Found {len(patterns.get('patterns', []))} patterns")
    return db_logs, errors, patterns, timeline


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Viewing Investigation History

    See all the steps you've taken:
    """)
    return


@app.cell
def _(session):
    # Get investigation history
    history = session.get_history()

    print("=== Investigation History ===\n")
    for _i, _entry in enumerate(history):
        _op = _entry['operation']
        _desc = _entry['description']
        _summary = _entry.get('result_summary', {})

        print(f"{_i+1}. [{_op}] {_desc}")
        if _summary:
            for _key, _value in _summary.items():
                print(f"      {_key}: {_value}")
        print()
    return (history,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Undo/Redo Operations

    Made a wrong turn? Undo your last step:
    """)
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
    mo.md(r"""
    ## 6. Adding Notes

    Document your findings as you go:
    """)
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
    mo.md(r"""
    ## 7. Saving and Loading Sessions

    Save your investigation to continue later:
    """)
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
    print(f"\nSaved session contains:")
    print(f"  Name: {saved['name']}")
    print(f"  Files: {saved['files']}")
    print(f"  History entries: {len(saved['history'])}")
    return P, json, save_path, saved


@app.cell
def _(InvestigationSession, save_path):
    # Load the session back
    loaded_session = InvestigationSession.load(str(save_path))

    print(f"=== Loaded Session ===")
    print(f"Name: {loaded_session.name}")
    print(f"History entries: {len(loaded_session.history)}")
    print(f"\nCan continue investigation from where you left off!")
    return (loaded_session,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Generating Reports

    Summarize your investigation for documentation or sharing:
    """)
    return


@app.cell
def _(session):
    # Generate a report from history
    print("=" * 60)
    print("INVESTIGATION REPORT")
    print("=" * 60)
    print(f"Name: {session.name}")
    print(f"Files analyzed: {len(session.files)}")
    print()

    print("STEPS TAKEN:")
    for _i, _entry in enumerate(session.get_history(), 1):
        if _entry['operation'] == 'note':
            print(f"  {_i}. NOTE: {_entry['description']}")
        else:
            _summary = _entry.get('result_summary', {})
            _result_str = ", ".join(f"{_k}={_v}" for _k, _v in _summary.items()) if _summary else "completed"
            print(f"  {_i}. {_entry['description']} ({_result_str})")

    print()
    print("FINDINGS:")
    for _entry in session.get_history():
        if _entry['operation'] == 'note':
            _note = _entry.get('params', {}).get('note', '')
            print(f"  - {_note}")
    print("=" * 60)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned how to use Investigation Sessions:

    - **`InvestigationSession(files, name)`** - Create a session
    - **`.search()`, `.follow_thread()`, etc.** - Operations are tracked
    - **`.get_history()`** - View all steps taken
    - **`.undo()` / `.redo()`** - Navigate history
    - **`.add_note()`** - Document findings
    - **`.save()` / `.load()`** - Persist and resume

    **Key Benefits:**
    - Never lose track of what you've investigated
    - Easy to resume complex debugging sessions
    - Generate reports of your investigation process

    **Next Steps:**
    - **Tour 05**: Pattern detection (find recurring issues)
    """)
    return


@app.cell
def _(temp_dir):
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return (shutil,)


if __name__ == "__main__":
    app.run()
