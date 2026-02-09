"""Hierarchy benchmark suite — scenarios 5-7."""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.core.base import BenchmarkResult
from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.timer import PrecisionTimer
from benchmarks.generators.logs import LogGenerator

SUITE_NAME = "hierarchy"


class HierarchyBuilding:
    """Scenario 5: follow_thread_hierarchy() at scaling sizes."""

    name = "hierarchy_building"
    suite = SUITE_NAME
    description = "follow_thread_hierarchy() at scaling entry counts (with spans)"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_hier_")
        self.files: dict[int, str] = {}
        self.thread_ids: dict[int, str] = {}

        for size in config.scale.entry_counts:
            entries = self.gen.generate(
                size,
                num_threads=config.scale.thread_count,
                with_spans=True,
                error_rate=0.1,
            )
            path = Path(self.tmpdir) / f"log_{size}.jsonl"
            self.gen.write_file(path, entries)
            self.files[size] = str(path)
            # Pick a thread that exists
            self.thread_ids[size] = entries[0]["thread_id"]

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import follow_thread_hierarchy

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for size in config.scale.entry_counts:
            filepath = self.files[size]
            tid = self.thread_ids[size]

            def do_hierarchy(f=filepath, t=tid):
                return follow_thread_hierarchy(
                    files=[f],
                    root_identifier=t,
                    use_naming_patterns=True,
                    use_temporal_inference=True,
                )

            stats = timer.measure(do_hierarchy)

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


class ErrorFlowAnalysis:
    """Scenario 6: analyze_error_flow() at different tree sizes."""

    name = "error_flow_analysis"
    suite = SUITE_NAME
    description = "analyze_error_flow() at small/medium/large hierarchy sizes"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_errflow_")
        self.hierarchies: dict[str, dict] = {}

        from logler.investigate import follow_thread_hierarchy

        sizes = {"small": 1_000, "medium": 5_000, "large": 10_000}
        for label, size in sizes.items():
            entries = self.gen.generate(
                size,
                num_threads=10,
                with_spans=True,
                error_rate=0.15,
            )
            path = Path(self.tmpdir) / f"log_{label}.jsonl"
            self.gen.write_file(path, entries)
            tid = entries[0]["thread_id"]
            hierarchy = follow_thread_hierarchy(
                files=[str(path)],
                root_identifier=tid,
                use_naming_patterns=True,
                use_temporal_inference=True,
            )
            self.hierarchies[label] = hierarchy

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import analyze_error_flow

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for label, hierarchy in self.hierarchies.items():

            def do_analysis(h=hierarchy):
                return analyze_error_flow(h)

            stats = timer.measure(do_analysis)

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="size",
                    value=label,
                    timing=stats,
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class TreeFormatting:
    """Scenario 7: get_hierarchy_summary() + format_tree()."""

    name = "tree_formatting"
    suite = SUITE_NAME
    description = "get_hierarchy_summary() and format_tree() on hierarchy results"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_tree_")

        from logler.investigate import follow_thread_hierarchy

        size = config.scale.entry_counts[-1]
        entries = self.gen.generate(
            size,
            num_threads=config.scale.thread_count,
            with_spans=True,
        )
        path = Path(self.tmpdir) / "log.jsonl"
        self.gen.write_file(path, entries)
        tid = entries[0]["thread_id"]
        self.hierarchy = follow_thread_hierarchy(
            files=[str(path)],
            root_identifier=tid,
            use_naming_patterns=True,
            use_temporal_inference=True,
        )

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import get_hierarchy_summary
        from logler.tree_formatter import format_tree

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        # Summary
        def do_summary():
            return get_hierarchy_summary(self.hierarchy)

        stats = timer.measure(do_summary)
        results.append(
            BenchmarkResult(
                scenario=self.name,
                suite=self.suite,
                parameter="operation",
                value="summary",
                timing=stats,
            )
        )

        # format_tree
        def do_tree():
            return format_tree(self.hierarchy, mode="compact")

        stats = timer.measure(do_tree)
        results.append(
            BenchmarkResult(
                scenario=self.name,
                suite=self.suite,
                parameter="operation",
                value="format_tree",
                timing=stats,
            )
        )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


SUITE = [HierarchyBuilding(), ErrorFlowAnalysis(), TreeFormatting()]
