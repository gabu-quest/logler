"""
Smart sampling strategies for log entries.

Public API surface is re-exported by :mod:`logler.investigate`.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from collections import defaultdict

from ._search_core import search


def smart_sample(
    files: List[str],
    level: Optional[str] = None,
    strategy: str = "representative",
    sample_size: int = 50,
) -> Dict[str, Any]:
    """Get a smart sample of log entries that represents the full dataset.

    Instead of random sampling, this uses intelligent strategies to ensure
    the sample is informative and diverse.

    Args:
        files: Log file paths to sample.
        level: Optional log level filter.
        strategy: Sampling strategy — ``"representative"`` (balanced mix),
            ``"diverse"`` (maximum diversity), ``"chronological"`` (evenly
            spaced across time), ``"errors_focused"`` (prioritise errors
            with context).
        sample_size: Target number of entries (default 50).

    Returns:
        SampleResult dict with shape::

            {
                "samples": [...],
                "total_population": int,
                "sample_size": int,
                "strategy": str,
                "coverage": {"time_coverage": float, "level_coverage": {...}, ...}
            }

    Example::

        >>> sample = smart_sample(["app.log"], strategy="representative", sample_size=100)
        >>> for entry in sample["samples"]:
        ...     print(entry["message"])
    """
    from ._search_core import RUST_AVAILABLE

    if not RUST_AVAILABLE:
        raise RuntimeError("Rust backend not available")

    # Cap fetch size to avoid deserializing tens of thousands of entries.
    # Rust returns total_matches (true count) even with a limit, so we get
    # the real population size without a separate count query.
    fetch_limit = max(sample_size * 10, 500)

    if strategy == "errors_focused":
        error_budget = int(sample_size * 0.7)
        context_budget = sample_size - error_budget

        errors_result = search(files, level="ERROR,FATAL", limit=max(error_budget * 10, 500))
        error_entries = [r["entry"] for r in errors_result.get("results", [])]

        context_result = search(
            files,
            level=level,
            exclude_level="ERROR,FATAL",
            limit=max(context_budget * 10, 500),
        )
        context_entries = [r["entry"] for r in context_result.get("results", [])]

        all_entries = error_entries + context_entries
        total_population = errors_result.get("total_matches", 0) + context_result.get(
            "total_matches", 0
        )
        samples = _sample_errors_focused(all_entries, sample_size)
    else:
        results = search(files, level=level, limit=fetch_limit)
        all_entries = [r["entry"] for r in results.get("results", [])]
        total_population = results.get("total_matches", len(all_entries))

        if strategy == "representative":
            samples = _sample_representative(all_entries, sample_size)
        elif strategy == "diverse":
            samples = _sample_diverse(all_entries, sample_size)
        elif strategy == "chronological":
            samples = _sample_chronological(all_entries, sample_size)
        else:
            samples = _sample_representative(all_entries, sample_size)

    if total_population == 0:
        return {
            "samples": [],
            "total_population": 0,
            "sample_size": 0,
            "strategy": strategy,
            "coverage": {},
        }

    coverage = _calculate_coverage(all_entries, samples)

    return {
        "samples": samples,
        "total_population": total_population,
        "sample_size": len(samples),
        "strategy": strategy,
        "coverage": coverage,
    }


# ---------------------------------------------------------------------------
# Sampling strategies
# ---------------------------------------------------------------------------


def _sample_representative(entries: List[Dict], size: int) -> List[Dict]:
    """Sample to represent overall distribution."""
    if len(entries) <= size:
        return entries

    samples = []

    # Group by level
    by_level = defaultdict(list)
    for entry in entries:
        level = entry.get("level", "INFO")
        by_level[level].append(entry)

    # Calculate proportional samples per level
    for level, level_entries in by_level.items():
        proportion = len(level_entries) / len(entries)
        level_sample_size = max(1, int(size * proportion))

        # Sample evenly across time
        if level_sample_size >= len(level_entries):
            samples.extend(level_entries)
        else:
            step = len(level_entries) / level_sample_size
            indices = [int(i * step) for i in range(level_sample_size)]
            samples.extend([level_entries[i] for i in indices])

    # If we have too many, trim to size
    if len(samples) > size:
        step = len(samples) / size
        indices = [int(i * step) for i in range(size)]
        samples = [samples[i] for i in indices]

    return samples[:size]


def _sample_diverse(entries: List[Dict], size: int) -> List[Dict]:
    """Sample for maximum diversity."""
    if len(entries) <= size:
        return entries

    samples = []
    used_messages = set()
    used_threads = set()

    # First pass: unique messages
    for entry in entries:
        if len(samples) >= size:
            break

        message = entry.get("message", "")
        if message and message not in used_messages:
            samples.append(entry)
            used_messages.add(message)
            thread = entry.get("thread_id") or entry.get("correlation_id")
            if thread:
                used_threads.add(thread)

    # Second pass: unique threads
    if len(samples) < size:
        for entry in entries:
            if len(samples) >= size:
                break

            thread = entry.get("thread_id") or entry.get("correlation_id")
            if thread and thread not in used_threads:
                samples.append(entry)
                used_threads.add(thread)

    # Third pass: fill remaining with evenly spaced entries
    if len(samples) < size:
        remaining = size - len(samples)
        step = len(entries) / remaining
        for i in range(remaining):
            idx = int(i * step)
            if idx < len(entries):
                samples.append(entries[idx])

    return samples[:size]


def _sample_chronological(entries: List[Dict], size: int) -> List[Dict]:
    """Sample evenly across time."""
    if len(entries) <= size:
        return entries

    # Sort by timestamp
    sorted_entries = sorted(entries, key=lambda e: e.get("timestamp", ""))

    # Sample evenly
    step = len(sorted_entries) / size
    indices = [int(i * step) for i in range(size)]
    return [sorted_entries[i] for i in indices]


def _sample_errors_focused(entries: List[Dict], size: int) -> List[Dict]:
    """Sample focusing on errors with context."""
    if len(entries) <= size:
        return entries

    samples = []
    error_indices = []
    non_error_indices = []

    # Separate errors from non-errors
    for i, entry in enumerate(entries):
        level = entry.get("level", "INFO")
        if level in ["ERROR", "FATAL"]:
            error_indices.append(i)
        else:
            non_error_indices.append(i)

    # Allocate 70% to errors, 30% to context
    error_budget = int(size * 0.7)

    # Sample errors
    if error_indices:
        if len(error_indices) <= error_budget:
            # All errors + some context
            for idx in error_indices:
                samples.append(entries[idx])
                # Add 1-2 entries before error for context
                if idx > 0:
                    samples.append(entries[idx - 1])
        else:
            # Sample errors evenly
            step = len(error_indices) / error_budget
            for i in range(error_budget):
                idx = error_indices[int(i * step)]
                samples.append(entries[idx])

    # Sample non-errors for context
    if non_error_indices and len(samples) < size:
        remaining = size - len(samples)
        step = len(non_error_indices) / remaining
        for i in range(remaining):
            idx = non_error_indices[min(int(i * step), len(non_error_indices) - 1)]
            samples.append(entries[idx])

    # Sort by original order
    entry_to_index = {id(e): i for i, e in enumerate(entries)}
    samples.sort(key=lambda e: entry_to_index.get(id(e), 0))

    return samples[:size]


# ---------------------------------------------------------------------------
# Coverage calculation
# ---------------------------------------------------------------------------


def _calculate_coverage(population: List[Dict], sample: List[Dict]) -> Dict[str, Any]:
    """Calculate how well the sample covers the population."""
    # Time coverage
    pop_times = [e.get("timestamp") for e in population if e.get("timestamp")]
    sample_times = [e.get("timestamp") for e in sample if e.get("timestamp")]

    time_coverage = 0.0
    if pop_times and sample_times:
        pop_times.sort()
        sample_times.sort()
        # Simple coverage: sample span / population span
        try:
            pop_start = datetime.fromisoformat(pop_times[0].replace("Z", "+00:00"))
            pop_end = datetime.fromisoformat(pop_times[-1].replace("Z", "+00:00"))
            sample_start = datetime.fromisoformat(sample_times[0].replace("Z", "+00:00"))
            sample_end = datetime.fromisoformat(sample_times[-1].replace("Z", "+00:00"))

            pop_duration = (pop_end - pop_start).total_seconds()
            sample_duration = (sample_end - sample_start).total_seconds()

            if pop_duration > 0:
                time_coverage = min(1.0, sample_duration / pop_duration)
        except (ValueError, TypeError, AttributeError):
            pass  # Skip if timestamps are invalid

    # Level coverage
    level_coverage = defaultdict(int)
    for entry in sample:
        level = entry.get("level", "INFO")
        level_coverage[level] += 1

    # Thread coverage
    pop_threads = set()
    sample_threads = set()
    for entry in population:
        thread = entry.get("thread_id") or entry.get("correlation_id")
        if thread:
            pop_threads.add(thread)
    for entry in sample:
        thread = entry.get("thread_id") or entry.get("correlation_id")
        if thread:
            sample_threads.add(thread)

    thread_coverage_pct = len(sample_threads) / len(pop_threads) if pop_threads else 0

    return {
        "time_coverage": time_coverage,
        "level_coverage": dict(level_coverage),
        "unique_threads_in_sample": len(sample_threads),
        "unique_threads_in_population": len(pop_threads),
        "thread_coverage_pct": thread_coverage_pct,
    }
