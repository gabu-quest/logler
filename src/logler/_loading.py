"""The one loader: files go into an investigator here, each read with its own format.

Imports ``config`` and nothing from ``_search_core`` (see CLAUDE.md, "Module Split
Architecture"), so ``_search_core`` and ``cache`` can both load through it.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .config import format_for_file


def load_files(
    inv: Any,
    files: Iterable[Any],
    parser_format: Optional[str] = None,
    custom_regex: Optional[str] = None,
) -> None:
    """Load ``files`` into ``inv``.

    A ``parser_format`` or ``custom_regex`` given by the caller applies to every file, and an
    error from the engine (``ValueError`` for a regex or format it cannot use) propagates.
    Otherwise each file is read with ``format_for_file(file)``: files that share a format load
    together with its regex, the rest with the built-in detection.
    """
    paths: List[str] = [str(f) for f in files]
    if parser_format or custom_regex:
        inv.load_files_with_config(paths, parser_format, custom_regex)
        return

    by_regex: Dict[str, List[str]] = {}
    rest: List[str] = []
    for path in paths:
        fmt = format_for_file(path)
        if fmt is None:
            rest.append(path)
        else:
            by_regex.setdefault(fmt.regex, []).append(path)
    for regex, group in by_regex.items():
        inv.load_files_with_config(group, None, regex)
    if rest:
        inv.load_files(rest)
