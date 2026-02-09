"""Benchmark suites registry."""

from __future__ import annotations

from .suite_search import SUITE as SEARCH_SUITE
from .suite_hierarchy import SUITE as HIERARCHY_SUITE
from .suite_correlation import SUITE as CORRELATION_SUITE
from .suite_output import SUITE as OUTPUT_SUITE
from .suite_sampling import SUITE as SAMPLING_SUITE

ALL_SUITES: dict[str, list] = {
    "search": SEARCH_SUITE,
    "hierarchy": HIERARCHY_SUITE,
    "correlation": CORRELATION_SUITE,
    "output": OUTPUT_SUITE,
    "sampling": SAMPLING_SUITE,
}


def get_scenarios(suite_names: list[str] | None = None) -> list:
    """Get scenarios for the given suites, or all if None."""
    if suite_names is None:
        suite_names = list(ALL_SUITES.keys())
    scenarios = []
    for name in suite_names:
        if name not in ALL_SUITES:
            raise ValueError(f"Unknown suite: {name!r} (choose from {list(ALL_SUITES)})")
        scenarios.extend(ALL_SUITES[name])
    return scenarios
