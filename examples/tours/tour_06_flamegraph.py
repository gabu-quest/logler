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
    # Logler Tour: Flamegraph Visualization

    Flamegraphs are powerful visualizations for understanding performance.
    They show where time is spent in a hierarchical execution, making
    bottlenecks instantly visible.

    **What you'll learn:**
    1. What flamegraphs are and when to use them
    2. Creating flamegraph visualizations
    3. Interpreting width (time spent)
    4. Identifying bottlenecks
    5. Comparing flamegraphs

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up - Performance Trace Data

    We'll create a trace with multiple nested operations
    where some are much slower than others.
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

    # Root span - API request (total 800ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=0)).isoformat(),
            "level": "INFO",
            "message": "HTTP POST /api/checkout",
            "trace_id": "trace-perf-001",
            "span_id": "checkout.request",
            "parent_span_id": None,
            "operation_name": "Checkout Request",
            "service": "api-gateway",
            "duration_ms": 800,
        }
    )

    # Auth check (fast: 20ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=5)).isoformat(),
            "level": "INFO",
            "message": "Validating auth token",
            "trace_id": "trace-perf-001",
            "span_id": "auth.validate",
            "parent_span_id": "checkout.request",
            "operation_name": "Auth Check",
            "service": "auth-service",
            "duration_ms": 20,
        }
    )

    # Inventory check (medium: 100ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=30)).isoformat(),
            "level": "INFO",
            "message": "Checking inventory",
            "trace_id": "trace-perf-001",
            "span_id": "inventory.check",
            "parent_span_id": "checkout.request",
            "operation_name": "Inventory Check",
            "service": "inventory-service",
            "duration_ms": 100,
        }
    )

    # Database query under inventory (50ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=35)).isoformat(),
            "level": "DEBUG",
            "message": "SELECT stock FROM inventory",
            "trace_id": "trace-perf-001",
            "span_id": "inventory.db",
            "parent_span_id": "inventory.check",
            "operation_name": "Inventory DB Query",
            "service": "postgres",
            "duration_ms": 50,
        }
    )

    # Payment processing (SLOW: 500ms - BOTTLENECK)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=150)).isoformat(),
            "level": "INFO",
            "message": "Processing payment",
            "trace_id": "trace-perf-001",
            "span_id": "payment.process",
            "parent_span_id": "checkout.request",
            "operation_name": "Process Payment",
            "service": "payment-service",
            "duration_ms": 500,
        }
    )

    # Payment gateway call (SLOW: 400ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=160)).isoformat(),
            "level": "INFO",
            "message": "Calling Stripe API",
            "trace_id": "trace-perf-001",
            "span_id": "payment.gateway",
            "parent_span_id": "payment.process",
            "operation_name": "Payment Gateway Call",
            "service": "stripe-gateway",
            "duration_ms": 400,
        }
    )

    # Fraud check (50ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=580)).isoformat(),
            "level": "DEBUG",
            "message": "Running fraud detection",
            "trace_id": "trace-perf-001",
            "span_id": "fraud.check",
            "parent_span_id": "payment.process",
            "operation_name": "Fraud Check",
            "service": "fraud-service",
            "duration_ms": 50,
        }
    )

    # Order creation (fast: 80ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=680)).isoformat(),
            "level": "INFO",
            "message": "Creating order record",
            "trace_id": "trace-perf-001",
            "span_id": "order.create",
            "parent_span_id": "checkout.request",
            "operation_name": "Create Order",
            "service": "order-service",
            "duration_ms": 80,
        }
    )

    # Notification (fast: 30ms)
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=770)).isoformat(),
            "level": "INFO",
            "message": "Sending confirmation email",
            "trace_id": "trace-perf-001",
            "span_id": "notify.email",
            "parent_span_id": "checkout.request",
            "operation_name": "Send Confirmation",
            "service": "notification-service",
            "duration_ms": 30,
        }
    )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "performance.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries with performance data")
    print("Total request duration: 800ms")
    print("Expected bottleneck: Process Payment (500ms)")
    return log_file, temp_dir


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Building the Hierarchy

    First, let's build the hierarchy that we'll visualize.
    """)
    return


@app.cell
def _():
    from logler.investigate import follow_thread_hierarchy
    from logler.tree_formatter import format_flamegraph, format_tree, format_waterfall
    return (
        follow_thread_hierarchy,
        format_flamegraph,
        format_tree,
        format_waterfall,
    )


@app.cell
def _(follow_thread_hierarchy, log_file):
    # Build hierarchy for the trace
    hierarchy = follow_thread_hierarchy(files=[str(log_file)], root_identifier="trace-perf-001")

    print("=== Hierarchy Stats ===")
    print(f"Total nodes: {hierarchy['total_nodes']}")
    print(f"Max depth: {hierarchy['max_depth']}")
    print(f"Total duration: {hierarchy.get('total_duration_ms', 0)}ms")

    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        print(f"\nBottleneck: {bottleneck.get('node_id')}")
        print(f"  Duration: {bottleneck.get('duration_ms', 0)}ms")
        print(f"  Percentage: {bottleneck.get('percentage', 0):.1f}%")
    return (hierarchy,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Creating a Flamegraph

    The flamegraph shows the call hierarchy where **width = time spent**.
    Wider bars mean more time was spent in that operation.
    """)
    return


@app.cell
def _(format_flamegraph, hierarchy):
    # Create flamegraph (without ANSI colors for notebook display)
    flamegraph = format_flamegraph(hierarchy, width=80, use_colors=False)
    print(flamegraph)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Interpreting the Flamegraph

    Key insights from the flamegraph above:
    """)
    return


@app.cell
def _(hierarchy):
    print("=== Flamegraph Interpretation ===\n")

    # Analyze the hierarchy
    total_duration = hierarchy.get("total_duration_ms", 0)
    bottleneck_info = hierarchy.get("bottleneck", {})

    print("WIDTH = TIME SPENT")
    print("-" * 40)

    # Collect all nodes with durations (iterative to avoid marimo scoping issues)
    _nodes_by_duration = []
    _stack = [(node, 0) for node in hierarchy.get("roots", [])]
    while _stack:
        _node, _depth = _stack.pop()
        _duration = _node.get("duration_ms", 0)
        if _duration and total_duration > 0:
            _pct = (_duration / total_duration) * 100
            _nodes_by_duration.append(
                {
                    "id": _node.get("id", "unknown"),
                    "duration": _duration,
                    "percentage": _pct,
                    "depth": _depth,
                }
            )
        for _child in _node.get("children", []):
            _stack.append((_child, _depth + 1))

    # Sort by duration
    _nodes_by_duration.sort(key=lambda x: -x["duration"])

    print("\nTime spent by node (sorted):")
    for _n in _nodes_by_duration[:5]:
        _bar = "█" * int(_n["percentage"] / 5)
        print(f"  {_n['id']:<25} {_bar:<20} {_n['duration']:>4}ms ({_n['percentage']:.0f}%)")

    if bottleneck_info:
        print("\n⚠️  BOTTLENECK IDENTIFIED:")
        print(
            f"   {bottleneck_info.get('node_id')} takes {bottleneck_info.get('percentage', 0):.0f}% of total time"
        )
        print("   This is where optimization efforts should focus!")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Comparing with Other Visualizations

    Flamegraphs complement tree and waterfall views:
    - **Tree**: Shows structure and hierarchy
    - **Waterfall**: Shows timing sequence
    - **Flamegraph**: Shows time distribution
    """)
    return


@app.cell
def _(format_tree, hierarchy):
    # Compare with tree view
    print("=== Tree View (Structure) ===")
    _tree = format_tree(hierarchy, mode="compact", use_colors=False)
    print(_tree)
    return


@app.cell
def _(format_waterfall, hierarchy):
    # Compare with waterfall view
    print("=== Waterfall View (Timing) ===")
    _waterfall = format_waterfall(hierarchy, width=70)
    print(_waterfall)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. When to Use Flamegraphs

    **Use Flamegraphs when:**
    - Investigating slow requests/transactions
    - Identifying performance bottlenecks
    - Understanding where time is spent
    - Comparing before/after optimizations

    **Flamegraph vs Waterfall:**
    - Waterfall shows *when* things happened (sequence)
    - Flamegraph shows *how much time* each took (proportion)
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned how to use flamegraph visualizations:

    - **`format_flamegraph(hierarchy)`** - Create flamegraph visualization
    - **Width = time** - Wider bars mean more time spent
    - **Bottleneck detection** - Find the slow operations
    - **Visual comparison** - Compare with tree/waterfall views

    **Key Insights:**
    - Flamegraphs make bottlenecks visually obvious
    - Focus optimization on the widest bars
    - Use with hierarchy analysis for complete picture

    **Next Steps:**
    - **Tour 07**: Error flow analysis
    - **Tour 08**: Comparison & diffing
    """)
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
