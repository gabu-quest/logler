#!/usr/bin/env python3
"""Logler demo -- generates sample logs and demonstrates key features.

Run:
    uv run python demo.py

Generates a temporary log file with realistic microservice entries,
then runs logler's investigation engine to show:
  1. Error search with summary output
  2. Thread hierarchy with bottleneck detection
  3. Cross-service timeline
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Generate sample log data
# ---------------------------------------------------------------------------

BASE = datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc)


def entry(offset_ms, level, message, thread_id, cid=None, tid=None, sid=None, psid=None, svc=None):
    ts = BASE + timedelta(milliseconds=offset_ms)
    d = {"timestamp": ts.isoformat(), "level": level, "message": message, "thread_id": thread_id}
    if cid:
        d["correlation_id"] = cid
    if tid:
        d["trace_id"] = tid
    if sid:
        d["span_id"] = sid
    if psid:
        d["parent_span_id"] = psid
    if svc:
        d["service"] = svc
    return d


ENTRIES = [
    # --- Request flow with hierarchy ---
    entry(
        0,
        "INFO",
        "POST /api/checkout started",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-root",
        svc="api",
    ),
    entry(
        5,
        "INFO",
        "Authenticating user",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-auth",
        "span-root",
        svc="api",
    ),
    entry(
        15,
        "INFO",
        "JWT validated for user:bob",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-auth",
        "span-root",
        svc="api",
    ),
    entry(
        20,
        "INFO",
        "Checking inventory",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-inv",
        "span-root",
        svc="api",
    ),
    entry(
        120,
        "WARN",
        "Inventory query slow (100ms)",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-inv",
        "span-root",
        svc="api",
    ),
    entry(
        130,
        "INFO",
        "Inventory confirmed",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-inv",
        "span-root",
        svc="api",
    ),
    entry(
        135,
        "INFO",
        "Processing payment",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-pay",
        "span-root",
        svc="api",
    ),
    entry(
        400,
        "ERROR",
        "Payment gateway timeout after 250ms",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-pay",
        "span-root",
        svc="api",
    ),
    entry(
        405,
        "ERROR",
        "POST /api/checkout failed 500",
        "api-1",
        "req-7742",
        "trace-a1",
        "span-root",
        svc="api",
    ),
    # --- Database service ---
    entry(25, "INFO", "SELECT * FROM inventory WHERE sku='ABC'", "db-pool-1", "req-7742", svc="db"),
    entry(115, "INFO", "Query returned 1 row (90ms)", "db-pool-1", "req-7742", svc="db"),
    # --- Cache service ---
    entry(22, "INFO", "Cache MISS for sku:ABC", "cache-1", "req-7742", svc="cache"),
    entry(118, "INFO", "Cache SET for sku:ABC ttl=300s", "cache-1", "req-7742", svc="cache"),
    # --- Background noise ---
    entry(50, "INFO", "Health check passed", "monitor", svc="api"),
    entry(200, "INFO", "Metrics exported", "metrics-1", svc="api"),
    entry(300, "DEBUG", "GC pause 12ms", "gc-thread", svc="api"),
    entry(500, "INFO", "Connection pool recycled", "db-pool-1", svc="db"),
    entry(600, "ERROR", "Redis connection refused", "cache-1", svc="cache"),
]


def write_logs(directory):
    """Write service-split log files. Returns dict of service -> [path]."""
    services = {}
    for e in ENTRIES:
        svc = e.get("service", "api")
        services.setdefault(svc, []).append(e)

    paths = {}
    for svc, entries in services.items():
        p = Path(directory) / f"{svc}.log"
        with open(p, "w") as f:
            for ent in sorted(entries, key=lambda x: x["timestamp"]):
                f.write(json.dumps(ent) + "\n")
        paths[svc] = [str(p)]

    # Also write a combined file
    combined = Path(directory) / "combined.log"
    with open(combined, "w") as f:
        for ent in sorted(ENTRIES, key=lambda x: x["timestamp"]):
            f.write(json.dumps(ent) + "\n")

    return paths, str(combined)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def main():
    try:
        import logler.investigate as investigate
    except ImportError:
        print("logler not installed. Run: uv pip install -e .")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        service_paths, combined = write_logs(tmpdir)
        all_files = [combined]

        print("=" * 60)
        print("  LOGLER DEMO")
        print("=" * 60)
        print()

        # 1. Search for errors
        print("--- 1. Search for errors (summary mode) ---")
        print()
        result = investigate.search(files=all_files, level="ERROR", output_format="summary")
        print(f"  Total errors found: {result['total_matches']}")
        print()

        # Also show full results
        full = investigate.search(files=all_files, level="ERROR")
        for r in full.get("results", []):
            e = r.get("entry", r)
            print(f"  [{e.get('level', '?')}] {e.get('message', '?')}")
        print()

        # 2. Thread hierarchy
        print("--- 2. Thread hierarchy (req-7742) ---")
        print()
        hierarchy = investigate.follow_thread_hierarchy(
            files=all_files,
            root_identifier="req-7742",
        )
        print(f"  Nodes: {hierarchy['total_nodes']}")
        if hierarchy.get("bottleneck"):
            bn = hierarchy["bottleneck"]
            print(f"  Bottleneck: {bn['node_id']} ({bn['duration_ms']}ms)")
        print()

        try:
            from logler.tree_formatter import format_tree

            tree = format_tree(hierarchy, mode="detailed", use_colors=False)
            for line in tree.split("\n"):
                print(f"  {line}")
        except Exception:
            pass
        print()

        # 3. Cross-service timeline
        print("--- 3. Cross-service timeline (req-7742) ---")
        print()
        timeline = investigate.cross_service_timeline(
            files=service_paths,
            correlation_id="req-7742",
        )
        print(f"  Total events: {timeline['total_entries']}")
        services_seen = {e["service"] for e in timeline["timeline"]}
        print(f"  Services: {', '.join(sorted(services_seen))}")
        for event in timeline["timeline"]:
            msg = event.get("entry", {}).get("message", "?")
            print(f"    [{event['service']}] {msg}")
        print()

        print("=" * 60)
        print("  Demo complete. Explore more with the interactive tours:")
        print("  uv run marimo edit examples/tours/tour_01_fundamentals.py")
        print("=" * 60)


if __name__ == "__main__":
    main()
