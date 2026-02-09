"""Search benchmark suite — scenarios 1-4."""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.core.base import BenchmarkResult
from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.timer import PrecisionTimer
from benchmarks.generators.logs import LogGenerator

SUITE_NAME = "search"


class SearchScaling:
    """Scenario 1: search() throughput at increasing entry counts."""

    name = "search_scaling"
    suite = SUITE_NAME
    description = "search() throughput at 1K -> max entries, level=ERROR"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_search_")
        self.files: dict[int, str] = {}

        for size in config.scale.entry_counts:
            entries = self.gen.generate(size, error_rate=0.1)
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import search

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in config.scale.entry_counts:
            filepath = self.files[size]

            def do_search(f=filepath):
                return search(files=[f], level="ERROR", limit=100)

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


class SearchByLevel:
    """Scenario 2: Level filter comparison at fixed size."""

    name = "search_by_level"
    suite = SUITE_NAME
    description = "Level filter (ERROR/WARN/INFO) at fixed entry count"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_level_")
        size = config.scale.entry_counts[-1]  # largest
        entries = self.gen.generate(size, error_rate=0.1)
        self.filepath = str(Path(self.tmpdir) / "log.jsonl")
        self.gen.write_file(self.filepath, entries)
        self.size = size

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import search

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for level in ("ERROR", "WARN", "INFO"):

            def do_search(lv=level):
                return search(files=[self.filepath], level=lv, limit=100)

            stats = timer.measure(do_search)
            throughput = self.size / (stats.median_ms / 1000) if stats.median_ms > 0 else 0

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="level",
                    value=level,
                    timing=stats,
                    rows=self.size,
                    throughput=round(throughput, 1),
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class SearchOutputFormats:
    """Scenario 3: full vs summary vs count — time + response size."""

    name = "search_output_formats"
    suite = SUITE_NAME
    description = "Output format impact: full/summary/count/compact"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_fmt_")
        size = config.scale.entry_counts[-1]
        entries = self.gen.generate(size, error_rate=0.1)
        self.filepath = str(Path(self.tmpdir) / "log.jsonl")
        self.gen.write_file(self.filepath, entries)
        self.size = size

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        import json
        from logler.investigate import search

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for fmt in ("full", "summary", "count", "compact"):
            response_holder = [None]

            def do_search(f=fmt):
                r = search(files=[self.filepath], level="ERROR", limit=100, output_format=f)
                response_holder[0] = r
                return r

            stats = timer.measure(do_search)
            response_bytes = len(json.dumps(response_holder[0]).encode())

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="format",
                    value=fmt,
                    timing=stats,
                    rows=self.size,
                    metadata={"response_bytes": response_bytes},
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class SearchWithFilters:
    """Scenario 4: Combined level+query+time_range filters, scaling."""

    name = "search_with_filters"
    suite = SUITE_NAME
    description = "Combined level+query filters at scaling entry counts"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_filter_")
        self.files: dict[int, str] = {}

        for size in config.scale.entry_counts:
            entries = self.gen.generate(size, error_rate=0.1)
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import search

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in config.scale.entry_counts:
            filepath = self.files[size]

            def do_search(f=filepath):
                return search(
                    files=[f],
                    level="ERROR",
                    query="timeout",
                    limit=50,
                )

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


SUITE = [SearchScaling(), SearchByLevel(), SearchOutputFormats(), SearchWithFilters()]
