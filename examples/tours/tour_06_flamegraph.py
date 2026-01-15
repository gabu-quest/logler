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
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Setting Up - Performance Trace Data

    We'll create a trace with multiple nested operations
    where some are much slower than others.
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

    def _add_span_events(
        span_id,
        parent_span_id,
        service,
        message,
        offset_ms,
        duration_ms,
        level="INFO",
        emit_end=True,
    ):
        logs.append(
            {
                "timestamp": (base_time + timedelta(milliseconds=offset_ms)).isoformat(),
                "level": level,
                "message": message,
                "trace_id": "trace-perf-001",
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "service": service,
                "duration_ms": duration_ms,
            }
        )
        if emit_end:
            logs.append(
                {
                    "timestamp": (
                        base_time + timedelta(milliseconds=offset_ms + duration_ms)
                    ).isoformat(),
                    "level": level,
                    "message": f"{message} completed ({duration_ms}ms)",
                    "trace_id": "trace-perf-001",
                    "span_id": span_id,
                    "parent_span_id": parent_span_id,
                    "service": service,
                    "duration_ms": duration_ms,
                }
            )

    span_defs = [
        ("span-root", None, "api-gateway", "HTTP POST /api/checkout", 0, 900, "INFO", False),
        ("span-auth", "span-root", "auth-service", "Validating auth token", 5, 20, "INFO", True),
        ("span-inventory", "span-root", "inventory-service", "Checking inventory", 30, 120, "INFO", True),
        ("span-payment", "span-root", "payment-service", "Processing payment", 170, 540, "INFO", True),
        ("span-stripe", "span-payment", "stripe-gateway", "Calling Stripe API", 190, 420, "INFO", True),
        ("span-fraud", "span-payment", "fraud-service", "Running fraud detection", 640, 60, "DEBUG", True),
        ("span-order", "span-root", "order-service", "Creating order record", 740, 90, "INFO", True),
        ("span-notify", "span-root", "notification-service", "Sending confirmation email", 850, 50, "INFO", True),
    ]

    for _span in span_defs:
        _add_span_events(*_span)

    for _idx, _region in enumerate(["us-east", "eu-west", "ap-south"]):
        _add_span_events(
            f"span-inv-db-{_idx + 1}",
            "span-inventory",
            "postgres",
            f"SELECT stock FROM inventory_{_region}",
            35 + _idx * 12,
            40 + _idx * 8,
            "DEBUG",
            True,
        )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "performance.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries with performance data")
    print("Total request duration: 900ms")
    print("Expected bottleneck: payment-service (540ms)")
    return Path, base_time, log_file, logs, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Building the Hierarchy

    First, let's build the hierarchy that we'll visualize.
    """
    )
    return


@app.cell
def _():
    from logler.investigate import follow_thread_hierarchy
    from logler.tree_formatter import format_flamegraph, format_tree, format_waterfall

    return follow_thread_hierarchy, format_flamegraph, format_tree, format_waterfall


@app.cell
def _(follow_thread_hierarchy, log_file):
    # Build hierarchy for the trace
    hierarchy = follow_thread_hierarchy(files=[str(log_file)], root_identifier="trace-perf-001")
    bottleneck = hierarchy.get("bottleneck")
    if bottleneck and "percentage" not in bottleneck:
        bottleneck["percentage"] = bottleneck.get("percentage_of_total", 0)

    print("=== Hierarchy Stats ===")
    print(f"Total nodes: {hierarchy['total_nodes']}")
    print(f"Max depth: {hierarchy['max_depth']}")
    hier_total_duration = hierarchy.get("total_duration_ms", 0)
    print(f"Total duration: {hier_total_duration}ms")

    bottleneck = hierarchy.get("bottleneck")
    if bottleneck:
        hier_total_duration = hierarchy.get("total_duration_ms", 0) or 0
        duration_ms = bottleneck.get("duration_ms", 0) or 0
        bottleneck_percentage = bottleneck.get("percentage")
        if bottleneck_percentage is None:
            bottleneck_percentage = bottleneck.get("percentage_of_total")
        if bottleneck_percentage is None and hier_total_duration:
            bottleneck_percentage = (duration_ms / hier_total_duration) * 100
        if bottleneck_percentage is not None:
            bottleneck["percentage"] = bottleneck_percentage

        print(f"\nBottleneck: {bottleneck.get('node_id')}")
        print(f"  Duration: {duration_ms}ms")
        if bottleneck_percentage is not None:
            print(f"  Percentage: {bottleneck_percentage:.1f}%")
    return bottleneck, hierarchy


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Creating a Flamegraph

    The flamegraph shows the call hierarchy where **width = time spent**.
    Wider bars mean more time was spent in that operation.
    """
    )
    return


@app.cell
def _(format_flamegraph, hierarchy):
    # Create flamegraph (without ANSI colors for notebook display)
    flamegraph = format_flamegraph(hierarchy, width=80, use_colors=False)
    print(flamegraph)
    return (flamegraph,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Interpreting the Flamegraph

    Key insights from the flamegraph above:
    """
    )
    return


@app.cell
def _(hierarchy):
    print("=== Flamegraph Interpretation ===\n")

    # Analyze the hierarchy
    analysis_total_duration = hierarchy.get("total_duration_ms", 0)
    bottleneck_info = hierarchy.get("bottleneck", {})

    print("WIDTH = TIME SPENT")
    print("-" * 40)

    # Collect all nodes with durations (deduplicate by node id)
    nodes_by_id = {}
    stack = [(_root, 0) for _root in hierarchy.get("roots", [])]
    while stack:
        _node, _depth = stack.pop()
        _duration = _node.get("duration_ms", 0)
        if _duration and analysis_total_duration > 0:
            _pct = (_duration / analysis_total_duration) * 100
            node_id = _node.get("id", "unknown")
            existing = nodes_by_id.get(node_id)
            if not existing or _duration > existing["duration"]:
                nodes_by_id[node_id] = {
                    "id": node_id,
                    "duration": _duration,
                    "percentage": _pct,
                    "depth": _depth,
                }
        for _child in _node.get("children", []):
            stack.append((_child, _depth + 1))

    # Sort by duration
    _nodes_by_duration = sorted(nodes_by_id.values(), key=lambda x: -x["duration"])

    print("\nTime spent by node (sorted):")
    for _n in _nodes_by_duration[:5]:
        _bar = "█" * int(_n["percentage"] / 5)
        print(f"  {_n['id']:<25} {_bar:<20} {_n['duration']:>4}ms ({_n['percentage']:.0f}%)")

    if bottleneck_info:
        analysis_bottleneck_pct = bottleneck_info.get("percentage")
        if analysis_bottleneck_pct is None:
            analysis_bottleneck_pct = bottleneck_info.get("percentage_of_total")
        if analysis_bottleneck_pct is None and analysis_total_duration:
            analysis_bottleneck_pct = (
                bottleneck_info.get("duration_ms", 0) / analysis_total_duration
            ) * 100
        if analysis_bottleneck_pct is None:
            analysis_bottleneck_pct = 0

        print("\n⚠️  BOTTLENECK IDENTIFIED:")
        print(
            f"   {bottleneck_info.get('node_id')} takes {analysis_bottleneck_pct:.0f}% of total time"
        )
        print("   This is where optimization efforts should focus!")
    return bottleneck_info, analysis_total_duration


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Comparing with Other Visualizations

    Flamegraphs complement tree and waterfall views:
    - **Tree**: Shows structure and hierarchy
    - **Waterfall**: Shows timing sequence
    - **Flamegraph**: Shows time distribution
    """
    )
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
    mo.md(
        r"""
    ## 6. When to Use Flamegraphs

    **Use Flamegraphs when:**
    - Investigating slow requests/transactions
    - Identifying performance bottlenecks
    - Understanding where time is spent
    - Comparing before/after optimizations

    **Flamegraph vs Waterfall:**
    - Waterfall shows *when* things happened (sequence)
    - Flamegraph shows *how much time* each took (proportion)
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
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
    """
    )
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return (shutil,)


if __name__ == "__main__":
    app.run()
