"""The one loader: files go into an investigator here, each read with its own format.

Imports ``config`` and nothing from ``_search_core`` (see CLAUDE.md, "Module Split
Architecture"), so ``_search_core`` and ``cache`` can both load through it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .config import format_for_file


def load_files(
    inv: Any,
    files: Iterable[Any],
    parser_format: str | None = None,
    custom_regex: str | None = None,
) -> None:
    """Load ``files`` into ``inv``.

    A ``parser_format`` or ``custom_regex`` given by the caller applies to every file, and an
    error from the engine (``ValueError`` for a regex or format it cannot use) propagates.
    Otherwise each file is read with ``format_for_file(file)``: files that share a regex and a
    ``timestamp_format`` load together with both, the rest with the built-in detection.
    """
    paths: list[str] = [str(f) for f in files]
    if parser_format or custom_regex:
        inv.load_files_with_config(paths, parser_format, custom_regex)
        return

    # Grouped by what the parser is given: one regex with two timestamp formats is two parsers.
    by_parser: dict[tuple[str, str | None], list[str]] = {}
    rest: list[str] = []
    for path in paths:
        fmt = format_for_file(path)
        if fmt is None:
            rest.append(path)
        else:
            by_parser.setdefault((fmt.regex, fmt.timestamp_format), []).append(path)
    for (regex, timestamp_format), group in by_parser.items():
        inv.load_files_with_config(group, None, regex, timestamp_format)
    if rest:
        inv.load_files(rest)
