"""Output benchmark suite — scenarios 11-12. Grounds the "Nx token savings" claim."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from benchmarks.core.base import BenchmarkResult
from benchmarks.core.config import BenchmarkConfig
from benchmarks.core.timer import PrecisionTimer
from benchmarks.generators.logs import LogGenerator

SUITE_NAME = "output"


class OutputFormatComparison:
    """Scenario 11: full/summary/count/compact — time + bytes.

    This is the scenario that grounds the "Nx token savings" claim.
    Measures actual response size in bytes for each output format.
    """

    name = "output_format_comparison"
    suite = SUITE_NAME
    description = "Output format comparison: full/summary/count/compact — time + response bytes"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_output_")
        size = config.scale.entry_counts[-1]
        entries = self.gen.generate(size, error_rate=0.1)
        self.filepath = str(Path(self.tmpdir) / "log.jsonl")
        self.gen.write_file(self.filepath, entries)
        self.size = size

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        from logler.investigate import search

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)
        response_sizes: dict[str, int] = {}

        for fmt in ("full", "summary", "count", "compact"):
            response_holder = [None]

            def do_search(f=fmt):
                r = search(
                    files=[self.filepath],
                    level="ERROR",
                    limit=100,
                    output_format=f,
                )
                response_holder[0] = r
                return r

            stats = timer.measure(do_search)
            response_bytes = len(json.dumps(response_holder[0]).encode())
            response_sizes[fmt] = response_bytes

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

        # Calculate savings ratios against full
        full_bytes = response_sizes.get("full", 1)
        for r in results:
            fmt = r.value
            if fmt != "full" and full_bytes > 0:
                ratio = full_bytes / max(1, response_sizes.get(fmt, 1))
                r.metadata["savings_vs_full"] = round(ratio, 1)

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class MaxBytesTruncation:
    """Scenario 12: --max-bytes budget accuracy."""

    name = "max_bytes_truncation"
    suite = SUITE_NAME
    description = "Max-bytes budget accuracy at 1KB/4KB/16KB limits"

    def setup(self, config: BenchmarkConfig) -> None:
        self.gen = LogGenerator(seed=42)
        self.tmpdir = tempfile.mkdtemp(prefix="bench_maxbytes_")
        size = config.scale.entry_counts[-1]
        entries = self.gen.generate(size, error_rate=0.1)
        self.filepath = str(Path(self.tmpdir) / "log.jsonl")
        self.gen.write_file(self.filepath, entries)
        self.size = size

    def run(self, config: BenchmarkConfig) -> list[BenchmarkResult]:
        import subprocess
        import sys

        results = []
        timer = PrecisionTimer(warmup=config.warmup, iterations=config.iterations)

        for budget in (1024, 4096, 16384):
            response_holder = [0]

            def do_search(b=budget):
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "logler.cli",
                        "llm",
                        "search",
                        self.filepath,
                        "--level",
                        "ERROR",
                        "--max-bytes",
                        str(b),
                    ],
                    capture_output=True,
                    text=True,
                )
                response_holder[0] = len(proc.stdout.encode())
                return proc

            stats = timer.measure(do_search)
            actual_bytes = response_holder[0]

            results.append(
                BenchmarkResult(
                    scenario=self.name,
                    suite=self.suite,
                    parameter="budget_bytes",
                    value=f"{budget // 1024}KB",
                    timing=stats,
                    metadata={
                        "budget_bytes": budget,
                        "actual_bytes": actual_bytes,
                        "within_budget": actual_bytes <= budget,
                    },
                )
            )

        return results

    def teardown(self) -> None:
        import shutil

        if hasattr(self, "tmpdir"):
            shutil.rmtree(self.tmpdir, ignore_errors=True)


SUITE = [OutputFormatComparison(), MaxBytesTruncation()]
