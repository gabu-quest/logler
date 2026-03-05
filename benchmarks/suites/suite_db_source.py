"""DB source benchmark suite — scenarios 17-19. Proves streaming DB ingestion."""

from __future__ import annotations

import os
import resource
import tempfile
from pathlib import Path

from benchmarks.core.base import BenchmarkResult
from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.timer import PrecisionTimer
from benchmarks.generators.database import DatabaseGenerator

SUITE_NAME = "db_source"

# Fixed scales — ignores config.scale for cross-run comparability.
DB_TIMING_SCALES = (1_000, 10_000, 50_000)
DB_MEMORY_SCALES = (10_000, 50_000, 100_000)


def _get_rss_kb() -> int:
    """Current RSS in KB (Linux: ru_maxrss is already KB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


class DbToJsonlScaling:
    """Scenario 17: db_to_jsonl throughput at 1K/10K/50K rows.

    Measures the streaming conversion pipeline: SQLite -> fetchmany -> JSONL.
    Cleans up temp JSONL files after each timing batch via path_holder pattern.
    """

    name = "db_to_jsonl_scaling"
    suite = SUITE_NAME
    description = "db_to_jsonl streaming throughput at 1K/10K/50K rows"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = DatabaseGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_db_")
        self.db_paths: dict[int, str] = {}

        for size in DB_TIMING_SCALES:
            rows = self.gen.generate(size)
            db_path = Path(self.tmpdir) / f"qler_{size}.db"
            self.gen.write_db(db_path, rows)
            self.db_paths[size] = str(db_path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.db_source import db_to_jsonl

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in DB_TIMING_SCALES:
            db_path = self.db_paths[size]

            def do_convert(p=db_path):
                jsonl_path = db_to_jsonl(p)
                # Cleanup temp file (unlink is ~microseconds, negligible vs conversion)
                os.unlink(jsonl_path)
                return jsonl_path

            stats = timer.measure(do_convert)
            throughput = size / (stats.median_ms / 1000) if stats.median_ms > 0 else 0

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="rows",
                    value=size,
                    timing=stats,
                    rows=size,
                    throughput=round(throughput, 1),
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class DbSourceSearch:
    """Scenario 18: end-to-end DB search at 1K/10K/50K rows.

    Full pipeline: db_to_jsonl -> Rust parse -> two-phase search.
    search_db is one-shot (creates/disposes Investigator), ideal for repeated timing.
    """

    name = "db_source_search"
    suite = SUITE_NAME
    description = "End-to-end DB search (db_to_jsonl + Rust) at 1K/10K/50K rows"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = DatabaseGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_dbsearch_")
        self.db_paths: dict[int, str] = {}

        for size in DB_TIMING_SCALES:
            rows = self.gen.generate(size)
            db_path = Path(self.tmpdir) / f"qler_{size}.db"
            self.gen.write_db(db_path, rows)
            self.db_paths[size] = str(db_path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import search_db

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in DB_TIMING_SCALES:
            db_path = self.db_paths[size]

            def do_search(p=db_path):
                return search_db(p, level="ERROR")

            stats = timer.measure(do_search)
            throughput = size / (stats.median_ms / 1000) if stats.median_ms > 0 else 0

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="rows",
                    value=size,
                    timing=stats,
                    rows=size,
                    throughput=round(throughput, 1),
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class DbSourceMemory:
    """Scenario 19: RSS memory profile for db_to_jsonl streaming.

    Proves streaming fetchmany keeps memory flat regardless of table size.
    Uses timer.measure_once() — RSS is a high-water mark.
    """

    name = "db_source_memory"
    suite = SUITE_NAME
    description = "RSS memory profile for db_to_jsonl at 10K/50K/100K rows"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = DatabaseGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_dbmem_")
        self.db_paths: dict[int, str] = {}

        for size in DB_MEMORY_SCALES:
            rows = self.gen.generate(size)
            db_path = Path(self.tmpdir) / f"qler_{size}.db"
            self.gen.write_db(db_path, rows)
            self.db_paths[size] = str(db_path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.db_source import db_to_jsonl

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in DB_MEMORY_SCALES:
            db_path = self.db_paths[size]
            rss_before = _get_rss_kb()

            path_holder = [None]

            def do_convert(p=db_path):
                jsonl_path = db_to_jsonl(p)
                path_holder[0] = jsonl_path
                return jsonl_path

            stats = timer.measure_once(do_convert)
            rss_after = _get_rss_kb()

            # Cleanup temp JSONL
            if path_holder[0] and os.path.exists(path_holder[0]):
                os.unlink(path_holder[0])

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="rows",
                    value=size,
                    timing=stats,
                    rows=size,
                    metadata={
                        "peak_rss_kb": rss_after,
                        "allocated_rss_kb": rss_after - rss_before,
                        "rss_before_kb": rss_before,
                    },
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


SUITE = [DbToJsonlScaling(), DbSourceSearch(), DbSourceMemory()]
