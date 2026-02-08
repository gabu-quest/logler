"""Benchmark configuration and scale profiles for log investigation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ScaleConfig:
    """Controls data sizes for benchmark runs."""

    name: str
    entry_counts: tuple[int, ...]
    thread_count: int
    correlations: int

    @classmethod
    def small(cls) -> ScaleConfig:
        return cls(
            name="small",
            entry_counts=(1_000, 10_000, 50_000),
            thread_count=10,
            correlations=20,
        )

    @classmethod
    def medium(cls) -> ScaleConfig:
        return cls(
            name="medium",
            entry_counts=(10_000, 50_000, 100_000),
            thread_count=50,
            correlations=100,
        )

    @classmethod
    def large(cls) -> ScaleConfig:
        return cls(
            name="large",
            entry_counts=(50_000, 100_000, 500_000),
            thread_count=100,
            correlations=500,
        )

    @classmethod
    def from_name(cls, name: str) -> ScaleConfig:
        configs = {"small": cls.small, "medium": cls.medium, "large": cls.large}
        factory = configs.get(name)
        if factory is None:
            raise ValueError(f"Unknown scale: {name!r} (choose from {list(configs)})")
        return factory()


@dataclass(slots=True)
class BenchmarkConfig:
    """Full benchmark configuration."""

    scale: ScaleConfig = field(default_factory=ScaleConfig.small)
    warmup: int = 2
    iterations: int = 5
    output_dir: str = "benchmarks/results"
    suites: list[str] | None = None  # None = all suites
    verbose: bool = False
