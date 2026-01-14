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
    # Logler Tour: Smart Sampling Strategies

    When dealing with large log files, you can't always process everything.
    Smart sampling gives you a **representative subset** without missing
    important information.

    **What you'll learn:**
    1. Representative sampling (balanced mix)
    2. Diverse sampling (maximum variety)
    3. Chronological sampling (time-spread)
    4. Errors-focused sampling (prioritize problems)
    5. Understanding coverage metrics

    Let's dive in!
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Setting Up - Large Log Dataset

    We'll create a larger dataset with various patterns.
    """
    )
    return


@app.cell
def _():
    import json
    import tempfile
    import random
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    random.seed(42)  # Reproducible

    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    # Generate 500 log entries over 1 hour
    services = ["api", "database", "cache", "worker", "auth"]
    messages_by_level = {
        "INFO": [
            "Request processed successfully",
            "Cache hit",
            "User authenticated",
            "Job completed",
            "Health check passed",
        ],
        "DEBUG": ["Query executed", "Token validated", "Cache lookup", "Processing started"],
        "WARN": ["High latency detected", "Cache miss", "Retry attempt", "Rate limit approaching"],
        "ERROR": [
            "Connection timeout",
            "Database query failed",
            "Authentication error",
            "Service unavailable",
        ],
    }

    # Distribution: 60% INFO, 20% DEBUG, 15% WARN, 5% ERROR
    level_weights = [("INFO", 60), ("DEBUG", 20), ("WARN", 15), ("ERROR", 5)]

    for _i in range(500):
        # Pick level based on weights
        _rand = random.randint(1, 100)
        _cumulative = 0
        _level = "INFO"
        for _l, _w in level_weights:
            _cumulative += _w
            if _rand <= _cumulative:
                _level = _l
                break

        _message = random.choice(messages_by_level[_level])
        _service = random.choice(services)
        _thread = f"thread-{random.randint(1, 20)}"

        logs.append(
            {
                "timestamp": (base_time + timedelta(seconds=_i * 7.2)).isoformat(),
                "level": _level,
                "message": _message,
                "service": _service,
                "thread_id": _thread,
                "correlation_id": f"req-{_i:04d}",
            }
        )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "large.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    # Count levels
    _level_counts = {}
    for _log in logs:
        _l = _log["level"]
        _level_counts[_l] = _level_counts.get(_l, 0) + 1

    print(f"Created {len(logs)} log entries")
    print(f"Level distribution: {_level_counts}")
    print("Time span: 1 hour")
    return Path, base_time, log_file, logs, random, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Representative Sampling

    Gets a **balanced mix** that reflects the overall distribution.
    Each log level is represented proportionally.
    """
    )
    return


@app.cell
def _():
    from logler.investigate import smart_sample

    return (smart_sample,)


@app.cell
def _(log_file, smart_sample):
    # Representative sampling
    rep_sample = smart_sample(files=[str(log_file)], strategy="representative", sample_size=50)

    print("=== Representative Sampling ===\n")
    print(f"Population size: {rep_sample['total_population']}")
    print(f"Sample size: {rep_sample['sample_size']}")
    print(f"Strategy: {rep_sample['strategy']}")

    _coverage = rep_sample["coverage"]
    print("\nLevel coverage:")
    for _level, _count in _coverage.get("level_coverage", {}).items():
        print(f"  {_level}: {_count}")
    print(f"Thread coverage: {_coverage.get('thread_coverage', 0)} unique threads")
    return (rep_sample,)


@app.cell
def _(rep_sample):
    print("=== Sample Messages (first 10) ===\n")
    for _entry in rep_sample["samples"][:10]:
        print(f"[{_entry.get('level', 'N/A'):5}] {_entry.get('message', 'N/A')}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Diverse Sampling

    Maximizes **variety** - gets as many different messages,
    threads, and services as possible.
    """
    )
    return


@app.cell
def _(log_file, smart_sample):
    # Diverse sampling
    diverse_sample = smart_sample(files=[str(log_file)], strategy="diverse", sample_size=50)

    print("=== Diverse Sampling ===\n")
    print(f"Sample size: {diverse_sample['sample_size']}")

    _coverage = diverse_sample["coverage"]
    print(f"Thread coverage: {_coverage.get('thread_coverage', 0)} unique threads")

    # Count unique messages
    _unique_msgs = len(set(_e.get("message", "") for _e in diverse_sample["samples"]))
    print(f"Unique messages: {_unique_msgs}")
    return (diverse_sample,)


@app.cell
def _(diverse_sample):
    print("=== Diverse Sample Messages (first 10) ===\n")
    _seen = set()
    _count = 0
    for _entry in diverse_sample["samples"]:
        _msg = _entry.get("message", "N/A")
        if _msg not in _seen:
            print(f"[{_entry.get('level', 'N/A'):5}] {_msg}")
            _seen.add(_msg)
            _count += 1
            if _count >= 10:
                break
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Chronological Sampling

    Spreads samples **evenly across time**.
    Good for detecting patterns that change over time.
    """
    )
    return


@app.cell
def _(log_file, smart_sample):
    # Chronological sampling
    chrono_sample = smart_sample(files=[str(log_file)], strategy="chronological", sample_size=50)

    print("=== Chronological Sampling ===\n")
    print(f"Sample size: {chrono_sample['sample_size']}")

    _coverage = chrono_sample["coverage"]
    print(f"Time coverage: {_coverage.get('time_coverage', 0):.0%}")
    return (chrono_sample,)


@app.cell
def _(chrono_sample):
    print("=== Chronological Sample (showing time spread) ===\n")

    _samples = chrono_sample["samples"]
    # Show first 5 and last 5 to demonstrate time spread
    print("First 5 samples:")
    for _entry in _samples[:5]:
        _ts = _entry.get("timestamp", "N/A")
        if _ts and "T" in _ts:
            _ts = _ts.split("T")[1][:8]
        print(f"  [{_ts}] {_entry.get('message', 'N/A')[:40]}")

    print("\n... (samples in between) ...\n")

    print("Last 5 samples:")
    for _entry in _samples[-5:]:
        _ts = _entry.get("timestamp", "N/A")
        if _ts and "T" in _ts:
            _ts = _ts.split("T")[1][:8]
        print(f"  [{_ts}] {_entry.get('message', 'N/A')[:40]}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. Errors-Focused Sampling

    **Prioritizes errors** and includes context around them.
    Best when investigating problems.
    """
    )
    return


@app.cell
def _(log_file, smart_sample):
    # Errors-focused sampling
    errors_sample = smart_sample(files=[str(log_file)], strategy="errors_focused", sample_size=50)

    print("=== Errors-Focused Sampling ===\n")
    print(f"Sample size: {errors_sample['sample_size']}")

    _coverage = errors_sample["coverage"]
    _level_cov = _coverage.get("level_coverage", {})

    # Compare error ratio in sample vs population
    _sample_errors = _level_cov.get("ERROR", 0) + _level_cov.get("FATAL", 0)
    _sample_total = sum(_level_cov.values())
    _sample_ratio = _sample_errors / _sample_total if _sample_total > 0 else 0

    print("\nLevel distribution in sample:")
    for _level, _count in _level_cov.items():
        _pct = (_count / _sample_total * 100) if _sample_total > 0 else 0
        print(f"  {_level}: {_count} ({_pct:.0f}%)")

    print(f"\nError ratio in sample: {_sample_ratio:.0%}")
    print("(Population had ~5% errors, sample should have more)")
    return (errors_sample,)


@app.cell
def _(errors_sample):
    print("=== Error Samples with Context ===\n")

    _error_count = 0
    for _entry in errors_sample["samples"]:
        if _entry.get("level") in ["ERROR", "FATAL"]:
            print(f"[{_entry.get('level')}] {_entry.get('message')}")
            print(f"  Service: {_entry.get('service')}")
            print(f"  Thread: {_entry.get('thread_id')}")
            print()
            _error_count += 1
            if _error_count >= 5:
                break
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 6. Comparing Strategies

    Different strategies serve different purposes:
    """
    )
    return


@app.cell
def _(chrono_sample, diverse_sample, errors_sample, rep_sample):
    print("=== Strategy Comparison ===\n")
    print(f"{'Strategy':<20} {'Unique Msgs':<15} {'Error %':<15} {'Best For':<30}")
    print("-" * 80)

    _samples_list = [
        (rep_sample, "Representative"),
        (diverse_sample, "Diverse"),
        (chrono_sample, "Chronological"),
        (errors_sample, "Errors-Focused"),
    ]

    _best_for = {
        "Representative": "Overall understanding",
        "Diverse": "Discovery, exploration",
        "Chronological": "Time-based patterns",
        "Errors-Focused": "Debugging, incidents",
    }

    for _sample, _name in _samples_list:
        _entries = _sample["samples"]
        _unique = len(set(_e.get("message", "") for _e in _entries))
        _errors = sum(1 for _e in _entries if _e.get("level") in ["ERROR", "FATAL"])
        _error_pct = (_errors / len(_entries) * 100) if _entries else 0

        print(f"{_name:<20} {_unique:<15} {_error_pct:<15.0f}% {_best_for[_name]:<30}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 7. Using Samples for Efficient Analysis

    Samples reduce data while preserving insights:
    """
    )
    return


@app.cell
def _(rep_sample):
    # Analyze patterns in the sample
    _samples = rep_sample["samples"]

    # Group by message
    _message_counts = {}
    for _entry in _samples:
        _msg = _entry.get("message", "unknown")
        _message_counts[_msg] = _message_counts.get(_msg, 0) + 1

    print("=== Patterns in Sample ===\n")
    _sorted = sorted(_message_counts.items(), key=lambda x: -x[1])
    for _msg, _count in _sorted[:5]:
        print(f"  {_count}x {_msg}")

    # Calculate reduction
    _reduction = (1 - rep_sample["sample_size"] / rep_sample["total_population"]) * 100
    print(f"\nData reduction: {_reduction:.0f}%")
    print(f"({rep_sample['sample_size']} samples from {rep_sample['total_population']} entries)")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned smart sampling strategies:

    - **`smart_sample(files, strategy="representative")`** - Balanced mix
    - **`smart_sample(files, strategy="diverse")`** - Maximum variety
    - **`smart_sample(files, strategy="chronological")`** - Time-spread
    - **`smart_sample(files, strategy="errors_focused")`** - Prioritize problems

    **When to Use Each:**
    | Strategy | Use When |
    |----------|----------|
    | Representative | General analysis, understanding distribution |
    | Diverse | Exploring, discovering patterns |
    | Chronological | Time-based issues, trends |
    | Errors-Focused | Debugging, incident response |

    **Key Benefits:**
    - Reduce data by 90%+ while keeping insights
    - Faster processing with LLMs (fewer tokens)
    - Coverage metrics show what you're capturing

    **Next Steps:**
    - **Tour 11**: AI-powered insights
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
