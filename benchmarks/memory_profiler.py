"""Standalone memory profiler — measures peak Python heap allocation via tracemalloc.

Works with any version of logler. Produces JSON output compatible with the
benchmark comparison pipeline (same metadata keys as suite_memory/suite_db_source).

Usage:
    uv run python -m benchmarks.memory_profiler --scenario search --output results.json
    uv run python -m benchmarks.memory_profiler --scenario db_to_jsonl --output results.json
    uv run python -m benchmarks.memory_profiler --scenario all --output results.json
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path


def _get_vmrss_kb() -> int:
    """Current VmRSS from /proc/self/status (Linux).

    Unlike ru_maxrss (monotonic peak), VmRSS reflects current resident
    memory including Rust/C allocations invisible to tracemalloc.
    """
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def _measure_peak_kb(fn) -> tuple[float, int, int, int, int]:
    """Run fn() under tracemalloc and return (elapsed_ms, peak_kb, current_kb, vmrss_before_kb, vmrss_after_kb)."""
    gc.collect()
    vmrss_before = _get_vmrss_kb()
    tracemalloc.start()
    t0 = time.perf_counter()
    fn()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    vmrss_after = _get_vmrss_kb()
    return (
        elapsed_ms,
        round(peak_bytes / 1024),
        round(current_bytes / 1024),
        vmrss_before,
        vmrss_after,
    )


def profile_search(scales: tuple[int, ...] = (10_000, 50_000, 100_000)) -> list[dict]:
    """Profile search(level='INFO') memory at various scales."""
    # Import here so script works even if logler isn't fully set up
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

    from benchmarks.generators.logs import LogGenerator
    from logler.investigate import search

    gen = LogGenerator(seed=42)
    tmpdir = tempfile.mkdtemp(prefix="memprof_search_")
    results = []

    try:
        for size in scales:
            entries = gen.generate(size, error_rate=0.1)
            filepath = Path(tmpdir) / f"log_{size}.jsonl"
            gen.write_file(filepath, entries)

            elapsed_ms, peak_kb, current_kb, vmrss_before, vmrss_after = _measure_peak_kb(
                lambda f=str(filepath): search(files=[f], level="INFO", limit=100)
            )

            results.append(
                {
                    "scenario": "search_memory_profile",
                    "suite": "memory",
                    "parameter": "entries",
                    "value": size,
                    "timing": {
                        "median_ms": round(elapsed_ms, 2),
                        "p95_ms": round(elapsed_ms, 2),
                        "min_ms": round(elapsed_ms, 2),
                        "max_ms": round(elapsed_ms, 2),
                        "stddev_ms": 0,
                        "mean_ms": round(elapsed_ms, 2),
                        "iterations": 1,
                        "p99_ms": round(elapsed_ms, 2),
                        "total_ms": round(elapsed_ms, 2),
                    },
                    "rows": size,
                    "throughput": 0,
                    "metadata": {
                        "peak_memory_kb": peak_kb,
                        "current_memory_kb": current_kb,
                        "vmrss_before_kb": vmrss_before,
                        "vmrss_after_kb": vmrss_after,
                        "vmrss_delta_kb": vmrss_after - vmrss_before,
                    },
                }
            )
            print(
                f"  search {size:>7,}: peak={peak_kb:,} KB, current={current_kb:,} KB, "
                f"vmrss_delta={vmrss_after - vmrss_before:,} KB, {elapsed_ms:.0f}ms"
            )
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    return results


def profile_db_to_jsonl(scales: tuple[int, ...] = (10_000, 50_000, 100_000)) -> list[dict]:
    """Profile db_to_jsonl memory at various scales."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

    from benchmarks.generators.database import DatabaseGenerator
    from logler.db_source import db_to_jsonl

    gen = DatabaseGenerator(seed=42)
    tmpdir = tempfile.mkdtemp(prefix="memprof_db_")
    results = []

    try:
        for size in scales:
            rows = gen.generate(size)
            db_path = Path(tmpdir) / f"qler_{size}.db"
            gen.write_db(db_path, rows)

            path_holder = [None]

            def do_convert(p=str(db_path)):
                jsonl_path = db_to_jsonl(p)
                path_holder[0] = jsonl_path
                return jsonl_path

            elapsed_ms, peak_kb, current_kb, vmrss_before, vmrss_after = _measure_peak_kb(
                do_convert
            )

            # Clean up temp JSONL
            if path_holder[0] and os.path.exists(path_holder[0]):
                os.unlink(path_holder[0])

            results.append(
                {
                    "scenario": "db_source_memory",
                    "suite": "db_source",
                    "parameter": "rows",
                    "value": size,
                    "timing": {
                        "median_ms": round(elapsed_ms, 2),
                        "p95_ms": round(elapsed_ms, 2),
                        "min_ms": round(elapsed_ms, 2),
                        "max_ms": round(elapsed_ms, 2),
                        "stddev_ms": 0,
                        "mean_ms": round(elapsed_ms, 2),
                        "iterations": 1,
                        "p99_ms": round(elapsed_ms, 2),
                        "total_ms": round(elapsed_ms, 2),
                    },
                    "rows": size,
                    "throughput": 0,
                    "metadata": {
                        "peak_memory_kb": peak_kb,
                        "current_memory_kb": current_kb,
                        "vmrss_before_kb": vmrss_before,
                        "vmrss_after_kb": vmrss_after,
                        "vmrss_delta_kb": vmrss_after - vmrss_before,
                    },
                }
            )
            print(
                f"  db_to_jsonl {size:>7,}: peak={peak_kb:,} KB, current={current_kb:,} KB, "
                f"vmrss_delta={vmrss_after - vmrss_before:,} KB, {elapsed_ms:.0f}ms"
            )
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    return results


def main():
    parser = argparse.ArgumentParser(description="Standalone memory profiler for logler")
    parser.add_argument(
        "--scenario",
        choices=["search", "db_to_jsonl", "all"],
        default="all",
        help="Which scenario to profile",
    )
    parser.add_argument("--output", "-o", type=str, help="Output JSON file path")
    args = parser.parse_args()

    all_results = []

    if args.scenario in ("search", "all"):
        print("Profiling search memory...")
        all_results.extend(profile_search())

    if args.scenario in ("db_to_jsonl", "all"):
        print("Profiling db_to_jsonl memory...")
        all_results.extend(profile_db_to_jsonl())

    output = {
        "config": {"scale": "memory_profile", "warmup": 0, "iterations": 1},
        "system": {},
        "results": all_results,
        "summary": {
            "total_scenarios": len({r["scenario"] for r in all_results}),
            "total_measurements": len(all_results),
        },
    }

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(output, indent=2))
        print(f"\nResults saved to {args.output}")
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
