"""Correlation benchmark suite — scenarios 8-10."""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.core.base import BenchmarkResult
from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.timer import PrecisionTimer
from benchmarks.generators.logs import LogGenerator

SUITE_NAME = "correlation"


class FollowThreadScaling:
    """Scenario 8: follow_thread() at scaling entry counts."""

    name = "follow_thread_scaling"
    suite = SUITE_NAME
    description = "follow_thread() throughput at scaling entry counts"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_follow_")
        self.files: dict[int, str] = {}
        self.correlation_ids: dict[int, str] = {}

        for size in config.scale.entry_counts:
            entries = self.gen.generate(
                size,
                num_correlations=config.scale.correlations,
            )
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)
            self.correlation_ids[size] = entries[0]["correlation_id"]

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import follow_thread

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in config.scale.entry_counts:
            filepath = self.files[size]
            cid = self.correlation_ids[size]

            def do_follow(f=filepath, c=cid):
                return follow_thread(files=[f], correlation_id=c)

            stats = timer.measure(do_follow)
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


class CrossServiceTimeline:
    """Scenario 9: cross_service_timeline() with varying service counts."""

    name = "cross_service_timeline"
    suite = SUITE_NAME
    description = "cross_service_timeline() with 2/3/5 services"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_xsvc_")
        self.service_files: dict[int, dict[str, list[str]]] = {}
        self.cid = "req-000042"

        all_services = [
            "api-gateway",
            "auth-service",
            "user-service",
            "order-service",
            "cache-service",
        ]
        entries_per = max(100, config.scale.entry_counts[0] // 5)

        for svc_count in (2, 3, 5):
            services = all_services[:svc_count]
            multi = self.gen.generate_multi_service(services, entries_per, self.cid)
            files_map: dict[str, list[str]] = {}
            for svc, entries in multi.items():
                path = Path(self.tmpdir) / f"{svc}_{svc_count}.jsonl"
                self.gen.write_file(path, entries)
                files_map[svc] = [str(path)]
            self.service_files[svc_count] = files_map

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import cross_service_timeline

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for svc_count, files_map in self.service_files.items():

            def do_timeline(fm=files_map, c=self.cid):
                return cross_service_timeline(files=fm, correlation_id=c)

            stats = timer.measure(do_timeline)

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="services",
                    value=f"{svc_count}_services",
                    timing=stats,
                    metadata={"service_count": svc_count},
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class CompareThreads:
    """Scenario 10: compare_threads() at scaling sizes."""

    name = "compare_threads"
    suite = SUITE_NAME
    description = "compare_threads() comparing two correlation IDs at scaling sizes"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_compare_")
        self.files: dict[int, str] = {}

        for size in config.scale.entry_counts:
            entries = self.gen.generate(
                size,
                num_correlations=max(20, config.scale.correlations),
            )
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import compare_threads

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in config.scale.entry_counts:
            filepath = self.files[size]

            def do_compare(f=filepath):
                return compare_threads(
                    files=[f],
                    correlation_a="req-000000",
                    correlation_b="req-000001",
                )

            stats = timer.measure(do_compare)

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="entries",
                    value=size,
                    timing=stats,
                    rows=size,
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


SUITE = [FollowThreadScaling(), CrossServiceTimeline(), CompareThreads()]
