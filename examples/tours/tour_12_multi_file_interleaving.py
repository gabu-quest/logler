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
    # Logler Tour: Multi-File Tracing

    Multi-file tracing is where Logler shines. Real systems have logs scattered
    across services, and Logler can unify them into one investigation surface:

    - Load ALL files into a single index
    - Search across all services with ONE query
    - Trace a request as it flows through multiple teams and services
    - Build hierarchies spanning multiple files
    - Detect where failures originate in a distributed system

    **Scenario:** We'll trace a checkout request through 5 microservices:
    1. **API Gateway** - Routes requests, handles auth
    2. **User Service** - Profile and preferences
    3. **Inventory Service** - Stock availability
    4. **Payment Service** - Transaction processing
    5. **Notification Service** - Email/SMS confirmation

    Let's see how a single request flows through this system!
    """)
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    # Create temp directory for our 5 log files
    temp_dir = tempfile.mkdtemp()

    # Base timestamp
    base_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)

    # Correlation ID that links all services
    CORRELATION_ID = "checkout-abc-123"
    TRACE_ID = "trace-checkout-001"

    print(f"Correlation ID: {CORRELATION_ID}")
    print(f"Trace ID: {TRACE_ID}")
    print(f"Temp directory: {temp_dir}")
    return CORRELATION_ID, Path, TRACE_ID, base_time, json, temp_dir, timedelta


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Generate Distributed Logs

    We'll create 5 separate log files, each representing a different microservice.
    The request flows through them in sequence, with realistic timing and occasional failures.
    """)
    return


@app.cell
def _(CORRELATION_ID, Path, TRACE_ID, base_time, json, temp_dir, timedelta):
    def write_logs(filename, service_name, logs):
        path = Path(temp_dir) / filename
        with open(path, "w") as f:
            for log in logs:
                log["service"] = service_name
                log["correlation_id"] = CORRELATION_ID
                log["trace_id"] = TRACE_ID
                f.write(json.dumps(log) + "\n")
        return str(path)

    # API Gateway logs (entry point)
    api_gateway_log = write_logs(
        "api_gateway.log",
        "api-gateway",
        [
            {
                "timestamp": (base_time + timedelta(milliseconds=0)).isoformat(),
                "level": "INFO",
                "message": "Incoming POST /api/checkout",
                "thread_id": "gateway-handler-1",
                "span_id": "checkout.api",
                "parent_span_id": None,
                "operation_name": "Checkout Request",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=5)).isoformat(),
                "level": "DEBUG",
                "message": "Auth token validated for user_id=user-456",
                "thread_id": "gateway-handler-1",
                "span_id": "checkout.api",
                "parent_span_id": None,
                "operation_name": "Checkout Request",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=10)).isoformat(),
                "level": "INFO",
                "message": "Routing to user-service for profile lookup",
                "thread_id": "gateway-handler-1",
                "span_id": "checkout.api",
                "parent_span_id": None,
                "operation_name": "Checkout Request",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=850)).isoformat(),
                "level": "INFO",
                "message": "Checkout completed successfully, returning 200",
                "thread_id": "gateway-handler-1",
                "span_id": "checkout.api",
                "parent_span_id": None,
                "operation_name": "Checkout Request",
                "duration_ms": 850,
            },
        ],
    )

    # User Service logs
    user_service_log = write_logs(
        "user_service.log",
        "user-service",
        [
            {
                "timestamp": (base_time + timedelta(milliseconds=15)).isoformat(),
                "level": "INFO",
                "message": "Received profile request for user_id=user-456",
                "thread_id": "user-worker-3",
                "span_id": "user.profile",
                "parent_span_id": "checkout.api",
                "operation_name": "Fetch User Profile",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=25)).isoformat(),
                "level": "DEBUG",
                "message": "Cache miss for user profile, querying database",
                "thread_id": "user-worker-3",
                "span_id": "user.profile",
                "parent_span_id": "checkout.api",
                "operation_name": "Fetch User Profile",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=45)).isoformat(),
                "level": "INFO",
                "message": "Profile loaded: premium_member=true, shipping_address=123 Main St",
                "thread_id": "user-worker-3",
                "span_id": "user.profile",
                "parent_span_id": "checkout.api",
                "operation_name": "Fetch User Profile",
                "duration_ms": 30,
            },
        ],
    )

    # Inventory Service logs
    inventory_service_log = write_logs(
        "inventory_service.log",
        "inventory-service",
        [
            {
                "timestamp": (base_time + timedelta(milliseconds=50)).isoformat(),
                "level": "INFO",
                "message": "Checking stock for items: [SKU-001, SKU-002, SKU-003]",
                "thread_id": "inventory-checker-2",
                "span_id": "inventory.check",
                "parent_span_id": "checkout.api",
                "operation_name": "Check Inventory",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=55)).isoformat(),
                "level": "DEBUG",
                "message": "Querying warehouse database for stock levels",
                "thread_id": "inventory-checker-2",
                "span_id": "inventory.check",
                "parent_span_id": "checkout.api",
                "operation_name": "Check Inventory",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=120)).isoformat(),
                "level": "WARN",
                "message": "Low stock warning: SKU-003 has only 2 units remaining",
                "thread_id": "inventory-checker-2",
                "span_id": "inventory.check",
                "parent_span_id": "checkout.api",
                "operation_name": "Check Inventory",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=125)).isoformat(),
                "level": "INFO",
                "message": "Stock reserved: all items available",
                "thread_id": "inventory-checker-2",
                "span_id": "inventory.check",
                "parent_span_id": "checkout.api",
                "operation_name": "Check Inventory",
                "duration_ms": 75,
            },
        ],
    )

    # Payment Service logs (with a retry scenario)
    payment_service_log = write_logs(
        "payment_service.log",
        "payment-service",
        [
            {
                "timestamp": (base_time + timedelta(milliseconds=130)).isoformat(),
                "level": "INFO",
                "message": "Processing payment: amount=$149.99, method=credit_card",
                "thread_id": "payment-processor-1",
                "span_id": "payment.process",
                "parent_span_id": "checkout.api",
                "operation_name": "Process Payment",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=200)).isoformat(),
                "level": "ERROR",
                "message": "Payment gateway timeout after 70ms, retrying...",
                "thread_id": "payment-processor-1",
                "span_id": "payment.process",
                "parent_span_id": "checkout.api",
                "operation_name": "Process Payment",
                "error_code": "GATEWAY_TIMEOUT",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=350)).isoformat(),
                "level": "INFO",
                "message": "Retry successful: payment authorized, txn_id=TXN-789",
                "thread_id": "payment-processor-1",
                "span_id": "payment.process",
                "parent_span_id": "checkout.api",
                "operation_name": "Process Payment",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=400)).isoformat(),
                "level": "INFO",
                "message": "Payment completed successfully",
                "thread_id": "payment-processor-1",
                "span_id": "payment.process",
                "parent_span_id": "checkout.api",
                "operation_name": "Process Payment",
                "duration_ms": 270,
            },
        ],
    )

    # Notification Service logs
    notification_service_log = write_logs(
        "notification_service.log",
        "notification-service",
        [
            {
                "timestamp": (base_time + timedelta(milliseconds=405)).isoformat(),
                "level": "INFO",
                "message": "Sending order confirmation to user-456",
                "thread_id": "notifier-async-1",
                "span_id": "notify.send",
                "parent_span_id": "checkout.api",
                "operation_name": "Send Notification",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=450)).isoformat(),
                "level": "DEBUG",
                "message": "Email template rendered: order_confirmation_v2",
                "thread_id": "notifier-async-1",
                "span_id": "notify.send",
                "parent_span_id": "checkout.api",
                "operation_name": "Send Notification",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=500)).isoformat(),
                "level": "INFO",
                "message": "Email queued for delivery: msg_id=EMAIL-123",
                "thread_id": "notifier-async-1",
                "span_id": "notify.send",
                "parent_span_id": "checkout.api",
                "operation_name": "Send Notification",
            },
            {
                "timestamp": (base_time + timedelta(milliseconds=520)).isoformat(),
                "level": "INFO",
                "message": "SMS notification sent: +1-555-0123",
                "thread_id": "notifier-async-1",
                "span_id": "notify.send",
                "parent_span_id": "checkout.api",
                "operation_name": "Send Notification",
                "duration_ms": 115,
            },
        ],
    )

    all_files = [
        api_gateway_log,
        user_service_log,
        inventory_service_log,
        payment_service_log,
        notification_service_log,
    ]

    print("Created 5 log files:")
    for f in all_files:
        print(f"  - {Path(f).name}")

    total_logs = 4 + 3 + 4 + 4 + 4  # Count per service
    print(f"\nTotal log entries: {total_logs} across 5 services")
    return (
        all_files,
        api_gateway_log,
        inventory_service_log,
        notification_service_log,
        payment_service_log,
        user_service_log,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Load ALL Files Into Single Investigator

    Here's the magic: we load all 5 log files into ONE Investigator.
    This creates a unified index that can search across everything.
    """)
    return


@app.cell
def _(all_files):
    from logler.investigate import Investigator

    inv = Investigator()
    inv.load_files(all_files)

    print("Loaded all 5 service logs into single Investigator!")
    print(f"Files indexed: {len(all_files)}")

    # Get combined metadata
    meta = inv.get_metadata()
    total_lines = sum(m["lines"] for m in meta)
    print(f"Total lines indexed: {total_lines}")
    return (inv,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Search Across ALL Services

    One query searches all 5 log files simultaneously.
    Results are merged and sorted by timestamp.
    """)
    return


@app.cell
def _(inv):
    # Search for errors across ALL services
    errors = inv.search(level="ERROR")

    print(f"Found {errors['total_matches']} errors across all services:\n")
    for _r in errors["results"]:
        _entry = _r["entry"]
        _svc = _entry.get("service", _r.get("file", "unknown"))
        print(f"[{_svc}] {_entry.get('message', '')}")
        if _entry.get("error_code"):
            print(f"  Error code: {_entry['error_code']}")
    return


@app.cell
def _(inv):
    # Search for "payment" across all services
    payment_results = inv.search(query="payment")

    print(f"Found {payment_results['total_matches']} entries mentioning 'payment':\n")
    for _r in payment_results["results"]:
        _entry = _r["entry"]
        _svc = _entry.get("service_name", "unknown")
        print(f"[{_svc:20}] [{_entry['level']:5}] {_entry['message'][:60]}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Cross-Service Timeline

    `cross_service_timeline()` creates a unified view of a request across
    services with relative timings. This makes handoffs and latency visible.
    """)
    return


@app.cell
def _(
    CORRELATION_ID,
    api_gateway_log,
    inventory_service_log,
    notification_service_log,
    payment_service_log,
    user_service_log,
):
    from logler.investigate import cross_service_timeline

    timeline = cross_service_timeline(
        files={
            "api-gateway": [api_gateway_log],
            "user-service": [user_service_log],
            "inventory-service": [inventory_service_log],
            "payment-service": [payment_service_log],
            "notification-service": [notification_service_log],
        },
        correlation_id=CORRELATION_ID,
    )

    print("=" * 70)
    print("CROSS-SERVICE TIMELINE")
    print("=" * 70)
    print(f"Total duration: {timeline['duration_ms']}ms")
    print(f"Services involved: {timeline['services']}")
    print(f"Total entries: {timeline['total_entries']}")
    print()

    # Service breakdown
    print("Entries per service:")
    for _svc, _count in timeline.get("service_breakdown", {}).items():
        print(f"  {_svc}: {_count}")
    return (timeline,)


@app.cell
def _(timeline):
    # Print the waterfall timeline
    print("\n" + "=" * 70)
    print("REQUEST WATERFALL")
    print("=" * 70)

    for _evt in timeline["timeline"]:
        _svc = _evt["service"]
        _rel_ms = _evt["relative_time_ms"]
        _entry = _evt["entry"]
        _level = _entry.get("level", "INFO")

        # Visual indicator for level
        _indicator = "  "
        if _level == "ERROR":
            _indicator = "!!"
        elif _level == "WARN":
            _indicator = "! "

        print(f"+{_rel_ms:4d}ms [{_svc:20}] {_indicator} {_entry['message'][:45]}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Build Hierarchy Across All Files

    Even more powerful: build a parent-child hierarchy from logs
    scattered across multiple files!
    """)
    return


@app.cell
def _(CORRELATION_ID, all_files):
    from logler.investigate import follow_thread_hierarchy, get_hierarchy_summary

    hierarchy = follow_thread_hierarchy(
        files=all_files,
        root_identifier=CORRELATION_ID,
        use_naming_patterns=True,
        use_temporal_inference=True,
    )

    print("DISTRIBUTED HIERARCHY")
    print("=" * 70)
    print(get_hierarchy_summary(hierarchy))
    return (hierarchy,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Error Flow Analysis Across Services

    When something fails in a distributed system, where did it START?
    Error flow analysis traces failures back to their root cause.
    """)
    return


@app.cell
def _(hierarchy):
    from logler.investigate import analyze_error_flow, format_error_flow

    error_flow = analyze_error_flow(hierarchy)

    print("ERROR FLOW ANALYSIS")
    print("=" * 70)
    print(format_error_flow(error_flow))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've seen the real power of Logler:

    - **Single Investigator** - Load unlimited files into one index
    - **Unified Search** - One query across all services
    - **Cross-Service Timeline** - See request flow with timings
    - **Distributed Hierarchy** - Parent-child relationships across files
    - **Error Flow Analysis** - Find root causes in distributed systems

    This is how you debug microservices with clarity and speed.

    **Next Steps:**
    - **Tour 13**: Live log watching (real-time streaming)
    - **Tour 14**: Performance at scale (10,000+ entries)
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
