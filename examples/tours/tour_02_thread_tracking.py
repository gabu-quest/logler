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
    # Logler Tour: Thread & Correlation Tracking

    In distributed systems, a single request often spans multiple threads,
    services, and components. Logler helps you follow these execution flows.

    **What you'll learn:**
    1. Following threads through logs
    2. Tracking correlation IDs across services
    3. Trace ID tracking for distributed systems
    4. Timeline reconstruction
    5. Comparing parallel executions

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up - Microservice Simulation

    We'll create logs that simulate a request flowing through multiple services,
    similar to what you'd see in a real microservice architecture.
    """)
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    # Simulate requests flowing through microservices
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    def _add_event(offset_ms, level, message, service, thread_id, correlation_id, trace_id):
        logs.append(
            {
                "timestamp": (base_time + timedelta(milliseconds=offset_ms)).isoformat(),
                "level": level,
                "message": message,
                "service": service,
                "component": service,
                "thread_id": thread_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            }
        )

    request_specs = [
        {
            "correlation_id": "req-001",
            "trace_id": "trace-abc123",
            "user": "alice",
            "amount": 99.99,
            "sku": "SKU-12345",
            "qty": 2,
            "status": "success",
            "offset_ms": 0,
            "thread_suffix": 1,
        },
        {
            "correlation_id": "req-002",
            "trace_id": "trace-def456",
            "user": "bob",
            "amount": 49.99,
            "sku": "SKU-54321",
            "qty": 1,
            "status": "failed",
            "offset_ms": 1200,
            "thread_suffix": 2,
        },
        {
            "correlation_id": "req-003",
            "trace_id": "trace-ghi789",
            "user": "carol",
            "amount": 19.99,
            "sku": "SKU-88888",
            "qty": 1,
            "status": "success",
            "offset_ms": 2400,
            "thread_suffix": 3,
        },
    ]

    for _spec in request_specs:
        _offset = _spec["offset_ms"]
        _suffix = _spec["thread_suffix"]
        _cid = _spec["correlation_id"]
        _tid = _spec["trace_id"]
        _user = _spec["user"]
        _sku = _spec["sku"]
        _qty = _spec["qty"]
        _amount = _spec["amount"]

        _add_event(
            _offset + 0,
            "INFO",
            "Received POST /api/orders",
            "api-gateway",
            f"http-{_suffix}",
            _cid,
            _tid,
        )
        _add_event(
            _offset + 5,
            "DEBUG",
            "Validating JWT token",
            "auth-service",
            f"auth-pool-{_suffix}",
            _cid,
            _tid,
        )
        _add_event(
            _offset + 15,
            "INFO",
            f"Token validated for user:{_user}",
            "auth-service",
            f"auth-pool-{_suffix}",
            _cid,
            _tid,
        )
        _add_event(
            _offset + 20,
            "DEBUG",
            f"Checking inventory for {_sku}",
            "inventory-service",
            f"inv-worker-{_suffix}",
            _cid,
            _tid,
        )
        _add_event(
            _offset + 45,
            "INFO",
            f"Inventory reserved: {_qty} units",
            "inventory-service",
            f"inv-worker-{_suffix}",
            _cid,
            _tid,
        )
        _add_event(
            _offset + 50,
            "INFO",
            f"Processing payment ${_amount:.2f}",
            "payment-service",
            f"payment-{_suffix}",
            _cid,
            _tid,
        )

        if _spec["status"] == "success":
            _add_event(
                _offset + 200,
                "INFO",
                f"Payment authorized: txn-{700 + _suffix}",
                "payment-service",
                f"payment-{_suffix}",
                _cid,
                _tid,
            )
            _add_event(
                _offset + 210,
                "INFO",
                f"Order created: order-{400 + _suffix}",
                "order-service",
                f"order-proc-{_suffix}",
                _cid,
                _tid,
            )
            _add_event(
                _offset + 215,
                "INFO",
                "Request completed: 201 Created",
                "api-gateway",
                f"http-{_suffix}",
                _cid,
                _tid,
            )
        else:
            _add_event(
                _offset + 350,
                "ERROR",
                "Payment declined: insufficient funds",
                "payment-service",
                f"payment-{_suffix}",
                _cid,
                _tid,
            )
            _add_event(
                _offset + 355,
                "WARN",
                "Rolling back inventory reservation",
                "inventory-service",
                f"inv-worker-{_suffix}",
                _cid,
                _tid,
            )
            _add_event(
                _offset + 360,
                "INFO",
                "Request completed: 402 Payment Required",
                "api-gateway",
                f"http-{_suffix}",
                _cid,
                _tid,
            )

    # Sort by timestamp (simulating collected logs)
    logs.sort(key=lambda x: x["timestamp"])

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "microservices.log"
    with open(log_file, "w") as f:
        for log in logs:
            f.write(json.dumps(log) + "\n")

    service_count = len({log["service"] for log in logs})
    print(f"Created {len(logs)} log entries from {service_count} services")
    print("Correlation IDs: req-001 (success), req-002 (failed), req-003 (success)")
    return log_file, temp_dir


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Following a Thread

    A thread represents a single execution context. Use `follow_thread()`
    to get all logs from a specific thread, in chronological order.
    """)
    return


@app.cell
def _():
    from datetime import datetime as _dt
    from logler.investigate import follow_thread

    def format_duration(timeline):
        duration = timeline.get("duration_ms")
        if duration is None:
            entries = timeline.get("entries", [])
            if len(entries) >= 2:
                try:
                    start = _dt.fromisoformat(entries[0]["timestamp"].replace("Z", "+00:00"))
                    end = _dt.fromisoformat(entries[-1]["timestamp"].replace("Z", "+00:00"))
                    duration = (end - start).total_seconds() * 1000
                except Exception:
                    duration = None
        return "N/A" if duration is None else f"{duration:.0f}ms"

    def service_label(entry):
        return (
            entry.get("service_name")
            or entry.get("fields", {}).get("component")
            or entry.get("service")
            or "unknown"
        )

    return follow_thread, format_duration, service_label


@app.cell
def _(follow_thread, log_file, format_duration):
    # Follow the payment-1 thread (successful payment)
    timeline = follow_thread(files=[str(log_file)], thread_id="payment-1")

    print("=== Thread: payment-1 ===")
    print(f"Total entries: {timeline['total_entries']}")
    print(f"Duration: {format_duration(timeline)}\n")

    for _entry in timeline["entries"]:
        _ts = _entry["timestamp"].split("T")[1][:12]
        print(f"[{_ts}] [{_entry['level']}] {_entry['message']}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Following a Correlation ID

    Correlation IDs track a single request across all services and threads.
    This is essential for debugging distributed systems.
    """)
    return


@app.cell
def _(follow_thread, log_file, format_duration, service_label):
    # Follow the successful order request
    request_timeline = follow_thread(files=[str(log_file)], correlation_id="req-001")

    print("=== Request: req-001 (Successful Order) ===")
    print(f"Total entries: {request_timeline['total_entries']}")
    print(f"Duration: {format_duration(request_timeline)}")
    services = sorted({service_label(_e) for _e in request_timeline["entries"]})
    print(f"Services: {', '.join(services)}\n")

    for _entry in request_timeline["entries"]:
        _ts = _entry["timestamp"].split("T")[1][:12]
        _svc = service_label(_entry)
        print(f"[{_ts}] [{_svc:20}] [{_entry['level']:5}] {_entry['message']}")
    return (request_timeline,)


@app.cell
def _(follow_thread, log_file, format_duration, service_label):
    # Follow the failed order request
    failed_timeline = follow_thread(files=[str(log_file)], correlation_id="req-002")

    print("=== Request: req-002 (Failed Order) ===")
    print(f"Total entries: {failed_timeline['total_entries']}")
    print(f"Duration: {format_duration(failed_timeline)}\n")

    for _entry in failed_timeline["entries"]:
        _ts = _entry["timestamp"].split("T")[1][:12]
        _svc = service_label(_entry)
        _level = _entry["level"]
        # Highlight errors
        _marker = ">>>" if _level == "ERROR" else "   "
        print(f"{_marker} [{_ts}] [{_svc:20}] [{_level:5}] {_entry['message']}")
    return (failed_timeline,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Following a Trace ID

    In OpenTelemetry-style systems, trace IDs connect all operations
    for a single distributed transaction.
    """)
    return


@app.cell
def _(follow_thread, log_file, service_label):
    # Follow by trace ID
    trace_timeline = follow_thread(files=[str(log_file)], trace_id="trace-abc123")

    print("=== Trace: trace-abc123 ===")
    print(f"Total entries: {trace_timeline['total_entries']}")

    # Group by service
    by_service = {}
    for _entry in trace_timeline["entries"]:
        _svc = service_label(_entry)
        if _svc not in by_service:
            by_service[_svc] = []
        by_service[_svc].append(_entry)

    print(f"\nServices involved: {list(by_service.keys())}")
    for _svc, _entries in by_service.items():
        print(f"  {_svc}: {len(_entries)} entries")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Comparing Parallel Requests

    When debugging, you often want to compare a successful request
    with a failed one. Let's analyze the differences:
    """)
    return


@app.cell
def _(failed_timeline, request_timeline, format_duration, service_label):
    print("=== Comparison: req-001 vs req-002 ===\n")

    success = request_timeline
    failure = failed_timeline

    print(f"{'Metric':<25} {'Success (req-001)':<20} {'Failure (req-002)':<20}")
    print("-" * 65)
    print(f"{'Total entries':<25} {success['total_entries']:<20} {failure['total_entries']:<20}")
    print(
        f"{'Duration (ms)':<25} {format_duration(success):<20} {format_duration(failure):<20}"
    )

    # Count by level
    def count_levels(timeline):
        counts = {}
        for _e in timeline["entries"]:
            _lvl = _e["level"]
            counts[_lvl] = counts.get(_lvl, 0) + 1
        return counts

    success_levels = count_levels(success)
    failure_levels = count_levels(failure)

    print(f"\n{'Level Breakdown:':<25}")
    for level in ["INFO", "DEBUG", "WARN", "ERROR"]:
        s_count = success_levels.get(level, 0)
        f_count = failure_levels.get(level, 0)
        print(f"  {level:<23} {s_count:<20} {f_count:<20}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Finding Where Things Went Wrong

    Let's pinpoint exactly where the failed request diverged:
    """)
    return


@app.cell
def _(failed_timeline, request_timeline):
    print("=== Timeline Comparison ===\n")

    # Get services visited in order
    def get_service_sequence(timeline):
        seen = []
        for _e in timeline["entries"]:
            _s = service_label(_e)
            if not seen or seen[-1] != _s:
                seen.append(_s)
        return seen

    success_path = get_service_sequence(request_timeline)
    failure_path = get_service_sequence(failed_timeline)

    print(f"Success path: {' -> '.join(success_path)}")
    print(f"Failure path: {' -> '.join(failure_path)}")

    # Find first ERROR
    print("\n=== First Error ===")
    for _entry in failed_timeline["entries"]:
        if _entry["level"] == "ERROR":
            print(f"Service: {service_label(_entry)}")
            print(f"Thread: {_entry.get('thread_id')}")
            print(f"Message: {_entry['message']}")
            print(f"Time: {_entry['timestamp']}")
            break
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned how to track execution flows in Logler:

    - **`follow_thread(thread_id=...)`** - Track a single thread
    - **`follow_thread(correlation_id=...)`** - Track a request across services
    - **`follow_thread(trace_id=...)`** - Track distributed traces
    - **Timeline analysis** - Compare durations and service paths

    **Key Insights:**
    - Correlation IDs are essential for debugging microservices
    - Comparing successful vs failed requests reveals root causes
    - Timeline reconstruction shows the full request journey

    **Next Steps:**
    - **Tour 03**: Hierarchy visualization (tree and waterfall views)
    - **Tour 04**: Investigation sessions
    """)
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return


if __name__ == "__main__":
    app.run()
