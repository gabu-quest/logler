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
    # Logler Tour: Advanced Filtering

    Precision filtering to cut through noise and find exactly what you need.

    **What you'll learn:**
    1. Multi-level filtering (comma-separated)
    2. Exclude patterns (kill health-check noise)
    3. `--tail` for recent entries
    4. `ids` command for discovery
    5. `--service` filtering
    6. `--max-bytes` budget control
    7. Combining filters for surgical precision
    8. Token optimization: `--count-only`, `--offset`, `--compact`, `--metadata-only`
    9. Relative time windows: `--after=-1h`, `--before=-30m`
    """
    )
    return


@app.cell
def _():
    from logler.investigate import search, extract_ids, RUST_AVAILABLE

    assert RUST_AVAILABLE, "Rust backend is required for this tour"
    print("Rust backend ready")
    return search, extract_ids


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Setup: Create Sample Logs

    We'll create 200 entries across 2 services, 4 levels, 4 threads,
    and 10 correlation IDs. This gives us known counts for verification.
    """
    )
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path

    _levels = ["INFO", "DEBUG", "WARN", "ERROR"]
    _threads = ["worker-0", "worker-1", "worker-2", "worker-3"]

    _f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log")
    for _i in range(200):
        _mm = _i // 60
        _ss = _i % 60
        _msg = "health check ok" if _i % 10 == 0 else f"Processing task {_i}"
        _entry = json.dumps(
            {
                "timestamp": f"2024-01-15T10:{_mm:02d}:{_ss:02d}Z",
                "level": _levels[_i % 4],
                "message": _msg,
                "thread_id": _threads[_i % 4],
                "correlation_id": f"corr-{_i % 10}",
                "service_name": "svc-alpha" if _i < 100 else "svc-beta",
            }
        )
        _f.write(_entry + "\n")
    _f.flush()
    LOG_FILE = _f.name
    print(f"Created {LOG_FILE} with 200 entries")
    print("  Levels: 50 each of INFO, DEBUG, WARN, ERROR")
    print("  Services: 100 svc-alpha, 100 svc-beta")
    print("  Threads: 50 each of worker-0 through worker-3")
    print("  20 entries contain 'health check ok'")
    return LOG_FILE, Path, json


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 1. Multi-Level Filtering

    Pass comma-separated levels to search for multiple levels at once.
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _result = search(files=[LOG_FILE], level="ERROR,WARN", limit=200)
    print(f"ERROR + WARN: {_result['total_matches']} matches (expected: 100)")

    _found_levels = set()
    for _item in _result["results"]:
        _entry = _item.get("entry", _item)
        _found_levels.add(_entry["level"])
    print(f"Levels found: {sorted(_found_levels)}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 2. Exclude Levels

    Remove noisy DEBUG entries without listing every other level.
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _result = search(files=[LOG_FILE], exclude_level="DEBUG", limit=200)
    print(f"Excluding DEBUG: {_result['total_matches']} matches (expected: 150)")

    _result2 = search(files=[LOG_FILE], exclude_level="DEBUG,INFO", limit=200)
    print(f"Excluding DEBUG+INFO: {_result2['total_matches']} matches (expected: 100)")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 3. Exclude Query Patterns

    Remove health check noise with a regex exclude pattern.
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _all_results = search(files=[LOG_FILE], limit=200)
    print(f"All entries: {_all_results['total_matches']}")

    _filtered = search(files=[LOG_FILE], exclude_query="health", limit=200)
    print(f"Without health checks: {_filtered['total_matches']} (expected: 180)")
    print(
        f"Removed {_all_results['total_matches'] - _filtered['total_matches']} health check entries"
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 4. Tail: Get Recent Entries

    `tail` returns the last N entries by timestamp, while reporting
    the full match count. Different from `limit` which takes the
    first N by relevance.
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _result = search(files=[LOG_FILE], tail=5)
    print(f"Total matches: {_result['total_matches']}")
    print(f"Returned: {len(_result['results'])} (last 5 by timestamp)")
    print()
    for _item in _result["results"]:
        _entry = _item.get("entry", _item)
        print(f"  {_entry.get('timestamp')} [{_entry['level']}] {_entry['message'][:50]}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 5. ID Discovery with extract_ids

    Before querying, discover what's in your logs: thread IDs,
    correlation IDs, trace IDs, and services with their counts.
    """
    )
    return


@app.cell
def _(extract_ids, LOG_FILE):
    _ids = extract_ids(files=[LOG_FILE])
    print(f"Total entries: {_ids['total_entries']}")
    print(f"\nThread IDs ({len(_ids['thread_ids'])}):")
    for _t in _ids["thread_ids"]:
        print(f"  {_t['id']}: {_t['count']} entries")
    print(f"\nServices ({len(_ids['services'])}):")
    for _s in _ids["services"]:
        print(f"  {_s['id']}: {_s['count']} entries")
    print(f"\nCorrelation IDs ({len(_ids['correlation_ids'])}):")
    for _c in _ids["correlation_ids"][:5]:
        print(f"  {_c['id']}: {_c['count']} entries")
    if len(_ids["correlation_ids"]) > 5:
        print(f"  ... and {len(_ids['correlation_ids']) - 5} more")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 6. Service Filtering

    Filter by service name to focus on a specific microservice.
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _result = search(files=[LOG_FILE], service_name="svc-alpha", limit=200)
    print(f"svc-alpha: {_result['total_matches']} entries (expected: 100)")

    _result2 = search(files=[LOG_FILE], service_name="svc-beta", level="ERROR", limit=200)
    print(f"svc-beta errors: {_result2['total_matches']} entries (expected: 25)")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 7. Multi-Value ID Filtering

    Pass comma-separated thread IDs or correlation IDs to match
    any of them (OR logic).
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _result = search(files=[LOG_FILE], thread_id="worker-0,worker-1", limit=200)
    print(f"worker-0 OR worker-1: {_result['total_matches']} entries (expected: 100)")

    _result2 = search(files=[LOG_FILE], correlation_id="corr-0,corr-1", limit=200)
    print(f"corr-0 OR corr-1: {_result2['total_matches']} entries (expected: 40)")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 8. Field Projection

    Limit output to only the fields you need, reducing noise
    and saving tokens for LLM context windows.
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _result = search(
        files=[LOG_FILE],
        level="ERROR",
        limit=3,
        fields=["timestamp", "level", "message"],
    )
    print("Projected to timestamp, level, message only:")
    for _item in _result["results"]:
        _entry = _item.get("entry", _item)
        print(f"  Keys: {sorted(_entry.keys())}")
        print(f"  {_entry}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 9. Max-Bytes Budget Control

    For LLM context windows, control the maximum output size.
    Results are binary-search truncated to fit the budget.
    """
    )
    return


@app.cell
def _(json):
    from logler.llm_cli import _apply_max_bytes

    _data = {
        "results": [{"entry": {"message": f"Log entry number {i}"}} for i in range(100)],
        "total_matches": 100,
    }

    _original_size = len(json.dumps(_data, default=str).encode("utf-8"))
    _truncated = _apply_max_bytes(dict(_data), 2000)
    _truncated_size = len(json.dumps(_truncated, default=str).encode("utf-8"))

    print(f"Original: {_original_size} bytes, {len(_data['results'])} results")
    print(f"Truncated: {_truncated_size} bytes, {len(_truncated['results'])} results")
    print(
        f"Metadata: truncated={_truncated.get('truncated')}, "
        f"at={_truncated.get('truncated_at')}, "
        f"original={_truncated.get('original_count')}"
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## 10. Combining Filters

    The real power comes from combining filters for surgical precision.
    """
    )
    return


@app.cell
def _(search, LOG_FILE):
    _result = search(
        files=[LOG_FILE],
        level="ERROR",
        service_name="svc-alpha",
        limit=200,
    )
    print(f"ERROR + svc-alpha: {_result['total_matches']} (expected: 25)")

    _result2 = search(
        files=[LOG_FILE],
        level="ERROR,WARN",
        exclude_query="health",
        tail=5,
    )
    print(
        f"WARN+ERROR without health, tail=5: {len(_result2['results'])} returned, "
        f"{_result2['total_matches']} total"
    )

    _result3 = search(
        files=[LOG_FILE],
        thread_id="worker-0,worker-2",
        exclude_level="DEBUG",
        limit=200,
    )
    print(f"worker-0/2 without DEBUG: {_result3['total_matches']}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## New: Token Optimization Flags (CLI)

    The LLM CLI now has flags to reduce token usage:

    - `--count-only` — Get match count without results
    - `--offset N` — Pagination (skip first N results)
    - `--compact` — Short field names (ts/lv/msg/th/cid/trc/svc)
    - `--metadata-only` — Aggregations without results array
    - `--after=-1h` / `--before=-30m` — Relative time windows

    These are CLI-only features (use `logler llm search` in terminal).
    The Python API provides equivalent functionality through its parameters.
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ### Equivalent Python patterns for CLI features

    ```bash
    # CLI: logler llm search app.log --count-only
    # Python: just use total_matches from result

    # CLI: logler llm search app.log --offset 50 --limit 25
    # Python: results = result['results'][50:75]

    # CLI: logler llm search app.log --compact
    # Python: use fields= to project only needed keys

    # CLI: logler llm search app.log --metadata-only
    # Python: just read total_matches and build aggregations from results
    ```
    """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
    ## Summary

    | Feature | Syntax | Example |
    |---------|--------|---------|
    | Multi-level | `level="ERROR,WARN"` | Search multiple levels at once |
    | Exclude level | `exclude_level="DEBUG"` | Remove noisy levels |
    | Exclude query | `exclude_query="health"` | Kill health check noise |
    | Tail | `tail=10` | Last 10 entries by timestamp |
    | Service filter | `service_name="api"` | Focus on one service |
    | Multi-value IDs | `thread_id="w-0,w-1"` | Match any of multiple IDs |
    | Field projection | `fields=[...]` | Limit output keys |
    | Max bytes | `_apply_max_bytes(data, N)` | Budget-controlled output |
    | ID discovery | `extract_ids(files)` | Find all IDs before querying |
    | Count-only | `--count-only` (CLI) | Scope estimation |
    | Pagination | `--offset N` (CLI) | Page through results |
    | Compact | `--compact` (CLI) | Short field names |
    | Metadata-only | `--metadata-only` (CLI) | Aggregations without entries |
    | Relative time | `--after=-1h` (CLI) | Recent time windows |
    """
    )
    return


@app.cell
def _(LOG_FILE, Path):
    Path(LOG_FILE).unlink(missing_ok=True)
    print("Cleaned up temp file")
    return


if __name__ == "__main__":
    app.run()
