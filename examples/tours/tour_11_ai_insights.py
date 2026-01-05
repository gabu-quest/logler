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
    # Logler Tour: AI-Powered Insights

    Logler can automatically analyze logs and generate insights,
    explanations, and suggestions - perfect for LLM agents.

    **What you'll learn:**
    1. Automatic insights generation
    2. Explaining error messages
    3. Getting next action suggestions
    4. Using insights for investigation

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up - Problematic Logs

    We'll create logs with issues that need investigation.
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
    for _i in range(20):
        logs.append({
            "timestamp": (base_time + timedelta(seconds=_i * 5)).isoformat(),
            "level": "INFO",
            "message": f"Request processed: /api/users",
            "thread_id": f"http-{_i % 3}",
            "correlation_id": f"req-{_i:03d}"
        })

    # Error spike starts
    for _i in range(15):
        logs.append({
            "timestamp": (base_time + timedelta(seconds=100 + _i * 3)).isoformat(),
            "level": "ERROR",
            "message": "Database connection timeout after 30s",
            "thread_id": f"http-{_i % 3}",
            "correlation_id": f"req-{100 + _i:03d}",
            "error_code": "DB_TIMEOUT"
        })

    # Cascading failures
    for _i in range(10):
        logs.append({
            "timestamp": (base_time + timedelta(seconds=150 + _i * 2)).isoformat(),
            "level": "ERROR",
            "message": "Connection pool exhausted",
            "thread_id": f"http-{_i % 3}",
            "correlation_id": f"req-{150 + _i:03d}",
            "error_code": "POOL_EXHAUSTED"
        })

    # Some recovery
    for _i in range(5):
        logs.append({
            "timestamp": (base_time + timedelta(seconds=180 + _i * 5)).isoformat(),
            "level": "WARN",
            "message": "Retrying database connection",
            "thread_id": "recovery-1",
            "correlation_id": f"req-{180 + _i:03d}"
        })

    # Normal again
    for _i in range(10):
        logs.append({
            "timestamp": (base_time + timedelta(seconds=210 + _i * 5)).isoformat(),
            "level": "INFO",
            "message": "Request processed: /api/users",
            "thread_id": f"http-{_i % 3}",
            "correlation_id": f"req-{210 + _i:03d}"
        })

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "insights.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries")
    print(f"Scenario: Database timeout causing cascading failures")
    return Path, base_time, log_file, logs, temp_dir


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Automatic Insights

    `analyze_with_insights()` does the thinking for you - it analyzes
    logs and generates actionable insights automatically.
    """)
    return


@app.cell
def _():
    from logler.investigate import analyze_with_insights, explain, suggest_next_action

    return analyze_with_insights, explain, suggest_next_action


@app.cell
def _(analyze_with_insights, log_file):
    # Get automatic insights
    analysis = analyze_with_insights(
        files=[str(log_file)],
        auto_investigate=True
    )

    print("=== Automatic Analysis ===\n")
    _overview = analysis['overview']
    print(f"Total logs: {_overview['total_logs']}")
    print(f"Error count: {_overview['error_count']}")
    print(f"Error rate: {_overview['error_rate']:.1%}")
    print(f"Files analyzed: {_overview['files_analyzed']}")
    return (analysis,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Generated Insights

    Insights identify patterns and problems automatically.
    """)
    return


@app.cell
def _(analysis):
    print("=== INSIGHTS ===\n")

    for _insight in analysis['insights']:
        _severity = _insight.get('severity', 'medium').upper()
        _type = _insight.get('type', 'unknown')

        print(f"[{_severity}] {_insight.get('description', 'No description')}")
        print(f"  Type: {_type}")
        print(f"  Suggestion: {_insight.get('suggestion', 'N/A')}")
        print()
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Suggestions and Next Steps

    The analysis provides actionable suggestions.
    """)
    return


@app.cell
def _(analysis):
    print("=== SUGGESTIONS ===\n")
    for _suggestion in analysis.get('suggestions', []):
        print(f"• {_suggestion}")

    print("\n=== NEXT STEPS ===\n")
    for _step in analysis.get('next_steps', []):
        print(f"→ {_step}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Explaining Errors

    `explain()` provides human-friendly explanations of errors
    with context-specific advice.
    """)
    return


@app.cell
def _(explain):
    # Explain a timeout error
    timeout_explanation = explain(
        error_message="Database connection timeout after 30s",
        context="production"
    )

    print("=== Error Explanation ===\n")
    print(timeout_explanation)
    return (timeout_explanation,)


@app.cell
def _(explain):
    # Explain pool exhaustion
    pool_explanation = explain(
        error_message="Connection pool exhausted",
        context="production"
    )

    print("=== Pool Error Explanation ===\n")
    print(pool_explanation)
    return (pool_explanation,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Explaining with Full Entry Context

    You can also explain a full log entry for more context.
    """)
    return


@app.cell
def _(explain):
    # Full entry explanation
    _entry = {
        "timestamp": "2024-01-15T10:02:30Z",
        "level": "ERROR",
        "message": "Database connection timeout after 30s",
        "thread_id": "http-1",
        "correlation_id": "req-123",
        "error_code": "DB_TIMEOUT"
    }

    entry_explanation = explain(entry=_entry, context="production")
    print("=== Full Entry Explanation ===\n")
    print(entry_explanation)
    return (entry_explanation,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Suggesting Next Actions

    Based on current results, `suggest_next_action()` tells you
    what to investigate next.
    """)
    return


@app.cell
def _(log_file, suggest_next_action):
    from logler.investigate import search as _search

    # Get some results first
    _results = _search(files=[str(log_file)], level="ERROR", output_format="summary")

    # Get suggestions based on results
    suggestions = suggest_next_action(
        current_results=_results,
        investigation_context={"looking_for": "root cause of errors"}
    )

    print("=== Suggested Next Actions ===\n")
    for _s in suggestions:
        print(_s)
    return (suggestions,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Building an Investigation Workflow

    Combine these tools for effective investigation:
    """)
    return


@app.cell
def _(analyze_with_insights, explain, log_file, suggest_next_action):
    from logler.investigate import find_patterns as _find_patterns

    print("=" * 60)
    print("INVESTIGATION WORKFLOW")
    print("=" * 60)

    # Step 1: Get insights
    print("\n📊 Step 1: Automatic Analysis")
    print("-" * 40)
    _analysis = analyze_with_insights(files=[str(log_file)])
    print(f"Error rate: {_analysis['overview']['error_rate']:.1%}")
    print(f"Insights found: {len(_analysis['insights'])}")

    # Step 2: Understand the main error
    if _analysis['insights']:
        print("\n🔍 Step 2: Explain Top Issue")
        print("-" * 40)
        _top_insight = _analysis['insights'][0]
        print(f"Issue: {_top_insight['description']}")

        # Get explanation
        _explanation = explain(error_message="Database connection timeout")
        _lines = _explanation.split('\n')[:5]
        for _l in _lines:
            print(_l)

    # Step 3: Find patterns
    print("\n📈 Step 3: Find Patterns")
    print("-" * 40)
    _patterns = _find_patterns(files=[str(log_file)], min_occurrences=3)
    _pattern_list = _patterns.get('patterns', [])
    print(f"Found {len(_pattern_list)} repeating patterns")

    # Step 4: Get next steps
    print("\n➡️ Step 4: Next Actions")
    print("-" * 40)
    _next = suggest_next_action(_patterns)
    for _action in _next[:3]:
        print(f"  {_action}")

    print("\n" + "=" * 60)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned AI-powered analysis features:

    - **`analyze_with_insights(files)`** - Automatic analysis with insights
    - **`explain(entry|error_message)`** - Human-friendly explanations
    - **`suggest_next_action(results)`** - What to investigate next

    **Key Features:**
    | Function | Returns |
    |----------|---------|
    | analyze_with_insights | Overview, insights, suggestions, next_steps |
    | explain | Markdown explanation with causes and steps |
    | suggest_next_action | List of recommended actions |

    **Investigation Workflow:**
    1. Start with `analyze_with_insights()` for overview
    2. Use `explain()` to understand specific errors
    3. Follow `suggest_next_action()` recommendations
    4. Iterate until root cause is found

    **This concludes the Logler Tours!**

    You now know how to:
    1. Search and filter logs (Tour 01)
    2. Track threads and correlations (Tour 02)
    3. Visualize hierarchies (Tour 03)
    4. Manage investigations (Tour 04)
    5. Detect patterns (Tour 05)
    6. Create flamegraphs (Tour 06)
    7. Analyze error flow (Tour 07)
    8. Compare and diff (Tour 08)
    9. Export to Jaeger/Zipkin (Tour 09)
    10. Smart sampling (Tour 10)
    11. AI-powered insights (Tour 11)

    Happy debugging!
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
