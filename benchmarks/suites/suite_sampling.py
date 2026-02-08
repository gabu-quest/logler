"""Sampling benchmark suite — scenarios 13-14."""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.core.base import BenchmarkResult
from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.timer import PrecisionTimer
from benchmarks.generators.logs import LogGenerator

SUITE_NAME = "sampling"


class SamplingStrategies:
    """Scenario 13: errors_focused/diverse/chronological comparison."""

    name = "sampling_strategies"
    suite = SUITE_NAME
    description = "Smart sampling strategies: errors_focused/diverse/chronological"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_sample_")
        size = config.scale.entry_counts[-1]
        entries = self.gen.generate(size, error_rate=0.1)
        self.filepath = str(Path(self.tmpdir) / "log.jsonl")
        self.gen.write_file(self.filepath, entries)
        self.size = size

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import smart_sample

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for strategy in ("errors_focused", "diverse", "chronological"):

            def do_sample(s=strategy):
                return smart_sample(
                    files=[self.filepath],
                    strategy=s,
                    sample_size=50,
                )

            stats = timer.measure(do_sample)

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="strategy",
                    value=strategy,
                    timing=stats,
                    rows=self.size,
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class SamplingScaling:
    """Scenario 14: smart_sample() at scaling entry counts."""

    name = "sampling_scaling"
    suite = SUITE_NAME
    description = "smart_sample() throughput at scaling entry counts"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_sscale_")
        self.files: dict[int, str] = {}

        for size in config.scale.entry_counts:
            entries = self.gen.generate(size, error_rate=0.1)
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import smart_sample

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in config.scale.entry_counts:
            filepath = self.files[size]

            def do_sample(f=filepath):
                return smart_sample(
                    files=[f],
                    strategy="errors_focused",
                    sample_size=50,
                )

            stats = timer.measure(do_sample)
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


SUITE = [SamplingStrategies(), SamplingScaling()]
