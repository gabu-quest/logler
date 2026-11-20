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


@pytest.fixture(scope="module")
def fifty_thousand_lines(tmp_path_factory):
    """50,000 text lines, one thread per 7 lines, times ascending; line n says "line n"."""
    path = tmp_path_factory.mktemp("order") / "big.log"
    path.write_text(
        "".join(
            f"2024-01-15 {n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d} INFO [t-{n % 7}] line {n}\n"
            for n in range(1, 50001)
        )
    )
    return str(path)


def test_the_index_keeps_file_order(rust_backend, fifty_thousand_lines):
    """Entries come back in file order: pages, context and a followed thread ascend, and
    a thread's lines are every seventh line."""
    import json

    investigator = rust_backend.PyInvestigator()
    investigator.load_files([fifty_thousand_lines])

    page = json.loads(investigator.get_entries_page(1000, 5000))
    assert [e["line_number"] for e in page["entries"]] == list(range(1001, 6001))

    context = json.loads(investigator.get_context(fifty_thousand_lines, 25000, 500, 500, False))
    assert [e["line_number"] for e in context["context_before"]] == list(range(24500, 25000))
    assert [e["line_number"] for e in context["context_after"]] == list(range(25001, 25501))

    timeline = json.loads(investigator.follow_thread([fifty_thousand_lines], "t-3", None, None))
    assert [e["line_number"] for e in timeline["entries"]] == list(range(3, 50001, 7))


def test_metadata_counts_by_level_add_up_to_the_lines_and_a_line_with_none_is_unknown(tmp_path):
    from logler.investigate import get_metadata

    path = tmp_path / "ten.log"
    path.write_text(
        "2024-01-15T10:00:00Z INFO one\n"
        "2024-01-15T10:00:01Z ERROR two\n"
        "continuation without a level\n"
        "2024-01-15T10:00:03Z WARN four\n"
        "2024-01-15T10:00:04Z INFO five\n"
        "  at somewhere.java:12\n"
        "2024-01-15T10:00:06Z INFO seven\n"
        "2024-01-15T10:00:07Z ERROR eight\n"
        "plain nine\n"
        "2024-01-15T10:00:09Z DEBUG ten\n"
    )
    (meta,) = get_metadata([str(path)])
    assert meta["log_levels"] == {"INFO": 3, "ERROR": 2, "WARN": 1, "DEBUG": 1, "UNKNOWN": 3}
    assert sum(meta["log_levels"].values()) == 10


def test_metadata_of_a_file_with_no_level_on_any_line_is_all_unknown(tmp_path):
    from logler.investigate import get_metadata

    path = tmp_path / "none.log"
    path.write_text("alpha\nbeta\ngamma\n")
    (meta,) = get_metadata([str(path)])
    assert meta["log_levels"] == {"UNKNOWN": 3}
