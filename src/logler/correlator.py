"""
Correlation engine for linking log entries across files.

Applies user-defined correlation rules from .logler/correlations.yaml to
create virtual trace IDs that link related entries across different log files.
"""

from __future__ import annotations

import bisect
import fnmatch
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (
    CorrelationsConfig,
    EventCondition,
    FieldMatchRule,
    TemporalRule,
    parse_duration,
)
from .safe_regex import try_compile


def _get_field_value(entry: Dict[str, Any], field_name: str) -> Any:
    """Extract a field value from a log entry.

    Checks top-level entry keys first, then the 'fields' sub-dict.
    """
    if field_name in entry:
        return entry[field_name]
    return entry.get("fields", {}).get(field_name)


def _matches_file_pattern(entry: Dict[str, Any], file_pattern: Optional[str]) -> bool:
    """Check if an entry's source file matches a glob pattern."""
    if file_pattern is None:
        return True
    file_path = entry.get("file", "")
    filename = Path(file_path).name if file_path else ""
    return fnmatch.fnmatch(filename, file_pattern)


def _make_virtual_trace_id(group_name: str, rule_index: int, key: str) -> str:
    """Generate a deterministic virtual trace ID from rule + shared value."""
    raw = f"{group_name}:{rule_index}:{key}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"vt-{short_hash}"


# =============================================================================
# Field-Based Correlation (M2.2)
# =============================================================================


def _apply_field_match_rule(
    entries: List[Dict[str, Any]],
    rule: FieldMatchRule,
    group_name: str,
    rule_index: int,
) -> List[Dict[str, Any]]:
    """Apply a single field_match rule, returning correlation clusters.

    For each unique value of the source field in source-file entries,
    finds all target-file entries where the target field has the same value.
    """
    clusters = []

    # Partition entries by file pattern
    source_entries = [e for e in entries if _matches_file_pattern(e, rule.source.file_pattern)]
    target_entries = [e for e in entries if _matches_file_pattern(e, rule.target.file_pattern)]

    # Build index: source field value -> list of source entries
    source_by_value: Dict[str, List[Dict[str, Any]]] = {}
    for entry in source_entries:
        val = _get_field_value(entry, rule.source.field)
        if val is not None:
            key = str(val)
            source_by_value.setdefault(key, []).append(entry)

    # Build index: target field value -> list of target entries
    target_by_value: Dict[str, List[Dict[str, Any]]] = {}
    for entry in target_entries:
        val = _get_field_value(entry, rule.target.field)
        if val is not None:
            key = str(val)
            target_by_value.setdefault(key, []).append(entry)

    # Match: for each source value, find target entries with same value
    for shared_value, src_list in source_by_value.items():
        tgt_list = target_by_value.get(shared_value, [])
        if not tgt_list:
            continue

        virtual_id = _make_virtual_trace_id(group_name, rule_index, shared_value)
        cluster_entries = src_list + tgt_list

        clusters.append(
            {
                "virtual_trace_id": virtual_id,
                "group": group_name,
                "rule_type": "field_match",
                "rule_index": rule_index,
                "shared_value": shared_value,
                "source_field": rule.source.field,
                "target_field": rule.target.field,
                "entry_count": len(cluster_entries),
                "source_count": len(src_list),
                "target_count": len(tgt_list),
                "entries": cluster_entries,
            }
        )

    return clusters


# =============================================================================
# Temporal Correlation (M2.3)
# =============================================================================


_CONDITION_PATTERN = re.compile(r"^\s*(<=?|>=?|==|!=)\s*(-?\d+(?:\.\d+)?)\s*$")


def _evaluate_condition(value: Any, condition: str) -> bool:
    """Evaluate a simple comparison condition against a value.

    Supports: < > <= >= == != with numeric operands.
    """
    match = _CONDITION_PATTERN.match(condition)
    if not match:
        return False

    operator = match.group(1)
    threshold = float(match.group(2))

    try:
        num_value = float(value)
    except (TypeError, ValueError):
        return False

    if operator == "<":
        return num_value < threshold
    elif operator == ">":
        return num_value > threshold
    elif operator == "<=":
        return num_value <= threshold
    elif operator == ">=":
        return num_value >= threshold
    elif operator == "==":
        return num_value == threshold
    elif operator == "!=":
        return num_value != threshold
    return False


def _matches_anchor(entry: Dict[str, Any], anchor: EventCondition) -> bool:
    """Check if an entry matches all specified anchor conditions."""
    if not _matches_file_pattern(entry, anchor.file_pattern):
        return False

    if anchor.level is not None:
        entry_level = (entry.get("level") or "").upper()
        if entry_level != anchor.level.upper():
            return False

    if anchor.pattern is not None:
        message = entry.get("message") or entry.get("raw") or ""
        regex = try_compile(anchor.pattern)
        if regex is None or not regex.search(message):
            return False

    if anchor.field is not None and anchor.condition is not None:
        field_val = _get_field_value(entry, anchor.field)
        if field_val is None or not _evaluate_condition(field_val, anchor.condition):
            return False

    return True


def _parse_entry_timestamp(entry: Dict[str, Any]) -> Optional[datetime]:
    """Parse an entry's timestamp into a datetime object."""
    ts = entry.get("timestamp")
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _apply_temporal_rule(
    entries: List[Dict[str, Any]],
    rule: TemporalRule,
    group_name: str,
    rule_index: int,
) -> List[Dict[str, Any]]:
    """Apply a single temporal rule, returning correlation clusters.

    Finds anchor events and collects all entries within the time window.
    """
    clusters = []
    window = parse_duration(rule.window)

    # Find anchor events
    anchors = []
    for entry in entries:
        if _matches_anchor(entry, rule.anchor):
            ts = _parse_entry_timestamp(entry)
            if ts is not None:
                anchors.append((entry, ts))

    if not anchors:
        return clusters

    # Pre-parse all timestamps for efficient windowing
    timed_entries = []
    for entry in entries:
        ts = _parse_entry_timestamp(entry)
        if ts is not None:
            timed_entries.append((entry, ts))

    # Sort by timestamp for efficient scanning
    timed_entries.sort(key=lambda x: x[1])

    # Extract sorted timestamps for binary search
    timestamps = [ts for _, ts in timed_entries]

    # For each anchor, collect entries within the window using bisect
    for anchor_entry, anchor_ts in anchors:
        window_start = anchor_ts - window
        window_end = anchor_ts + window

        lo = bisect.bisect_left(timestamps, window_start)
        hi = bisect.bisect_right(timestamps, window_end)
        cluster_entries = [timed_entries[i][0] for i in range(lo, hi)]

        if len(cluster_entries) <= 1:
            # Only the anchor itself - no interesting correlation
            continue

        anchor_desc = (anchor_entry.get("message") or anchor_entry.get("raw") or "")[:120]
        virtual_id = _make_virtual_trace_id(
            group_name, rule_index, f"{anchor_ts.isoformat()}:{anchor_desc}"
        )

        clusters.append(
            {
                "virtual_trace_id": virtual_id,
                "group": group_name,
                "rule_type": "temporal",
                "rule_index": rule_index,
                "anchor_timestamp": anchor_ts.isoformat(),
                "anchor_message": anchor_desc,
                "window": rule.window,
                "entry_count": len(cluster_entries),
                "entries": cluster_entries,
            }
        )

    return clusters


# =============================================================================
# Public API
# =============================================================================


def correlate_by_rules(
    entries: List[Dict[str, Any]],
    config: CorrelationsConfig,
    group_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply correlation rules to group entries by virtual trace IDs.

    Args:
        entries: List of log entry dicts (as returned by search/emit).
        config: Loaded CorrelationsConfig with correlation rules.
        group_name: If given, only apply rules from this named group.

    Returns:
        Dictionary with correlation results:
        {
            "clusters": [...],
            "total_clusters": int,
            "total_entries_correlated": int,
            "groups_applied": [str],
        }
    """
    all_clusters: List[Dict[str, Any]] = []

    groups_to_apply = config.correlations
    if group_name is not None:
        if group_name not in config.correlations:
            return {
                "clusters": [],
                "total_clusters": 0,
                "total_entries_correlated": 0,
                "groups_applied": [],
                "error": f"Unknown correlation group: {group_name!r}",
            }
        groups_to_apply = {group_name: config.correlations[group_name]}

    applied_groups = []

    for gname, group in groups_to_apply.items():
        applied_groups.append(gname)
        for rule_idx, rule in enumerate(group.rules):
            if isinstance(rule, FieldMatchRule):
                clusters = _apply_field_match_rule(entries, rule, gname, rule_idx)
                all_clusters.extend(clusters)
            elif isinstance(rule, TemporalRule):
                clusters = _apply_temporal_rule(entries, rule, gname, rule_idx)
                all_clusters.extend(clusters)

    # Count unique correlated entries
    correlated_ids = set()
    for cluster in all_clusters:
        for entry in cluster["entries"]:
            entry_id = entry.get("id") or id(entry)
            correlated_ids.add(entry_id)

    return {
        "clusters": all_clusters,
        "total_clusters": len(all_clusters),
        "total_entries_correlated": len(correlated_ids),
        "groups_applied": applied_groups,
    }
