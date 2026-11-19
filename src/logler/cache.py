"""
Performance optimization: File-level index caching for standalone functions.

Standalone functions like search(), extract_ids(), get_context() create a new
PyInvestigator and re-parse files every call.  This module provides a
thread-safe cache keyed on (sorted file paths) with mtime-based staleness
detection so callers get parsed indices for free on repeated queries. The formats.yaml
files that decide how each file is read are part of the staleness check.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Tuple

from ._loading import load_files
from .config import formats_stamp

# Thread-safe cache for Investigator instances
_investigator_lock = threading.Lock()

# Cache entry: (investigator, {path: mtime}, formats stamp)
_CacheEntry = Tuple[Any, Dict[str, float], tuple]  # Any = logler_rs.PyInvestigator
_investigator_cache: Dict[tuple, _CacheEntry] = {}
_cache_max_size = 10  # Keep up to 10 file sets in cache


def _collect_mtimes(files: tuple) -> Dict[str, float]:
    """Snapshot mtime for each file (0.0 if stat fails)."""
    mtimes: Dict[str, float] = {}
    for f in files:
        try:
            mtimes[f] = os.path.getmtime(f)
        except OSError:
            mtimes[f] = 0.0
    return mtimes


def _collect_format_stamps(files: tuple) -> tuple:
    """The formats.yaml (path, mtime, size) behind each file's directory, or None.

    Files in one directory share a stamp, except a link: its format is found from the
    directory of the file it points to, so it gets a stamp of its own.
    """
    stamps: Dict[str, Any] = {}
    for f in files:
        key = f if os.path.islink(f) else os.path.dirname(f)
        if key not in stamps:
            stamps[key] = formats_stamp(f)
    return tuple(sorted(stamps.items(), key=lambda item: item[0]))


def _mtimes_fresh(cached: Dict[str, float], current: Dict[str, float]) -> bool:
    """Return True if every file's mtime matches the cached snapshot."""
    if cached.keys() != current.keys():
        return False
    return all(cached[k] == current[k] for k in cached)


def _get_cached_investigator(files: tuple) -> Any:
    """Get or create a cached Investigator for the given (sorted) file tuple."""
    with _investigator_lock:
        current_mtimes = _collect_mtimes(files)
        current_stamps = _collect_format_stamps(files)

        if files in _investigator_cache:
            inv, cached_mtimes, cached_stamps = _investigator_cache[files]
            if cached_stamps == current_stamps and _mtimes_fresh(cached_mtimes, current_mtimes):
                return inv
            # Stale — fall through to re-create
            del _investigator_cache[files]

        # Lazy import to avoid module-level dependency on logler_rs
        import logler_rs

        inv = logler_rs.PyInvestigator()
        load_files(inv, files)

        # Evict oldest entry if at capacity
        if len(_investigator_cache) >= _cache_max_size:
            oldest = next(iter(_investigator_cache))
            del _investigator_cache[oldest]

        _investigator_cache[files] = (inv, current_mtimes, current_stamps)
        return inv


def get_cached_investigator(files) -> Any:
    """Public accessor — normalizes file list into a stable cache key."""
    key = tuple(sorted(str(f) for f in files))
    return _get_cached_investigator(key)


def clear_cache():
    """Clear the investigator cache (useful for testing or freeing memory)."""
    with _investigator_lock:
        _investigator_cache.clear()
