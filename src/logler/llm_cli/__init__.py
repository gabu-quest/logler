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
from ._core import (
    llm,
    EXIT_SUCCESS,
    EXIT_NO_RESULTS,
    EXIT_USER_ERROR,
    EXIT_INTERNAL_ERROR,
    _output_json,
    _error_json,
    _expand_globs,
    _apply_max_bytes,
    _parse_time_arg,
    _resolve_time_filters,
    time_filter_options,
)

# Import submodules to register their commands on the `llm` Click group.
# Each submodule uses `from ._core import llm` and decorates functions
# with `@llm.command()` or `@llm.group()`.
from . import _search  # noqa: F401 — search, schema, ids, sample, triage, summarize, sql
from . import _trace  # noqa: F401 — correlate, hierarchy, bottleneck, context, export
from . import _compare  # noqa: F401 — compare, diff
from . import _session  # noqa: F401 — session group (create, list, query, note, conclude)
from . import _format  # noqa: F401 — format group (list, test, validate)
from . import _correlation  # noqa: F401 — correlation group (list, run), correlate-events
from . import _metrics  # noqa: F401 — verify-pattern, emit, metrics, detect, templates

__all__ = [
    "llm",
    "EXIT_SUCCESS",
    "EXIT_NO_RESULTS",
    "EXIT_USER_ERROR",
    "EXIT_INTERNAL_ERROR",
    "_output_json",
    "_error_json",
    "_expand_globs",
    "_apply_max_bytes",
    "_parse_time_arg",
    "_resolve_time_filters",
    "time_filter_options",
]
