"""
Performance optimization: Add file-level index caching to standalone functions.

Currently, standalone functions like search(), follow_thread() create a new
Investigator and re-read files every time. This is inefficient for repeated
queries on the same files.

Solution: Add a module-level LRU cache that reuses Investigator instances.
"""

import threading
from typing import Dict
import logler_rs

# Thread-safe cache for Investigator instances
_investigator_lock = threading.Lock()
_investigator_cache: Dict[tuple, logler_rs.PyInvestigator] = {}
_cache_max_size = 10  # Keep up to 10 file sets in cache


def _get_cached_investigator(files: tuple) -> logler_rs.PyInvestigator:
    """
    Get or create a cached Investigator for the given files.

    This allows standalone functions to reuse parsed indices when
    called multiple times with the same files.
    """
    with _investigator_lock:
        # Check cache
        if files in _investigator_cache:
            return _investigator_cache[files]

        # Create new investigator
        inv = logler_rs.PyInvestigator()
        inv.load_files(list(files))

        # Add to cache (with simple size limit)
        if len(_investigator_cache) >= _cache_max_size:
            # Remove oldest entry (simple FIFO)
            oldest = next(iter(_investigator_cache))
            del _investigator_cache[oldest]

        _investigator_cache[files] = inv
        return inv


def get_cached_investigator(files) -> logler_rs.PyInvestigator:
    """
    Public accessor that normalizes the incoming file list into a stable cache key.
    """
    key = tuple(sorted(str(f) for f in files))
    return _get_cached_investigator(key)


def clear_cache():
    """Clear the investigator cache (useful for testing or freeing memory)"""
    with _investigator_lock:
        _investigator_cache.clear()


# Example usage showing the difference:
#
# SLOW (current):
#   for i in range(100):
#       search(["app.log"], level="ERROR")  # Re-reads file 100 times!
#
# FAST (with cache):
#   for i in range(100):
#       search(["app.log"], level="ERROR")  # Reads once, caches index!
#
# FASTEST (explicit Investigator):
#   inv = Investigator()
#   inv.load_files(["app.log"])
#   for i in range(100):
#       inv.search(level="ERROR")  # Explicit control, no cache overhead
