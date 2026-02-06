"""
Cross-file event correlation (M3).

Given a reference event or trigger conditions, find all related events
across multiple files within a configurable time window.

This builds on the existing Rust search engine's time_range filtering
to provide ad-hoc event correlation without requiring pre-defined YAML rules.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import investigate
from .config import EventCondition, parse_duration
from .correlator import _matches_anchor, _make_virtual_trace_id, _parse_entry_timestamp


def search_around_timestamp(
    files: List[str],
    anchor_timestamp: str,
    window: str = "5s",
    **search_kwargs: Any,
) -> Dict[str, Any]:
    """Search all files for events within a time window around a timestamp.

    Uses the Rust search engine's time_range filtering for performance.

    Args:
        files: Log file paths to search.
        anchor_timestamp: ISO8601 timestamp of the reference event.
        window: Time window (e.g., "5s", "1m", "500ms").
        **search_kwargs: Extra kwargs passed to investigate.search().

    Returns:
        Search results with window metadata added.
    """
    delta = parse_duration(window)
    anchor_dt = datetime.fromisoformat(anchor_timestamp.replace("Z", "+00:00"))

    time_start = (anchor_dt - delta).isoformat()
    time_end = (anchor_dt + delta).isoformat()

    result = investigate.search(
        files=files,
        time_start=time_start,
        time_end=time_end,
        **search_kwargs,
    )

    result["anchor_timestamp"] = anchor_timestamp
    result["window"] = window
    result["time_start"] = time_start
    result["time_end"] = time_end

    return result


def find_trigger_events(
    entries: List[Dict[str, Any]],
    trigger: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Find entries matching trigger conditions.

    Args:
        entries: Log entries to scan.
        trigger: Trigger definition dict with optional keys:
            level, pattern, file_pattern, field, condition.

    Returns:
        Entries matching the trigger conditions.
    """
    # At least one condition must be specified
    has_condition = any(
        trigger.get(k) is not None for k in ("level", "pattern", "file_pattern", "field")
    )
    if not has_condition:
        return []

    condition = EventCondition.model_validate(
        {
            k: v
            for k, v in {
                "file_pattern": trigger.get("file_pattern"),
                "level": trigger.get("level"),
                "pattern": trigger.get("pattern"),
                "field": trigger.get("field"),
                "condition": trigger.get("condition"),
            }.items()
            if v is not None
        }
    )

    return [e for e in entries if _matches_anchor(e, condition)]


def correlate_events(
    files: List[str],
    anchor_entry: Optional[Dict[str, Any]] = None,
    anchor_timestamp: Optional[str] = None,
    trigger: Optional[Dict[str, Any]] = None,
    window: str = "5s",
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Cross-file event correlation.

    Finds all events across multiple files within a time window around
    reference events. Reference events can be:
    - A specific entry (anchor_entry)
    - A specific timestamp (anchor_timestamp)
    - Automatically discovered via trigger conditions (trigger)

    Args:
        files: Log file paths to search.
        anchor_entry: A specific entry dict (must have timestamp).
        anchor_timestamp: ISO8601 timestamp to correlate around.
        trigger: Trigger conditions dict (level, pattern, field, condition).
        window: Time window (e.g., "5s", "1m", "500ms").
        limit: Max clusters to return.

    Returns:
        Dict with clusters, total_clusters, total_entries_correlated,
        files_searched, window.
    """
    clusters: List[Dict[str, Any]] = []
    delta = parse_duration(window)

    if anchor_entry is not None:
        cluster = _correlate_around_entry(files, anchor_entry, delta, window)
        if cluster is not None:
            clusters.append(cluster)

    elif anchor_timestamp is not None:
        cluster = _correlate_around_timestamp(files, anchor_timestamp, delta, window)
        if cluster is not None:
            clusters.append(cluster)

    elif trigger is not None:
        clusters = _correlate_by_trigger(files, trigger, delta, window)

    else:
        return {
            "error": "Must provide anchor_entry, anchor_timestamp, or trigger",
            "clusters": [],
            "total_clusters": 0,
            "total_entries_correlated": 0,
            "files_searched": len(files),
            "window": window,
        }

    total_clusters = len(clusters)
    if limit and limit > 0:
        clusters = clusters[:limit]

    correlated_ids = set()
    for cluster in clusters:
        for entry in cluster["entries"]:
            correlated_ids.add(entry.get("id") or id(entry))

    return {
        "clusters": clusters,
        "total_clusters": total_clusters,
        "total_entries_correlated": len(correlated_ids),
        "files_searched": len(files),
        "window": window,
    }


def _correlate_around_entry(
    files: List[str],
    anchor_entry: Dict[str, Any],
    delta,
    window: str,
) -> Optional[Dict[str, Any]]:
    """Build a correlation cluster around a specific entry."""
    anchor_ts = _parse_entry_timestamp(anchor_entry)
    if anchor_ts is None:
        return None

    anchor_msg = (anchor_entry.get("message") or anchor_entry.get("raw") or "")[:120]

    result = investigate.search(
        files=files,
        time_start=(anchor_ts - delta).isoformat(),
        time_end=(anchor_ts + delta).isoformat(),
    )

    entries = [item.get("entry", item) for item in result.get("results", [])]
    if not entries:
        return None

    vtid = _make_virtual_trace_id("event-correlation", 0, f"{anchor_ts.isoformat()}:{anchor_msg}")

    return {
        "virtual_trace_id": vtid,
        "rule_type": "event_window",
        "anchor_timestamp": anchor_ts.isoformat(),
        "anchor_message": anchor_msg,
        "anchor_file": Path(anchor_entry.get("file", "")).name,
        "anchor_line": anchor_entry.get("line_number"),
        "window": window,
        "entry_count": len(entries),
        "entries": entries,
    }


def _correlate_around_timestamp(
    files: List[str],
    anchor_timestamp: str,
    delta,
    window: str,
) -> Optional[Dict[str, Any]]:
    """Build a correlation cluster around a timestamp."""
    anchor_dt = datetime.fromisoformat(anchor_timestamp.replace("Z", "+00:00"))

    result = investigate.search(
        files=files,
        time_start=(anchor_dt - delta).isoformat(),
        time_end=(anchor_dt + delta).isoformat(),
    )

    entries = [item.get("entry", item) for item in result.get("results", [])]
    if not entries:
        return None

    vtid = _make_virtual_trace_id("event-correlation", 0, anchor_timestamp)

    return {
        "virtual_trace_id": vtid,
        "rule_type": "event_window",
        "anchor_timestamp": anchor_timestamp,
        "window": window,
        "entry_count": len(entries),
        "entries": entries,
    }


def _correlate_by_trigger(
    files: List[str],
    trigger: Dict[str, Any],
    delta,
    window: str,
) -> List[Dict[str, Any]]:
    """Find trigger events and build correlation clusters around each."""
    clusters: List[Dict[str, Any]] = []

    # Use Rust search with level/query filters for efficient trigger finding
    search_kwargs: Dict[str, Any] = {}
    if trigger.get("level"):
        search_kwargs["level"] = trigger["level"]
    if trigger.get("pattern"):
        search_kwargs["query"] = trigger["pattern"]

    # Load candidate trigger entries
    all_candidates: List[Dict[str, Any]] = []
    for fp in files:
        try:
            result = investigate.search(files=[fp], **search_kwargs)
            for item in result.get("results", []):
                all_candidates.append(item.get("entry", item))
        except Exception:
            pass

    # If field/condition specified, filter further
    if trigger.get("field") and trigger.get("condition"):
        trigger_entries = find_trigger_events(all_candidates, trigger)
    elif trigger.get("file_pattern"):
        trigger_entries = find_trigger_events(all_candidates, trigger)
    else:
        trigger_entries = all_candidates

    # Build a cluster around each trigger event
    seen_windows: set = set()
    for idx, trigger_entry in enumerate(trigger_entries):
        trigger_ts = _parse_entry_timestamp(trigger_entry)
        if trigger_ts is None:
            continue

        # Deduplicate overlapping windows (within 1s)
        window_key = trigger_ts.isoformat()[:19]
        if window_key in seen_windows:
            continue
        seen_windows.add(window_key)

        trigger_msg = (trigger_entry.get("message") or trigger_entry.get("raw") or "")[:120]

        result = investigate.search(
            files=files,
            time_start=(trigger_ts - delta).isoformat(),
            time_end=(trigger_ts + delta).isoformat(),
        )

        entries = [item.get("entry", item) for item in result.get("results", [])]

        if len(entries) > 1:
            vtid = _make_virtual_trace_id(
                "event-trigger",
                idx,
                f"{trigger_ts.isoformat()}:{trigger_msg}",
            )
            clusters.append(
                {
                    "virtual_trace_id": vtid,
                    "rule_type": "event_trigger",
                    "trigger": trigger,
                    "anchor_timestamp": trigger_ts.isoformat(),
                    "anchor_message": trigger_msg,
                    "anchor_file": Path(trigger_entry.get("file", "")).name,
                    "anchor_line": trigger_entry.get("line_number"),
                    "window": window,
                    "entry_count": len(entries),
                    "entries": entries,
                }
            )

    return clusters
