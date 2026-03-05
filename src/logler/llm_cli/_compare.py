"""Comparison commands: compare and diff."""

import click
import sys
from typing import Optional, List, Dict, Any
from collections import defaultdict
from datetime import datetime

from ._core import (
    llm,
    EXIT_SUCCESS,
    EXIT_INTERNAL_ERROR,
    _output_json,
    _error_json,
    _parse_duration,
    db_source_option,
    _db_file_source,
)


@llm.command()
@click.argument("id1")
@click.argument("id2")
@click.option("--files", "-f", multiple=True, help="Files to search (supports globs)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
@db_source_option
def compare(id1: str, id2: str, files: tuple, pretty: bool, db_path: Optional[str]):
    """
    Compare two requests/traces side by side.

    Shows differences between a failed and successful request,
    helping identify what went wrong.

    Example:
        logler llm compare req-001 req-003 --files "*.log"
    """
    from .. import investigate

    with _db_file_source(files, db_path, default_glob="*.log") as file_list:
        try:
            # Get timelines for both requests
            result1 = investigate.follow_thread(file_list, correlation_id=id1)
            result2 = investigate.follow_thread(file_list, correlation_id=id2)

            entries1 = result1.get("entries", [])
            entries2 = result2.get("entries", [])

            # Analyze each request
            def analyze_request(entries: List[Dict[str, Any]], req_id: str) -> Dict[str, Any]:
                if not entries:
                    return {"id": req_id, "found": False}

                levels = defaultdict(int)
                messages = []
                timestamps = []
                errors = []

                for e in entries:
                    level = e.get("level", "UNKNOWN")
                    levels[level] += 1
                    messages.append(e.get("message", ""))
                    if e.get("timestamp"):
                        timestamps.append(e["timestamp"])
                    if level in ["ERROR", "FATAL", "CRITICAL"]:
                        errors.append(
                            {
                                "message": e.get("message"),
                                "timestamp": e.get("timestamp"),
                                "line_number": e.get("line_number"),
                            }
                        )

                # Calculate duration
                duration_ms = None
                if len(timestamps) >= 2:
                    try:
                        start = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
                        end = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
                        duration_ms = int((end - start).total_seconds() * 1000)
                    except (ValueError, TypeError):
                        pass

                return {
                    "id": req_id,
                    "found": True,
                    "entry_count": len(entries),
                    "duration_ms": duration_ms,
                    "outcome": "error" if errors else "success",
                    "levels": dict(levels),
                    "errors": errors,
                    "steps": [e.get("message", "")[:80] for e in entries],
                }

            analysis1 = analyze_request(entries1, id1)
            analysis2 = analyze_request(entries2, id2)

            # Find differences
            differences = []

            if analysis1["found"] and analysis2["found"]:
                # Duration difference
                if analysis1.get("duration_ms") and analysis2.get("duration_ms"):
                    diff_ms = analysis1["duration_ms"] - analysis2["duration_ms"]
                    if abs(diff_ms) > 100:  # Significant difference
                        differences.append(
                            {
                                "type": "duration",
                                "description": f"{id1} took {diff_ms:+d}ms compared to {id2}",
                                "value1": analysis1["duration_ms"],
                                "value2": analysis2["duration_ms"],
                            }
                        )

                # Entry count difference
                if analysis1["entry_count"] != analysis2["entry_count"]:
                    differences.append(
                        {
                            "type": "entry_count",
                            "description": (
                                f"{id1} has {analysis1['entry_count']} entries, "
                                f"{id2} has {analysis2['entry_count']}"
                            ),
                            "value1": analysis1["entry_count"],
                            "value2": analysis2["entry_count"],
                        }
                    )

                # Outcome difference
                if analysis1["outcome"] != analysis2["outcome"]:
                    differences.append(
                        {
                            "type": "outcome",
                            "description": f"{id1} {analysis1['outcome']}, {id2} {analysis2['outcome']}",
                            "value1": analysis1["outcome"],
                            "value2": analysis2["outcome"],
                        }
                    )

                # Find where they diverge
                steps1 = analysis1.get("steps", [])
                steps2 = analysis2.get("steps", [])
                divergence_point = None
                for i, (s1, s2) in enumerate(zip(steps1, steps2)):
                    if s1 != s2:
                        divergence_point = {
                            "step": i + 1,
                            "request1": s1,
                            "request2": s2,
                        }
                        break

                if divergence_point:
                    differences.append(
                        {
                            "type": "divergence",
                            "description": f"Requests diverge at step {divergence_point['step']}",
                            "detail": divergence_point,
                        }
                    )

            output = {
                "comparison": {
                    "request1": analysis1,
                    "request2": analysis2,
                },
                "differences": differences,
                "summary": (
                    f"{id1}: {analysis1.get('outcome', 'not found')}, "
                    f"{id2}: {analysis2.get('outcome', 'not found')}"
                ),
            }

            # Add recommendation if one failed and one succeeded
            if analysis1.get("outcome") == "error" and analysis2.get("outcome") == "success":
                if analysis1.get("errors"):
                    output["recommendation"] = (
                        f"Investigate error in {id1}: "
                        f"{analysis1['errors'][0].get('message', 'Unknown error')}"
                    )
            elif analysis2.get("outcome") == "error" and analysis1.get("outcome") == "success":
                if analysis2.get("errors"):
                    output["recommendation"] = (
                        f"Investigate error in {id2}: "
                        f"{analysis2['errors'][0].get('message', 'Unknown error')}"
                    )

            _output_json(output, pretty)
            sys.exit(EXIT_SUCCESS)

        except Exception as e:
            _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("files", nargs=-1, required=False)
@db_source_option
@click.option("--before-start", help="Before period start (ISO8601)")
@click.option("--before-end", help="Before period end (ISO8601)")
@click.option("--after-start", help="After period start (ISO8601)")
@click.option("--after-end", help="After period end (ISO8601)")
@click.option("--baseline", help="Use last N as baseline (e.g., 1h)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def diff(
    files: tuple,
    db_path: Optional[str],
    before_start: Optional[str],
    before_end: Optional[str],
    after_start: Optional[str],
    after_end: Optional[str],
    baseline: Optional[str],
    pretty: bool,
):
    """
    Compare log characteristics between time periods.

    Useful for understanding what changed before/after an incident.

    Example:
        logler llm diff app.log --baseline 1h
    """
    from ..parser import LogParser
    from datetime import timezone

    with _db_file_source(files, db_path) as file_list:
        try:
            parser = LogParser()

            # Parse time periods
            now = datetime.now(timezone.utc)

            if baseline:
                try:
                    duration = _parse_duration(baseline)
                    after_end_ts = now
                    after_start_ts = now - duration
                    before_end_ts = after_start_ts
                    before_start_ts = before_end_ts - duration
                except ValueError as e:
                    _error_json(str(e))
            else:

                def parse_ts(s):
                    if not s:
                        return None
                    try:
                        return datetime.fromisoformat(s.replace("Z", "+00:00"))
                    except ValueError:
                        _error_json(f"Invalid timestamp: {s}")

                before_start_ts = parse_ts(before_start)
                before_end_ts = parse_ts(before_end)
                after_start_ts = parse_ts(after_start)
                after_end_ts = parse_ts(after_end)

            # Collect entries for each period
            before_entries = []
            after_entries = []

            for file_path in file_list:
                try:
                    with open(file_path, "r", errors="replace") as f:
                        for i, line in enumerate(f):
                            line = line.rstrip()
                            if not line:
                                continue

                            entry = parser.parse_line(i + 1, line)

                            if not entry.timestamp:
                                continue

                            try:
                                ts = entry.timestamp
                                if isinstance(ts, str):
                                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

                                # Make timezone-aware if needed
                                if ts.tzinfo is None:
                                    ts = ts.replace(tzinfo=timezone.utc)

                                if before_start_ts and before_end_ts:
                                    if before_start_ts <= ts <= before_end_ts:
                                        before_entries.append(entry)

                                if after_start_ts and after_end_ts:
                                    if after_start_ts <= ts <= after_end_ts:
                                        after_entries.append(entry)
                            except (ValueError, TypeError):
                                pass

                except (FileNotFoundError, PermissionError):
                    pass

            # Calculate metrics
            def calc_metrics(entries):
                if not entries:
                    return {"total": 0, "error_rate": 0, "by_level": {}}

                by_level = defaultdict(int)
                errors = 0
                for e in entries:
                    lvl = str(e.level) if e.level else "UNKNOWN"
                    by_level[lvl] += 1
                    if lvl in ["ERROR", "FATAL", "CRITICAL"]:
                        errors += 1

                return {
                    "total": len(entries),
                    "error_count": errors,
                    "error_rate": round(errors / len(entries), 4) if entries else 0,
                    "by_level": dict(by_level),
                }

            before_metrics = calc_metrics(before_entries)
            after_metrics = calc_metrics(after_entries)

            # Calculate changes
            volume_change = 0
            if before_metrics["total"] > 0:
                volume_change = round(
                    (after_metrics["total"] - before_metrics["total"])
                    / before_metrics["total"]
                    * 100,
                    1,
                )

            error_rate_change = None
            if before_metrics["error_rate"] > 0:
                change_pct = (
                    (after_metrics["error_rate"] - before_metrics["error_rate"])
                    / before_metrics["error_rate"]
                    * 100
                )
                error_rate_change = f"{change_pct:+.0f}%"

            output = {
                "comparison": {
                    "before": {
                        "start": str(before_start_ts) if before_start_ts else None,
                        "end": str(before_end_ts) if before_end_ts else None,
                        **before_metrics,
                    },
                    "after": {
                        "start": str(after_start_ts) if after_start_ts else None,
                        "end": str(after_end_ts) if after_end_ts else None,
                        **after_metrics,
                    },
                },
                "changes": {
                    "volume_change_percent": volume_change,
                    "error_rate_before": before_metrics["error_rate"],
                    "error_rate_after": after_metrics["error_rate"],
                    "error_rate_change": error_rate_change,
                },
            }

            _output_json(output, pretty)
            sys.exit(EXIT_SUCCESS)

        except Exception as e:
            _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)
