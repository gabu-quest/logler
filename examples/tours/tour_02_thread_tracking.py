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

    # Simulate a request flowing through microservices
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    # Request 1: Successful order
    correlation_id = "req-001"
    trace_id = "trace-abc123"

    logs.extend([
        {"timestamp": (base_time + timedelta(ms=0)).isoformat(), "level": "INFO",
         "message": "Received POST /api/orders", "service": "api-gateway",
         "thread_id": "http-1", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=5)).isoformat(), "level": "DEBUG",
         "message": "Validating JWT token", "service": "auth-service",
         "thread_id": "auth-pool-1", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=15)).isoformat(), "level": "INFO",
         "message": "Token validated for user:alice", "service": "auth-service",
         "thread_id": "auth-pool-1", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=20)).isoformat(), "level": "DEBUG",
         "message": "Checking inventory for SKU-12345", "service": "inventory-service",
         "thread_id": "inv-worker-3", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=45)).isoformat(), "level": "INFO",
         "message": "Inventory reserved: 2 units", "service": "inventory-service",
         "thread_id": "inv-worker-3", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=50)).isoformat(), "level": "INFO",
         "message": "Processing payment $99.99", "service": "payment-service",
         "thread_id": "payment-1", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=200)).isoformat(), "level": "INFO",
         "message": "Payment authorized: txn-789", "service": "payment-service",
         "thread_id": "payment-1", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=210)).isoformat(), "level": "INFO",
         "message": "Order created: order-456", "service": "order-service",
         "thread_id": "order-proc-2", "correlation_id": correlation_id, "trace_id": trace_id},

        {"timestamp": (base_time + timedelta(ms=215)).isoformat(), "level": "INFO",
         "message": "Request completed: 201 Created", "service": "api-gateway",
         "thread_id": "http-1", "correlation_id": correlation_id, "trace_id": trace_id},
    ])

    # Request 2: Failed payment
    correlation_id2 = "req-002"
    trace_id2 = "trace-def456"

    logs.extend([
        {"timestamp": (base_time + timedelta(ms=100)).isoformat(), "level": "INFO",
         "message": "Received POST /api/orders", "service": "api-gateway",
         "thread_id": "http-2", "correlation_id": correlation_id2, "trace_id": trace_id2},

        {"timestamp": (base_time + timedelta(ms=110)).isoformat(), "level": "INFO",
         "message": "Token validated for user:bob", "service": "auth-service",
         "thread_id": "auth-pool-2", "correlation_id": correlation_id2, "trace_id": trace_id2},

        {"timestamp": (base_time + timedelta(ms=130)).isoformat(), "level": "INFO",
         "message": "Inventory reserved: 1 unit", "service": "inventory-service",
         "thread_id": "inv-worker-1", "correlation_id": correlation_id2, "trace_id": trace_id2},

        {"timestamp": (base_time + timedelta(ms=140)).isoformat(), "level": "INFO",
         "message": "Processing payment $49.99", "service": "payment-service",
         "thread_id": "payment-2", "correlation_id": correlation_id2, "trace_id": trace_id2},

        {"timestamp": (base_time + timedelta(ms=350)).isoformat(), "level": "ERROR",
         "message": "Payment declined: insufficient funds", "service": "payment-service",
         "thread_id": "payment-2", "correlation_id": correlation_id2, "trace_id": trace_id2},

        {"timestamp": (base_time + timedelta(ms=355)).isoformat(), "level": "WARN",
         "message": "Rolling back inventory reservation", "service": "inventory-service",
         "thread_id": "inv-worker-1", "correlation_id": correlation_id2, "trace_id": trace_id2},

        {"timestamp": (base_time + timedelta(ms=360)).isoformat(), "level": "INFO",
         "message": "Request completed: 402 Payment Required", "service": "api-gateway",
         "thread_id": "http-2", "correlation_id": correlation_id2, "trace_id": trace_id2},
    ])

    # Sort by timestamp (simulating collected logs)
    logs.sort(key=lambda x: x['timestamp'])

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "microservices.log"
    with open(log_file, "w") as f:
        for log in logs:
            f.write(json.dumps(log) + "\n")

    print(f"Created {len(logs)} log entries from 5 services")
    print(f"Correlation IDs: req-001 (success), req-002 (failed)")
    return Path, base_time, correlation_id, correlation_id2, log_file, logs, temp_dir, trace_id, trace_id2


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
    from logler.investigate import follow_thread, search

    return follow_thread, search


@app.cell
def _(follow_thread, log_file):
    # Follow the payment-1 thread (successful payment)
    timeline = follow_thread(
        files=[str(log_file)],
        thread_id="payment-1"
    )

    print(f"=== Thread: payment-1 ===")
    print(f"Total entries: {timeline['total_entries']}")
    print(f"Duration: {timeline.get('duration_ms', 'N/A')}ms\n")

    for entry in timeline['entries']:
        ts = entry['timestamp'].split('T')[1][:12]
        print(f"[{ts}] [{entry['level']}] {entry['message']}")
    return (timeline,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Following a Correlation ID

    Correlation IDs track a single request across all services and threads.
    This is essential for debugging distributed systems.
    """)
    return


@app.cell
def _(follow_thread, log_file):
    # Follow the successful order request
    request_timeline = follow_thread(
        files=[str(log_file)],
        correlation_id="req-001"
    )

    print(f"=== Request: req-001 (Successful Order) ===")
    print(f"Total entries: {request_timeline['total_entries']}")
    print(f"Duration: {request_timeline.get('duration_ms', 'N/A')}ms")
    print(f"Unique spans: {len(request_timeline.get('unique_spans', []))}\n")

    for entry in request_timeline['entries']:
        ts = entry['timestamp'].split('T')[1][:12]
        svc = entry.get('service', 'unknown')
        print(f"[{ts}] [{svc:20}] [{entry['level']:5}] {entry['message']}")
    return (request_timeline,)


@app.cell
def _(follow_thread, log_file):
    # Follow the failed order request
    failed_timeline = follow_thread(
        files=[str(log_file)],
        correlation_id="req-002"
    )

    print(f"=== Request: req-002 (Failed Order) ===")
    print(f"Total entries: {failed_timeline['total_entries']}")
    print(f"Duration: {failed_timeline.get('duration_ms', 'N/A')}ms\n")

    for entry in failed_timeline['entries']:
        ts = entry['timestamp'].split('T')[1][:12]
        svc = entry.get('service', 'unknown')
        level = entry['level']
        # Highlight errors
        marker = ">>>" if level == "ERROR" else "   "
        print(f"{marker} [{ts}] [{svc:20}] [{level:5}] {entry['message']}")
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
def _(follow_thread, log_file):
    # Follow by trace ID
    trace_timeline = follow_thread(
        files=[str(log_file)],
        trace_id="trace-abc123"
    )

    print(f"=== Trace: trace-abc123 ===")
    print(f"Total entries: {trace_timeline['total_entries']}")

    # Group by service
    by_service = {}
    for entry in trace_timeline['entries']:
        svc = entry.get('service', 'unknown')
        if svc not in by_service:
            by_service[svc] = []
        by_service[svc].append(entry)

    print(f"\nServices involved: {list(by_service.keys())}")
    for svc, entries in by_service.items():
        print(f"  {svc}: {len(entries)} entries")
    return by_service, trace_timeline


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Comparing Parallel Requests

    When debugging, you often want to compare a successful request
    with a failed one. Let's analyze the differences:
    """)
    return


@app.cell
def _(failed_timeline, request_timeline):
    print("=== Comparison: req-001 vs req-002 ===\n")

    success = request_timeline
    failure = failed_timeline

    print(f"{'Metric':<25} {'Success (req-001)':<20} {'Failure (req-002)':<20}")
    print("-" * 65)
    print(f"{'Total entries':<25} {success['total_entries']:<20} {failure['total_entries']:<20}")
    print(f"{'Duration (ms)':<25} {success.get('duration_ms', 'N/A'):<20} {failure.get('duration_ms', 'N/A'):<20}")

    # Count by level
    def count_levels(timeline):
        counts = {}
        for entry in timeline['entries']:
            level = entry['level']
            counts[level] = counts.get(level, 0) + 1
        return counts

    success_levels = count_levels(success)
    failure_levels = count_levels(failure)

    print(f"\n{'Level Breakdown:':<25}")
    for level in ['INFO', 'DEBUG', 'WARN', 'ERROR']:
        s_count = success_levels.get(level, 0)
        f_count = failure_levels.get(level, 0)
        print(f"  {level:<23} {s_count:<20} {f_count:<20}")
    return count_levels, failure, failure_levels, success, success_levels


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
        for entry in timeline['entries']:
            svc = entry.get('service', 'unknown')
            if not seen or seen[-1] != svc:
                seen.append(svc)
        return seen

    success_path = get_service_sequence(request_timeline)
    failure_path = get_service_sequence(failed_timeline)

    print(f"Success path: {' -> '.join(success_path)}")
    print(f"Failure path: {' -> '.join(failure_path)}")

    # Find first ERROR
    print("\n=== First Error ===")
    for entry in failed_timeline['entries']:
        if entry['level'] == 'ERROR':
            print(f"Service: {entry.get('service')}")
            print(f"Thread: {entry.get('thread_id')}")
            print(f"Message: {entry['message']}")
            print(f"Time: {entry['timestamp']}")
            break
    return failure_path, get_service_sequence, success_path


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
    return (shutil,)


if __name__ == "__main__":
    app.run()
