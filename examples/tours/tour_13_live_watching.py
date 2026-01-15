import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
    # Tour 13: Live Log Watching - Real-Time Analysis

    **Watch logs as they happen. Detect anomalies in real-time.**

    In production, logs are constantly flowing. You need to:
    - Tail logs as they're written
    - Detect error spikes immediately
    - Alert on anomalies

    Logler's `LogReader` supports live tailing with `follow=True`.

    **In this tour:**
    1. Start a background log writer (simulates a running service)
    2. Watch logs stream in real-time
    3. Detect and alert on errors
    4. Count patterns as they arrive
    """
    )
    return


@app.cell
def _():
    import json
    import tempfile
    import threading
    import time
    from pathlib import Path
    from datetime import datetime, timezone

    # Create temp directory
    temp_dir = tempfile.mkdtemp()
    live_log = Path(temp_dir) / "live_service.log"

    # Touch the file
    live_log.touch()

    print(f"Live log file: {live_log}")
    return (
        Path,
        datetime,
        json,
        live_log,
        temp_dir,
        tempfile,
        threading,
        time,
        timezone,
    )


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. The Log Writer (Simulated Service)

    This function simulates a running service writing logs.
    - Normal INFO logs most of the time
    - Occasional WARN logs
    - Periodic ERROR bursts (simulating incidents)
    """
    )
    return


@app.cell
def _(datetime, json, timezone):
    def make_log_entry(i, level="INFO"):
        messages = {
            "INFO": [
                "Request processed successfully",
                "User session started",
                "Cache hit for key",
                "Database query completed",
                "API response sent",
            ],
            "WARN": [
                "High memory usage detected",
                "Slow query warning: >100ms",
                "Rate limit approaching",
                "Connection pool running low",
            ],
            "ERROR": [
                "Database connection failed",
                "Timeout waiting for response",
                "Authentication failed",
                "Service unavailable",
            ],
        }

        msg = messages[level][i % len(messages[level])]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": msg,
            "request_id": f"req-{i:05d}",
            "service": "live-demo-service",
        }

    print("Log entry generator ready")
    return (make_log_entry,)


@app.cell
def _(json, make_log_entry, time):
    def log_writer(path, stop_event, total_written):
        """Background writer that simulates a live service."""
        with open(path, "a") as f:
            i = 0
            while not stop_event.is_set() and i < 50:  # Write up to 50 logs
                # Determine log level based on pattern
                if i >= 30 and i < 40:
                    # Error burst from log 30-39
                    level = "ERROR"
                elif i % 10 == 0:
                    level = "WARN"
                else:
                    level = "INFO"

                entry = make_log_entry(i, level)
                f.write(json.dumps(entry) + "\n")
                f.flush()

                total_written[0] = i + 1
                i += 1
                time.sleep(0.15)  # 150ms between logs

    print("Log writer function defined")
    return (log_writer,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Start the Background Writer

    We'll start a background thread that writes logs every 150ms.
    This simulates a real service running in production.
    """
    )
    return


@app.cell
def _(live_log, log_writer, threading):
    # Control objects
    stop_event = threading.Event()
    total_written = [0]

    # Start the writer thread
    writer_thread = threading.Thread(target=log_writer, args=(live_log, stop_event, total_written))
    writer_thread.start()

    print("Background log writer started!")
    print("Logs are being written every 150ms...")
    return stop_event, total_written, writer_thread


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Watch Logs in Real-Time

    Now we use `LogReader.tail(follow=True)` to stream logs as they arrive.

    **Watch for:**
    - Normal INFO logs
    - WARN indicators
    - ERROR bursts (the incident simulation!)
    """
    )
    return


@app.cell
def _(json, live_log, stop_event, time, total_written):
    from logler import LogReader

    reader = LogReader(str(live_log))

    # Counters for real-time stats
    stats = {"INFO": 0, "WARN": 0, "ERROR": 0}
    recent_errors = []

    print("=" * 60)
    print("LIVE LOG STREAM")
    print("=" * 60)

    # Read with follow mode (limited iterations for demo)
    lines_read = 0
    max_lines = 50

    for line in reader.tail(num_lines=0, follow=True):
        if lines_read >= max_lines:
            break

        try:
            _entry = json.loads(line)
            _level = _entry.get("level", "INFO")
            _msg = _entry.get("message", "")[:50]

            stats[_level] = stats.get(_level, 0) + 1

            # Visual indicators
            if _level == "ERROR":
                print(f"🚨 ERROR | {_msg}")
                recent_errors.append(_entry)
            elif _level == "WARN":
                print(f"⚠️  WARN  | {_msg}")
            else:
                print(f"   INFO  | {_msg}")

            lines_read += 1

        except json.JSONDecodeError:
            continue

        # Brief pause to let more logs arrive
        time.sleep(0.05)

    # Stop the writer
    stop_event.set()

    print("\n" + "=" * 60)
    print(f"Stream ended. Total logs written: {total_written[0]}")
    return (
        LogReader,
        lines_read,
        max_lines,
        reader,
        recent_errors,
        stats,
    )


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Real-Time Statistics

    As logs stream in, we tracked statistics.
    In production, you'd use this for dashboards and alerts.
    """
    )
    return


@app.cell
def _(recent_errors, stats):
    print("=" * 60)
    print("REAL-TIME STATISTICS")
    print("=" * 60)

    print("\nLog Level Distribution:")
    total = sum(stats.values())
    for _level, _count in stats.items():
        _pct = (_count / total * 100) if total > 0 else 0
        _bar = "█" * int(_pct / 5)
        print(f"  {_level:5}: {_count:3} ({_pct:5.1f}%) {_bar}")

    print(f"\nTotal logs processed: {total}")

    if recent_errors:
        error_rate = len(recent_errors) / total * 100
        print(f"\n⚠️  Error rate: {error_rate:.1f}%")

        if error_rate > 10:
            print("🚨 ALERT: Error rate exceeded 10% threshold!")

        print(f"\nRecent errors ({len(recent_errors)}):")
        for _err in recent_errors[-5:]:
            print(f"  - {_err['message']}")
    return (error_rate, total)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Anomaly Detection Pattern

    In real production use, you'd implement patterns like:

    ```python
    # Sliding window error detection
    error_window = []
    WINDOW_SIZE = 60  # seconds
    ERROR_THRESHOLD = 10  # errors per minute

    for line in reader.tail(follow=True):
        entry = json.loads(line)
        now = datetime.now()

        if entry['level'] == 'ERROR':
            error_window.append(now)

        # Prune old entries
        error_window = [t for t in error_window
                       if (now - t).seconds < WINDOW_SIZE]

        # Check threshold
        if len(error_window) > ERROR_THRESHOLD:
            send_alert("Error spike detected!")
            error_window.clear()
    ```

    This is how production monitoring systems work!
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned real-time log watching:

    - **`LogReader.tail(follow=True)`** - Stream logs as they're written
    - **Real-time counting** - Track stats as logs flow
    - **Anomaly detection** - Alert on error spikes
    - **Pattern matching** - Filter and route in real-time

    **Production use cases:**
    - Live dashboards
    - PagerDuty/Slack alerts
    - Auto-scaling triggers
    - Security monitoring

    **Next Steps:**
    - **Tour 14**: Performance at scale (10,000+ entries)
    """
    )
    return


@app.cell
def _(stop_event, temp_dir, writer_thread):
    import shutil

    # Make sure writer is stopped
    stop_event.set()
    writer_thread.join(timeout=2)

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return (shutil,)


if __name__ == "__main__":
    app.run()
