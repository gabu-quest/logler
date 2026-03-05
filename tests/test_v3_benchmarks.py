"""Tests for v3 benchmark infrastructure: DatabaseGenerator, memory suite, db_source suite.

Validates:
- DatabaseGenerator determinism, schema, and status distribution
- Generated databases are compatible with db_to_jsonl pipeline
- All 5 new scenarios (15-19) produce correct BenchmarkResult structures
- Memory scenarios populate RSS metadata
- Comparison report renders memory narrative when present
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from benchmarks.core.config import BenchmarkConfig, ScaleConfig
from benchmarks.generators.database import DatabaseGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gen():
    return DatabaseGenerator(seed=42)


@pytest.fixture
def small_db(gen, tmp_path):
    """100-row SQLite database for fast tests."""
    rows = gen.generate(100)
    db_path = tmp_path / "test.db"
    gen.write_db(db_path, rows)
    return str(db_path)


@pytest.fixture
def fast_config():
    """Minimal config: 1 warmup, 1 iteration — fast enough for CI."""
    return BenchmarkConfig(
        scale=ScaleConfig(
            name="test",
            entry_counts=(100,),
            thread_count=5,
            correlations=10,
        ),
        warmup=1,
        iterations=1,
    )


# ---------------------------------------------------------------------------
# DatabaseGenerator: determinism
# ---------------------------------------------------------------------------


class TestDatabaseGeneratorDeterminism:
    def test_same_seed_same_output(self):
        """Two generators with same seed produce identical rows."""
        a = DatabaseGenerator(seed=42).generate(50)
        b = DatabaseGenerator(seed=42).generate(50)
        assert a == b

    def test_different_seed_different_output(self):
        """Different seeds produce different rows."""
        a = DatabaseGenerator(seed=42).generate(50)
        b = DatabaseGenerator(seed=99).generate(50)
        # ULIDs differ because suffix is RNG-derived
        assert a[0]["ulid"] != b[0]["ulid"]

    def test_generate_zero_rows(self):
        """generate(0) returns empty list."""
        rows = DatabaseGenerator(seed=42).generate(0)
        assert rows == []


# ---------------------------------------------------------------------------
# DatabaseGenerator: schema
# ---------------------------------------------------------------------------


class TestDatabaseGeneratorSchema:
    EXPECTED_COLUMNS = {
        "_id",
        "data",
        "_version",
        "ulid",
        "status",
        "queue_name",
        "priority",
        "eta",
        "lease_expires_at",
    }

    def test_table_created(self, small_db):
        """write_db creates qler_jobs table."""
        conn = sqlite3.connect(small_db)
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        conn.close()
        assert "qler_jobs" in tables

    def test_column_names(self, small_db):
        """qler_jobs has exactly the expected columns."""
        conn = sqlite3.connect(small_db)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(qler_jobs)").fetchall()}
        conn.close()
        assert columns == self.EXPECTED_COLUMNS

    def test_row_count(self, gen, tmp_path):
        """write_db returns correct count and DB has that many rows."""
        rows = gen.generate(200)
        db_path = tmp_path / "count.db"
        count = gen.write_db(db_path, rows)
        assert count == 200

        conn = sqlite3.connect(str(db_path))
        actual = conn.execute("SELECT COUNT(*) FROM qler_jobs").fetchone()[0]
        conn.close()
        assert actual == 200

    def test_ulids_unique(self, gen):
        """All ULIDs are unique within a generation run."""
        rows = gen.generate(1000)
        ulids = [r["ulid"] for r in rows]
        assert len(set(ulids)) == 1000

    def test_timestamps_sequential(self, gen):
        """Timestamps are strictly increasing."""
        rows = gen.generate(100)
        timestamps = [json.loads(r["data"])["created_at"] for r in rows]
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i - 1]

    def test_data_json_valid(self, gen):
        """Every data field is valid JSON with required keys."""
        rows = gen.generate(50)
        for row in rows:
            data = json.loads(row["data"])
            assert "task" in data
            assert "attempts" in data
            assert "correlation_id" in data
            assert "created_at" in data

    def test_write_db_returns_count(self, gen, tmp_path):
        """write_db returns the number of rows written."""
        rows = gen.generate(37)
        count = gen.write_db(tmp_path / "ret.db", rows)
        assert count == 37

    def test_write_db_overwrites_existing(self, gen, tmp_path):
        """write_db on existing file replaces it cleanly."""
        db_path = tmp_path / "overwrite.db"
        gen.write_db(db_path, gen.generate(10))
        gen.write_db(db_path, gen.generate(20))

        conn = sqlite3.connect(str(db_path))
        actual = conn.execute("SELECT COUNT(*) FROM qler_jobs").fetchone()[0]
        conn.close()
        assert actual == 20


# ---------------------------------------------------------------------------
# DatabaseGenerator: status distribution
# ---------------------------------------------------------------------------


class TestDatabaseGeneratorDistribution:
    def test_status_distribution(self, gen):
        """Status distribution roughly matches configured weights at 10K rows."""
        rows = gen.generate(10_000)
        counts = Counter(r["status"] for r in rows)
        total = sum(counts.values())

        # Allow +/-5% tolerance for statistical variation
        assert 0.60 <= counts["completed"] / total <= 0.70
        assert 0.10 <= counts["failed"] / total <= 0.20
        assert 0.05 <= counts["pending"] / total <= 0.15
        assert counts["running"] / total <= 0.10
        assert counts["cancelled"] / total <= 0.10

    def test_all_statuses_present(self, gen):
        """All 5 status values appear in a reasonably-sized generation."""
        rows = gen.generate(1000)
        statuses = {r["status"] for r in rows}
        assert statuses == {"completed", "failed", "pending", "running", "cancelled"}

    def test_all_queues_present(self, gen):
        """All queue names appear."""
        rows = gen.generate(1000)
        queues = {r["queue_name"] for r in rows}
        assert queues == {"default", "high", "low", "critical", "bulk"}


# ---------------------------------------------------------------------------
# Pipeline integration: DatabaseGenerator -> db_to_jsonl -> search
# ---------------------------------------------------------------------------


class TestDbPipelineIntegration:
    def test_db_to_jsonl_succeeds(self, small_db):
        """db_to_jsonl can read a generated database without error."""
        from logler.db_source import db_to_jsonl

        jsonl_path = db_to_jsonl(small_db)
        try:
            assert os.path.exists(jsonl_path)
            lines = Path(jsonl_path).read_text().strip().split("\n")
            assert len(lines) == 100
        finally:
            os.unlink(jsonl_path)

    def test_jsonl_entries_have_timestamps(self, small_db):
        """Every JSONL entry has a valid ISO 8601 timestamp."""
        from logler.db_source import db_to_jsonl

        jsonl_path = db_to_jsonl(small_db)
        try:
            lines = Path(jsonl_path).read_text().strip().split("\n")
            for line in lines:
                entry = json.loads(line)
                assert "timestamp" in entry
                # ISO 8601 timestamps contain 'T'
                assert "T" in entry["timestamp"]
        finally:
            os.unlink(jsonl_path)

    def test_jsonl_entries_have_levels(self, small_db):
        """Every JSONL entry has a log level from the mapping."""
        from logler.db_source import db_to_jsonl

        jsonl_path = db_to_jsonl(small_db)
        try:
            lines = Path(jsonl_path).read_text().strip().split("\n")
            levels = {json.loads(line)["level"] for line in lines}
            # qler_job_mapping maps statuses to INFO, ERROR, WARN
            assert levels <= {"INFO", "ERROR", "WARN"}
            assert len(levels) >= 2  # at least two different levels
        finally:
            os.unlink(jsonl_path)

    def test_end_to_end_search(self, small_db):
        """Full pipeline: generated DB -> db_to_jsonl -> Rust search returns results."""
        from logler.investigate import search_db

        results = search_db(small_db, level="ERROR")
        assert results["total_matches"] > 0
        for result in results["results"]:
            assert result["entry"]["level"] == "ERROR"

    def test_end_to_end_search_finds_failed_jobs(self, gen, tmp_path):
        """ERROR level maps to 'failed' status, search finds them."""
        rows = gen.generate(500)
        failed_count = sum(1 for r in rows if r["status"] == "failed")
        assert failed_count > 0  # sanity: generation produces failures

        db_path = tmp_path / "search.db"
        gen.write_db(db_path, rows)

        from logler.investigate import search_db

        results = search_db(str(db_path), level="ERROR")
        assert results["total_matches"] == failed_count


# ---------------------------------------------------------------------------
# Scenario smoke tests: setup -> run -> teardown at tiny scale
# ---------------------------------------------------------------------------


class TestMemorySuiteScenarios:
    """Smoke tests for scenarios 15-16 at minimal scale."""

    def _run_scenario(self, scenario_cls, config):
        """Helper: instantiate, setup, run, teardown, return results."""
        scenario = scenario_cls()
        scenario.setup(config)
        try:
            results = scenario.run(config)
        finally:
            scenario.teardown()
        return results

    def test_search_broad_query_returns_results(self, fast_config):
        """Scenario 15: produces BenchmarkResults with correct structure."""
        from benchmarks.suites.suite_memory import SearchBroadQuery

        # Patch MEMORY_SCALES to tiny for fast CI
        import benchmarks.suites.suite_memory as mod

        original = mod.MEMORY_SCALES
        mod.MEMORY_SCALES = (100,)
        try:
            results = self._run_scenario(SearchBroadQuery, fast_config)
        finally:
            mod.MEMORY_SCALES = original

        assert len(results) == 1
        r = results[0]
        assert r.scenario == "search_broad_query"
        assert r.suite == "memory"
        assert r.parameter == "entries"
        assert r.value == 100
        assert r.throughput > 0
        assert r.timing.median_ms > 0

    def test_search_memory_profile_has_rss_metadata(self, fast_config):
        """Scenario 16: metadata contains peak_rss_kb, allocated_rss_kb, rss_before_kb."""
        from benchmarks.suites.suite_memory import SearchMemoryProfile

        import benchmarks.suites.suite_memory as mod

        original = mod.MEMORY_SCALES
        mod.MEMORY_SCALES = (100,)
        try:
            results = self._run_scenario(SearchMemoryProfile, fast_config)
        finally:
            mod.MEMORY_SCALES = original

        assert len(results) == 1
        r = results[0]
        assert r.scenario == "search_memory_profile"
        assert r.suite == "memory"
        meta = r.metadata
        assert "peak_rss_kb" in meta
        assert "allocated_rss_kb" in meta
        assert "rss_before_kb" in meta
        assert isinstance(meta["peak_rss_kb"], int)
        assert isinstance(meta["rss_before_kb"], int)
        assert meta["peak_rss_kb"] > 0


class TestDbSourceSuiteScenarios:
    """Smoke tests for scenarios 17-19 at minimal scale."""

    def _run_scenario(self, scenario_cls, config):
        scenario = scenario_cls()
        scenario.setup(config)
        try:
            results = scenario.run(config)
        finally:
            scenario.teardown()
        return results

    def test_db_to_jsonl_scaling_returns_results(self, fast_config):
        """Scenario 17: produces results with throughput."""
        from benchmarks.suites.suite_db_source import DbToJsonlScaling

        import benchmarks.suites.suite_db_source as mod

        original = mod.DB_TIMING_SCALES
        mod.DB_TIMING_SCALES = (100,)
        try:
            results = self._run_scenario(DbToJsonlScaling, fast_config)
        finally:
            mod.DB_TIMING_SCALES = original

        assert len(results) == 1
        r = results[0]
        assert r.scenario == "db_to_jsonl_scaling"
        assert r.suite == "db_source"
        assert r.parameter == "rows"
        assert r.value == 100
        assert r.throughput > 0

    def test_db_source_search_returns_results(self, fast_config):
        """Scenario 18: end-to-end DB search produces results."""
        from benchmarks.suites.suite_db_source import DbSourceSearch

        import benchmarks.suites.suite_db_source as mod

        original = mod.DB_TIMING_SCALES
        mod.DB_TIMING_SCALES = (100,)
        try:
            results = self._run_scenario(DbSourceSearch, fast_config)
        finally:
            mod.DB_TIMING_SCALES = original

        assert len(results) == 1
        r = results[0]
        assert r.scenario == "db_source_search"
        assert r.suite == "db_source"
        assert r.throughput > 0

    def test_db_source_memory_has_rss_metadata(self, fast_config):
        """Scenario 19: metadata contains RSS fields."""
        from benchmarks.suites.suite_db_source import DbSourceMemory

        import benchmarks.suites.suite_db_source as mod

        original = mod.DB_MEMORY_SCALES
        mod.DB_MEMORY_SCALES = (100,)
        try:
            results = self._run_scenario(DbSourceMemory, fast_config)
        finally:
            mod.DB_MEMORY_SCALES = original

        assert len(results) == 1
        r = results[0]
        assert r.scenario == "db_source_memory"
        assert r.suite == "db_source"
        meta = r.metadata
        assert "peak_rss_kb" in meta
        assert "allocated_rss_kb" in meta
        assert "rss_before_kb" in meta
        assert meta["peak_rss_kb"] > 0

    def test_teardown_cleans_tmpdir(self, fast_config):
        """Teardown removes the temporary directory."""
        from benchmarks.suites.suite_db_source import DbToJsonlScaling

        import benchmarks.suites.suite_db_source as mod

        original = mod.DB_TIMING_SCALES
        mod.DB_TIMING_SCALES = (100,)
        try:
            scenario = DbToJsonlScaling()
            scenario.setup(fast_config)
            tmpdir = scenario.tmpdir
            assert os.path.isdir(tmpdir)
            scenario.run(fast_config)
            scenario.teardown()
            assert not os.path.exists(tmpdir)
        finally:
            mod.DB_TIMING_SCALES = original


# ---------------------------------------------------------------------------
# Suite registration
# ---------------------------------------------------------------------------


class TestSuiteRegistration:
    def test_all_suites_count(self):
        """7 suites registered total."""
        from benchmarks.suites import ALL_SUITES

        assert len(ALL_SUITES) == 7

    def test_new_suites_registered(self):
        """memory and db_source suites are in the registry."""
        from benchmarks.suites import ALL_SUITES

        assert "memory" in ALL_SUITES
        assert "db_source" in ALL_SUITES

    def test_total_scenario_count(self):
        """19 scenarios across all suites."""
        from benchmarks.suites import get_scenarios

        scenarios = get_scenarios()
        assert len(scenarios) == 19

    def test_new_scenario_names(self):
        """All 5 new scenario names are present."""
        from benchmarks.suites import get_scenarios

        names = {s.name for s in get_scenarios()}
        assert "search_broad_query" in names
        assert "search_memory_profile" in names
        assert "db_to_jsonl_scaling" in names
        assert "db_source_search" in names
        assert "db_source_memory" in names


# ---------------------------------------------------------------------------
# Comparison report: memory narrative
# ---------------------------------------------------------------------------


class TestComparisonMemoryNarrative:
    def test_memory_narrative_renders_when_present(self, tmp_path):
        """Memory Safety Profile section appears when memory scenarios are in results."""
        from benchmarks.plotting.comparison import _write_comparison_report

        baseline = {
            "config": {"scale": "small", "warmup": 1, "iterations": 1},
            "system": {},
            "results": [],
        }
        current = {
            "config": {"scale": "small", "warmup": 1, "iterations": 1},
            "system": {},
            "results": [
                {
                    "scenario": "search_memory_profile",
                    "suite": "memory",
                    "parameter": "entries",
                    "value": 10000,
                    "timing": {
                        "median_ms": 50,
                        "p95_ms": 55,
                        "min_ms": 45,
                        "max_ms": 60,
                        "stddev_ms": 3,
                        "mean_ms": 50,
                        "iterations": 1,
                        "p99_ms": 58,
                        "total_ms": 50,
                    },
                    "rows": 10000,
                    "throughput": 200000,
                    "metadata": {
                        "peak_rss_kb": 500000,
                        "allocated_rss_kb": 1024,
                        "rss_before_kb": 498976,
                    },
                },
            ],
        }

        report_path = tmp_path / "COMPARISON.md"
        charts_dir = tmp_path / "charts"
        charts_dir.mkdir()

        _write_comparison_report(report_path, baseline, current, [], {}, charts_dir, None)

        content = report_path.read_text()
        assert "## Memory Safety Profile" in content
        assert "search_memory_profile" in content
        assert "500,000" in content  # peak_rss_kb formatted
        assert "1,024" in content  # allocated_rss_kb formatted

    def test_memory_narrative_absent_when_no_memory_scenarios(self, tmp_path):
        """Memory Safety Profile section is absent when no memory scenarios."""
        from benchmarks.plotting.comparison import _write_comparison_report

        baseline = {
            "config": {"scale": "small", "warmup": 1, "iterations": 1},
            "system": {},
            "results": [],
        }
        current = {
            "config": {"scale": "small", "warmup": 1, "iterations": 1},
            "system": {},
            "results": [
                {
                    "scenario": "search_scaling",
                    "suite": "search",
                    "parameter": "entries",
                    "value": 1000,
                    "timing": {
                        "median_ms": 10,
                        "p95_ms": 12,
                        "min_ms": 9,
                        "max_ms": 13,
                        "stddev_ms": 1,
                        "mean_ms": 10,
                        "iterations": 3,
                        "p99_ms": 12.5,
                        "total_ms": 30,
                    },
                    "rows": 1000,
                    "throughput": 100000,
                    "metadata": {},
                },
            ],
        }

        report_path = tmp_path / "COMPARISON.md"
        charts_dir = tmp_path / "charts"
        charts_dir.mkdir()

        _write_comparison_report(report_path, baseline, current, [], {}, charts_dir, None)

        content = report_path.read_text()
        assert "## Memory Safety Profile" not in content
