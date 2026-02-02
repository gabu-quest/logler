from __future__ import annotations

import time
from pathlib import Path

import pytest

HUGE_LOG = Path("examples/logs/huge/massive_incident.log")
SAMPLE_CORRELATION = "req-0001"

# Skip tests if huge log file doesn't exist (gitignored, not in CI)
requires_huge_log = pytest.mark.skipif(
    not HUGE_LOG.exists(),
    reason=f"Huge log file not found: {HUGE_LOG} (gitignored, local only)",
)


@pytest.fixture(scope="module")
def inv(investigate_module):
    return investigate_module


def test_rust_backend_must_be_present(inv, rust_backend):
    assert getattr(inv, "RUST_AVAILABLE", False) is True
    assert hasattr(rust_backend, "PyInvestigator")


@requires_huge_log
def test_rust_metadata_and_search_fast(inv):
    files = [str(HUGE_LOG)]
    meta = inv.get_metadata(files)
    assert meta, "no metadata returned from Rust backend"
    assert meta[0]["lines"] == 10000
    assert meta[0]["unique_threads"] > 0
    assert meta[0]["log_levels"].get("ERROR", 0) > 0

    start = time.perf_counter()
    res = inv.search(files=files, query="Database timeout", level="ERROR", limit=50)
    elapsed = time.perf_counter() - start

    assert res["total_matches"] > 0
    assert res["results"], "Rust search returned no entries"
    assert res["search_time_ms"] < 1000
    assert elapsed < 1.5, f"Rust search wall time too slow: {elapsed:.3f}s"
    assert all(entry["entry"].get("service_name") for entry in res["results"])
    assert any("Database timeout" in entry["entry"]["message"] for entry in res["results"])


@requires_huge_log
def test_rust_follow_thread_has_duration(inv):
    timeline = inv.follow_thread(files=[str(HUGE_LOG)], correlation_id=SAMPLE_CORRELATION)
    assert timeline["entries"], "follow_thread returned no entries"
    assert timeline["total_entries"] == len(timeline["entries"])
    assert timeline["duration_ms"] is not None
    assert timeline["duration_ms"] > 0
    assert timeline["unique_spans"]
    assert all(entry["correlation_id"] == SAMPLE_CORRELATION for entry in timeline["entries"])
    assert all(entry.get("service_name") for entry in timeline["entries"])
