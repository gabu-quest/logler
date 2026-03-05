"""Memory benchmark suite — scenarios 15-16. Proves two-phase search bounds memory."""

from __future__ import annotations

import resource
import tempfile
from pathlib import Path

from benchmarks.core.base import BenchmarkResult
from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.timer import PrecisionTimer
from benchmarks.generators.logs import LogGenerator

SUITE_NAME = "memory"

# Fixed scales for cross-run comparability — ignores config.scale intentionally.
MEMORY_SCALES = (10_000, 50_000, 100_000)


def _get_rss_kb() -> int:
    """Current RSS in KB (Linux: ru_maxrss is already KB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


class SearchBroadQuery:
    """Scenario 15: broad query (level=INFO, ~60% of corpus) throughput.

    INFO represents ~60% of entries (vs ERROR=10% in existing search_scaling).
    This proves that broad queries don't regress under two-phase search.
    Uses timer.measure() — this is a speed scenario.
    """

    name = "search_broad_query"
    suite = SUITE_NAME
    description = "Broad query throughput (level=INFO ~60%) at 10K/50K/100K entries"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_memory_")
        self.files: dict[int, str] = {}

        for size in MEMORY_SCALES:
            entries = self.gen.generate(size, error_rate=0.1)
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import search

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in MEMORY_SCALES:
            filepath = self.files[size]

            def do_search(f=filepath):
                return search(files=[f], level="INFO", limit=100)

            stats = timer.measure(do_search)
            throughput = size / (stats.median_ms / 1000) if stats.median_ms > 0 else 0

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="entries",
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


class SearchMemoryProfile:
    """Scenario 16: RSS memory profile for broad queries.

    Same broad query as scenario 15, but captures RSS before/after.
    Uses timer.measure_once() — RSS is a high-water mark, repeated calls inflate it.
    The money shot: allocated_rss_kb should grow sub-linearly across 10K->100K.
    """

    name = "search_memory_profile"
    suite = SUITE_NAME
    description = "RSS memory profile for broad queries at 10K/50K/100K entries"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_memprof_")
        self.files: dict[int, str] = {}

        for size in MEMORY_SCALES:
            entries = self.gen.generate(size, error_rate=0.1)
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import search

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in MEMORY_SCALES:
            filepath = self.files[size]
            rss_before = _get_rss_kb()

            def do_search(f=filepath):
                return search(files=[f], level="INFO", limit=100)

            stats = timer.measure_once(do_search)
            rss_after = _get_rss_kb()

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="entries",
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


SUITE = [SearchBroadQuery(), SearchMemoryProfile()]
