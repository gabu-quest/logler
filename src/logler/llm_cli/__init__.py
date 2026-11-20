"""
LLM-First CLI Package - Commands optimized for AI agents.

Design principles:
- JSON output by default (no --json flag needed)
- No truncation - full data always
- Meaningful exit codes for chaining
- Rich metadata for LLM reasoning
- Deterministic output structure
"""

# Re-export public API from _core (backwards compatibility)
# Import submodules to register their commands on the `llm` Click group.
# Each submodule decorates its functions with `@command()` (from _core)
# or registers a group with `@llm.group()`.
from . import (
    _compare,  # noqa: F401 — compare, diff
    _correlation,  # noqa: F401 — correlation group (list, run), correlate-events
    _format,  # noqa: F401 — format group (list, test, validate)
    _metrics,  # noqa: F401 — verify-pattern, emit, metrics, detect, templates
    _search,  # noqa: F401 — search, schema, ids, sample, triage, summarize, sql
    _session,  # noqa: F401 — session group (create, list, query, note, conclude)
    _trace,  # noqa: F401 — correlate, hierarchy, bottleneck, context, export
)
from ._core import (
    EXIT_INTERNAL_ERROR,
    EXIT_NO_RESULTS,
    EXIT_SUCCESS,
    EXIT_USER_ERROR,
    _apply_max_bytes,
    _error_json,
    _expand_globs,
    _output_json,
    _parse_time_arg,
    _resolve_time_filters,
    llm,
    time_filter_options,
)

__all__ = [
    "EXIT_INTERNAL_ERROR",
    "EXIT_NO_RESULTS",
    "EXIT_SUCCESS",
    "EXIT_USER_ERROR",
    "_apply_max_bytes",
    "_error_json",
    "_expand_globs",
    "_output_json",
    "_parse_time_arg",
    "_resolve_time_filters",
    "llm",
    "time_filter_options",
]
