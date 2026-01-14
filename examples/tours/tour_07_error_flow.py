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
    # Logler Tour: Error Flow Analysis

    When errors occur in distributed systems, they often cascade through
    multiple services. Understanding the error flow helps identify the
    **root cause** vs **symptoms**.

    **What you'll learn:**
    1. Analyzing error propagation
    2. Identifying root causes
    3. Understanding cascading failures
    4. Getting recommendations
    5. Formatting error flow reports

    Let's dive in!
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Setting Up - Cascading Failure Scenario

    We'll simulate a scenario where a database failure causes
    errors to cascade through the system.
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

    # Root span - API request
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=0)).isoformat(),
            "level": "INFO",
            "message": "HTTP GET /api/products",
            "trace_id": "trace-error-001",
            "span_id": "span-root",
            "parent_span_id": None,
            "service": "api-gateway",
            "duration_ms": 5000,
        }
    )

    # Product service
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=10)).isoformat(),
            "level": "INFO",
            "message": "Fetching product catalog",
            "trace_id": "trace-error-001",
            "span_id": "span-products",
            "parent_span_id": "span-root",
            "service": "product-service",
            "duration_ms": 4500,
        }
    )

    # Database query - ROOT CAUSE
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=20)).isoformat(),
            "level": "ERROR",
            "message": "Database connection timeout after 3000ms",
            "trace_id": "trace-error-001",
            "span_id": "span-db",
            "parent_span_id": "span-products",
            "service": "postgres",
            "duration_ms": 3000,
            "error": "ConnectionTimeout",
        }
    )

    # Cache fallback - also fails
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=3100)).isoformat(),
            "level": "ERROR",
            "message": "Cache miss and DB unavailable",
            "trace_id": "trace-error-001",
            "span_id": "span-cache",
            "parent_span_id": "span-products",
            "service": "redis",
            "duration_ms": 100,
            "error": "CacheMiss",
        }
    )

    # Product service propagates error
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=3200)).isoformat(),
            "level": "ERROR",
            "message": "Failed to fetch products: data source unavailable",
            "trace_id": "trace-error-001",
            "span_id": "span-products",
            "parent_span_id": "span-root",
            "service": "product-service",
            "duration_ms": 4500,
            "error": "DataSourceError",
        }
    )

    # Recommendation service - separate failure
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=50)).isoformat(),
            "level": "INFO",
            "message": "Fetching recommendations",
            "trace_id": "trace-error-001",
            "span_id": "span-recs",
            "parent_span_id": "span-root",
            "service": "recommendation-service",
            "duration_ms": 500,
        }
    )

    # ML model call
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=60)).isoformat(),
            "level": "ERROR",
            "message": "ML model timeout",
            "trace_id": "trace-error-001",
            "span_id": "span-ml",
            "parent_span_id": "span-recs",
            "service": "ml-service",
            "duration_ms": 400,
            "error": "ModelTimeout",
        }
    )

    # API gateway sees multiple failures
    logs.append(
        {
            "timestamp": (base_time + timedelta(ms=4900)).isoformat(),
            "level": "ERROR",
            "message": "Request failed: multiple downstream errors",
            "trace_id": "trace-error-001",
            "span_id": "span-root",
            "parent_span_id": None,
            "service": "api-gateway",
            "duration_ms": 5000,
            "error": "DownstreamError",
        }
    )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "errors.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries with cascading errors")
    print("Root cause: Database connection timeout")
    print("Additional failure: ML model timeout")
    return Path, base_time, log_file, logs, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Building the Hierarchy

    First, let's build the hierarchy to see the error structure.
    """
    )
    return


@app.cell
def _():
    from logler.investigate import follow_thread_hierarchy, analyze_error_flow, format_error_flow

    return analyze_error_flow, follow_thread_hierarchy, format_error_flow


@app.cell
def _(follow_thread_hierarchy, log_file):
    # Build hierarchy
    hierarchy = follow_thread_hierarchy(files=[str(log_file)], root_identifier="trace-error-001")

    print("=== Hierarchy Overview ===")
    print(f"Total nodes: {hierarchy['total_nodes']}")
    print(f"Error nodes: {len(hierarchy.get('error_nodes', []))}")
    print(f"Error node IDs: {hierarchy.get('error_nodes', [])}")
    return (hierarchy,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Analyzing Error Flow

    The `analyze_error_flow()` function traces how errors propagate
    through the hierarchy and identifies root causes.
    """
    )
    return


@app.cell
def _(analyze_error_flow, hierarchy):
    # Analyze error flow
    error_analysis = analyze_error_flow(hierarchy, include_context=True)

    print("=== Error Flow Analysis ===\n")
    print(f"Has errors: {error_analysis['has_errors']}")
    print(f"Total error nodes: {error_analysis['total_error_nodes']}")
    return (error_analysis,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Identifying Root Causes

    Root causes are the **originating** errors - the deepest errors
    in the hierarchy that didn't come from child failures.
    """
    )
    return


@app.cell
def _(error_analysis):
    print("=== ROOT CAUSES ===\n")

    for _i, _cause in enumerate(error_analysis["root_causes"], 1):
        _confidence = int(_cause.get("confidence", 0) * 100)
        _leaf = "(leaf node)" if _cause.get("is_leaf") else ""

        print(f"{_i}. {_cause['node_id']} {_leaf}")
        print(f"   Type: {_cause.get('node_type', 'Unknown')}")
        print(f"   Depth: {_cause.get('depth', 0)}")
        print(f"   Confidence: {_confidence}%")
        print(f"   Path: {' -> '.join(_cause.get('path', []))}")
        print()
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Understanding Propagation Chains

    Propagation chains show how errors **bubbled up** through
    the system from the root cause.
    """
    )
    return


@app.cell
def _(error_analysis):
    print("=== PROPAGATION CHAINS ===\n")

    for _chain in error_analysis["propagation_chains"]:
        print(f"Root cause: {_chain['root_cause']}")
        print(f"Propagation type: {_chain['propagation_type']}")
        print(f"Total affected: {_chain['total_affected']} nodes")
        print()
        print("Chain:")
        for _node in _chain["chain"]:
            _indent = "  " * _node["depth"]
            print(
                f"  {_indent}↳ {_node['node_id']} (depth={_node['depth']}, errors={_node['error_count']})"
            )
        print()
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 6. Impact Summary

    The impact summary quantifies the severity of the failure.
    """
    )
    return


@app.cell
def _(error_analysis):
    _impact = error_analysis["impact_summary"]

    print("=== IMPACT SUMMARY ===\n")
    print(f"Total affected nodes: {_impact['total_affected_nodes']}")
    print(f"Affected percentage: {_impact['affected_percentage']:.1f}%")
    print(f"Max propagation depth: {_impact['max_propagation_depth']}")
    print(f"Concurrent failures: {_impact['concurrent_failures']}")

    if _impact["affected_percentage"] > 50:
        print("\n⚠️  HIGH IMPACT: More than 50% of nodes affected!")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 7. Recommendations

    Logler provides actionable recommendations based on the analysis.
    """
    )
    return


@app.cell
def _(error_analysis):
    print("=== RECOMMENDATIONS ===\n")

    for _rec in error_analysis["recommendations"]:
        print(f"• {_rec}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 8. Formatted Error Flow Report

    Use `format_error_flow()` for a complete, formatted report.
    """
    )
    return


@app.cell
def _(error_analysis, format_error_flow):
    # Generate formatted report
    report = format_error_flow(error_analysis, show_chains=True, show_recommendations=True)
    print(report)
    return (report,)


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned how to analyze error flow:

    - **`analyze_error_flow(hierarchy)`** - Trace error propagation
    - **Root causes** - Find originating errors (not symptoms)
    - **Propagation chains** - See how errors cascaded
    - **Impact summary** - Quantify the failure severity
    - **Recommendations** - Get actionable suggestions
    - **`format_error_flow()`** - Generate formatted reports

    **Key Insights:**
    - Root causes are at leaf nodes or deepest error points
    - Multiple root causes can exist (concurrent failures)
    - High propagation depth suggests missing error handling
    - Use confidence scores to prioritize investigation

    **Next Steps:**
    - **Tour 08**: Comparison & diffing
    - **Tour 09**: Distributed tracing exports
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
