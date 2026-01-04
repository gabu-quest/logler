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
    # Logler Tour: Pattern Detection

    Finding recurring issues in logs is crucial for identifying
    systemic problems. Logler helps you detect patterns automatically.

    **What you'll learn:**
    1. Finding repeated errors
    2. Analyzing pattern frequency
    3. Identifying affected threads/services
    4. Time-based pattern analysis
    5. Using patterns for root cause analysis

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up - Logs with Patterns

    We'll create logs that contain recurring error patterns,
    simulating a system with intermittent issues.
    """)
    return


@app.cell
def _():
    import json
    import tempfile
    import random
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    random.seed(42)  # Reproducible results

    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    # Common error patterns that will repeat
    error_patterns = [
        ("Connection refused to redis:6379", "cache"),
        ("Connection refused to redis:6379", "cache"),
        ("Connection refused to redis:6379", "cache"),
        ("Database query timeout after 30s", "database"),
        ("Database query timeout after 30s", "database"),
        ("Rate limit exceeded for API key: api_key_123", "api"),
        ("Rate limit exceeded for API key: api_key_123", "api"),
        ("Rate limit exceeded for API key: api_key_123", "api"),
        ("Rate limit exceeded for API key: api_key_123", "api"),
        ("OutOfMemoryError in worker process", "worker"),
        ("OutOfMemoryError in worker process", "worker"),
        ("SSL certificate validation failed", "auth"),
    ]

    # Generate logs over a 10-minute period
    for i in range(200):
        ts = base_time + timedelta(seconds=i * 3)
        thread_id = f"worker-{i % 5}"

        if i % 10 == 0 and i // 10 < len(error_patterns):
            # Insert error pattern
            msg, component = error_patterns[i // 10]
            logs.append({
                "timestamp": ts.isoformat(),
                "level": "ERROR",
                "message": msg,
                "component": component,
                "thread_id": thread_id,
                "correlation_id": f"req-{i:04d}"
            })
        elif i % 7 == 0:
            # Warning
            logs.append({
                "timestamp": ts.isoformat(),
                "level": "WARN",
                "message": f"High latency detected: {random.randint(500, 2000)}ms",
                "component": "api",
                "thread_id": thread_id,
                "correlation_id": f"req-{i:04d}"
            })
        else:
            # Normal log
            logs.append({
                "timestamp": ts.isoformat(),
                "level": "INFO",
                "message": f"Request processed successfully",
                "component": random.choice(["api", "worker", "cache"]),
                "thread_id": thread_id,
                "correlation_id": f"req-{i:04d}"
            })

    # Shuffle to simulate real log collection
    random.shuffle(logs)

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "patterns.log"
    with open(log_file, "w") as f:
        for log in logs:
            f.write(json.dumps(log) + "\n")

    print(f"Created {len(logs)} log entries")
    print(f"With {len(error_patterns)} error instances from {len(set(p[0] for p in error_patterns))} unique patterns")
    return Path, base_time, error_patterns, log_file, logs, random, temp_dir


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Finding Patterns

    The `find_patterns()` function automatically groups similar
    errors and identifies recurring issues.
    """)
    return


@app.cell
def _():
    from logler.investigate import find_patterns, search

    return find_patterns, search


@app.cell
def _(find_patterns, log_file):
    # Find patterns with at least 2 occurrences
    patterns = find_patterns(files=[str(log_file)], min_occurrences=2)

    print(f"=== Patterns Found ===\n")
    print(f"Total patterns: {len(patterns.get('patterns', []))}\n")

    for p in patterns.get('patterns', []):
        print(f"Pattern: {p['pattern'][:60]}...")
        print(f"  Occurrences: {p['occurrences']}")
        print(f"  Type: {p['pattern_type']}")
        print(f"  First seen: {p['first_seen']}")
        print(f"  Last seen: {p['last_seen']}")
        print(f"  Affected threads: {p['affected_threads']}")
        print()
    return (patterns,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Analyzing Top Patterns

    Let's dive deeper into the most frequent issues:
    """)
    return


@app.cell
def _(patterns):
    # Sort by occurrence count
    sorted_patterns = sorted(
        patterns.get('patterns', []),
        key=lambda p: p['occurrences'],
        reverse=True
    )

    print("=== Top 3 Most Frequent Issues ===\n")

    for i, p in enumerate(sorted_patterns[:3], 1):
        print(f"{i}. {p['pattern']}")
        print(f"   Count: {p['occurrences']} occurrences")

        # Calculate time span
        from datetime import datetime
        first = datetime.fromisoformat(p['first_seen'].replace('Z', '+00:00'))
        last = datetime.fromisoformat(p['last_seen'].replace('Z', '+00:00'))
        duration = (last - first).total_seconds()
        print(f"   Duration: {duration:.0f} seconds")

        # Frequency
        if duration > 0:
            freq = p['occurrences'] / (duration / 60)
            print(f"   Frequency: {freq:.2f} per minute")

        print(f"   Threads affected: {len(p['affected_threads'])}")
        print()
    return first, last, sorted_patterns


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Identifying Affected Components

    Group patterns by component to find systemic issues:
    """)
    return


@app.cell
def _(patterns):
    # Analyze patterns by looking at examples
    component_issues = {}

    for p in patterns.get('patterns', []):
        # Look at the first example to get component
        for example in p.get('examples', []):
            component = example.get('component', 'unknown')
            if component not in component_issues:
                component_issues[component] = {
                    'patterns': [],
                    'total_occurrences': 0
                }
            component_issues[component]['patterns'].append(p['pattern'][:50])
            component_issues[component]['total_occurrences'] += p['occurrences']
            break  # One component per pattern

    print("=== Issues by Component ===\n")
    for component, data in sorted(component_issues.items(), key=lambda x: x[1]['total_occurrences'], reverse=True):
        print(f"{component}:")
        print(f"  Total error occurrences: {data['total_occurrences']}")
        print(f"  Patterns:")
        for pattern in data['patterns']:
            print(f"    - {pattern}...")
        print()
    return (component_issues,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Examining Pattern Examples

    Each pattern includes example log entries for context:
    """)
    return


@app.cell
def _(patterns):
    # Get the most frequent pattern
    top_pattern = patterns.get('patterns', [{}])[0]

    print(f"=== Examples for Top Pattern ===")
    print(f"Pattern: {top_pattern.get('pattern', 'N/A')}\n")

    for i, example in enumerate(top_pattern.get('examples', [])[:3], 1):
        print(f"Example {i}:")
        print(f"  Timestamp: {example.get('timestamp')}")
        print(f"  Thread: {example.get('thread_id')}")
        print(f"  Correlation: {example.get('correlation_id')}")
        print(f"  Message: {example.get('message')}")
        print()
    return (top_pattern,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Correlating Patterns with Threads

    See which threads are most affected:
    """)
    return


@app.cell
def _(patterns):
    # Count thread occurrences across all patterns
    thread_impact = {}

    for p in patterns.get('patterns', []):
        for thread in p.get('affected_threads', []):
            if thread not in thread_impact:
                thread_impact[thread] = 0
            thread_impact[thread] += 1

    print("=== Thread Impact Analysis ===\n")
    for thread, count in sorted(thread_impact.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * count
        print(f"{thread}: {bar} ({count} patterns)")
    return (thread_impact,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Root Cause Analysis

    Use patterns to identify the root cause:
    """)
    return


@app.cell
def _(patterns):
    from datetime import datetime

    print("=== Root Cause Analysis ===\n")

    # Find the earliest error pattern
    all_patterns = patterns.get('patterns', [])
    if all_patterns:
        earliest = min(all_patterns, key=lambda p: p['first_seen'])

        print("FIRST ERROR DETECTED:")
        print(f"  Pattern: {earliest['pattern']}")
        print(f"  Time: {earliest['first_seen']}")
        print(f"  Threads: {earliest['affected_threads']}")

        # Find related errors (happening in same timeframe)
        earliest_time = datetime.fromisoformat(earliest['first_seen'].replace('Z', '+00:00'))

        print("\nRELATED ERRORS (within 1 minute):")
        for p in all_patterns:
            p_time = datetime.fromisoformat(p['first_seen'].replace('Z', '+00:00'))
            delta = abs((p_time - earliest_time).total_seconds())
            if delta <= 60 and p['pattern'] != earliest['pattern']:
                print(f"  - {p['pattern'][:50]}... (after {delta:.0f}s)")

        print("\nHYPOTHESIS:")
        print(f"  The {earliest['pattern'][:30]}... errors started first")
        print(f"  and may have caused cascading failures.")
    return (earliest,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Pattern Severity Assessment

    Prioritize patterns for fixing:
    """)
    return


@app.cell
def _(patterns):
    from datetime import datetime

    print("=== Pattern Severity Assessment ===\n")
    print(f"{'Priority':<10} {'Pattern':<45} {'Score':<8} {'Reason':<20}")
    print("-" * 85)

    for i, p in enumerate(patterns.get('patterns', [])[:5], 1):
        # Calculate severity score
        occurrences = p['occurrences']
        threads = len(p['affected_threads'])

        # More occurrences = more severe
        # More threads affected = more severe
        score = occurrences * 2 + threads * 3

        if occurrences >= 4:
            reason = "High frequency"
        elif threads >= 3:
            reason = "Wide impact"
        else:
            reason = "Notable issue"

        priority = f"P{min(i, 4)}"
        pattern_short = p['pattern'][:43] + ".." if len(p['pattern']) > 45 else p['pattern']

        print(f"{priority:<10} {pattern_short:<45} {score:<8} {reason:<20}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned how to detect and analyze patterns:

    - **`find_patterns(files, min_occurrences)`** - Find recurring issues
    - **Pattern analysis** - Frequency, affected threads, time span
    - **Component grouping** - Find systemic issues
    - **Root cause analysis** - Trace back to first error
    - **Severity assessment** - Prioritize fixes

    **Key Insights:**
    - Patterns reveal systemic issues, not just one-off errors
    - Affected threads show blast radius
    - Time analysis reveals cascade failures
    - Early errors often cause later ones

    **This concludes the Logler Tours!**

    You now know how to:
    1. Search and filter logs (Tour 01)
    2. Track threads and correlations (Tour 02)
    3. Visualize hierarchies (Tour 03)
    4. Manage investigations (Tour 04)
    5. Detect patterns (Tour 05)

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
