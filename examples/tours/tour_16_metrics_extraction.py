import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
    # Logler Tour: Numeric Value Extraction & Metrics

    Log files often contain numeric values — response times, memory usage,
    queue depths. Logler can extract these, compute statistics, detect
    anomalies, and bucket values into time series.

    **What you'll learn:**
    1. Extracting numeric fields from log messages
    2. Computing summary statistics (min, max, mean, p95, p99)
    3. Detecting anomalies via z-score
    4. Time-series bucketing for trend analysis
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

    random.seed(42)

    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    for i in range(60):
        # Normal response times: 50-200ms
        response_time = random.gauss(120, 30)
        # Memory usage: 500-800MB
        memory = random.gauss(650, 50)
        # Queue depth: 0-10
        queue = max(0, int(random.gauss(3, 2)))

        # Inject anomalies at i=25 and i=45
        if i == 25:
            response_time = 2500  # Massive spike
            memory = 1800  # Memory leak
        elif i == 45:
            response_time = 3200  # Another spike
            queue = 50  # Queue backup

        logs.append(
            {
                "timestamp": (base_time + timedelta(seconds=i * 10)).isoformat(),
                "level": "INFO" if response_time < 500 else "WARN",
                "message": (
                    f"Request processed: duration={response_time:.0f}ms "
                    f"memory={memory:.0f}MB queue_depth={queue}"
                ),
                "thread_id": f"worker-{i % 4}",
                "duration_ms": round(response_time, 1),
            }
        )

    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "metrics_demo.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries with numeric fields")
    print("Fields: duration_ms, memory (in message), queue_depth (in message)")
    return log_file, temp_dir


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Extracting Metrics

    Use `extract_metrics` to pull numeric values from structured fields
    and key=value patterns in messages:
    """
    )
    return


@app.cell
def _(log_file):
    from logler.investigate import search
    from logler.metrics import extract_metrics

    # First, search for all entries
    search_result = search(files=[str(log_file)], query="", limit=1000)
    entries = [item["entry"] for item in search_result.get("results", [])]

    result = extract_metrics(
        entries=entries,
        bucket_size="60s",
        anomaly_threshold=2.0,
    )

    print("=== Metrics Extracted ===\n")
    print(f"Entries scanned: {len(entries)}")
    print(f"Fields found: {list(result['fields'].keys())}")

    for _field_name, _data in result["fields"].items():
        print(f"\n  {_field_name}:")
        print(f"    Data points: {_data['count']}")
        print(f"    Anomalies: {len(_data.get('anomalies', []))}")
        if _data.get("unit"):
            print(f"    Unit: {_data['unit']}")
    return result


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Statistical Summary

    Each field gets full statistics — min, max, mean, median, p95, p99:
    """
    )
    return


@app.cell
def _(result):
    print("=== Statistical Summary ===\n")

    for _field_name, _data in result["fields"].items():
        stats = _data["stats"]
        print(f"--- {_field_name} ---")
        print(f"  Min:    {stats['min']:.1f}")
        print(f"  Max:    {stats['max']:.1f}")
        print(f"  Mean:   {stats['mean']:.1f}")
        print(f"  Median: {stats['median']:.1f}")
        print(f"  Stddev: {stats['stddev']:.1f}")
        print(f"  P95:    {stats['p95']:.1f}")
        print(f"  P99:    {stats['p99']:.1f}")
        print()
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Anomaly Detection

    Z-score anomaly detection identifies outliers that deviate
    significantly from the series mean:
    """
    )
    return


@app.cell
def _(result):
    print("=== Anomalies Detected ===\n")

    total_anomalies = 0
    for _field_name, _data in result["fields"].items():
        anomalies = _data.get("anomalies", [])
        if anomalies:
            print(f"--- {_field_name}: {len(anomalies)} anomalies ---")
            for a in anomalies:
                print(
                    f"  Value: {a['value']:.1f}  "
                    f"Z-score: {a['z_score']:.2f}  "
                    f"at {a.get('timestamp', 'N/A')}"
                )
            total_anomalies += len(anomalies)
            print()

    if total_anomalies == 0:
        print("No anomalies detected (all values within 2 std deviations)")
    else:
        print(f"Total anomalies across all fields: {total_anomalies}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Time-Series Buckets

    Values are aggregated into time buckets for trend analysis:
    """
    )
    return


@app.cell
def _(result):
    print("=== Time-Series Buckets ===\n")

    # Show buckets for the first field that has them
    for _field_name, _data in result["fields"].items():
        buckets = _data.get("buckets", [])
        if buckets:
            print(f"--- {_field_name} (bucket_size=60s) ---")
            print(f"{'Start':<28} {'Min':>8} {'Max':>8} {'Avg':>8} {'Count':>6}")
            print("-" * 65)
            for b in buckets[:10]:  # Show first 10 buckets
                print(
                    f"{b['start']:<28} "
                    f"{b['min']:>8.1f} "
                    f"{b['max']:>8.1f} "
                    f"{b['avg']:>8.1f} "
                    f"{b['count']:>6}"
                )
            if len(buckets) > 10:
                print(f"  ... and {len(buckets) - 10} more buckets")
            print()
            break  # Only show first field
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    You've learned logler's metrics extraction capabilities:

    - **`extract_metrics()`** — Pull numeric values from structured fields and messages
    - **`stats`** — Full statistical summary (min, max, mean, median, stddev, p95, p99)
    - **Anomaly detection** — Z-score identifies outliers automatically
    - **Time-series buckets** — Aggregated trends over configurable windows

    **Use cases:**
    - Monitor response time degradation
    - Detect memory leaks (growing memory values)
    - Identify queue backup events
    - Correlate performance metrics with error spikes

    **Next Steps:**
    - **Tour 17**: Format auto-detection and template mining
    """
    )
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return


if __name__ == "__main__":
    app.run()
