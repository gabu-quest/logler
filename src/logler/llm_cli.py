"""
LLM-First CLI Module - Commands optimized for AI agents

Design principles:
- JSON output by default (no --json flag needed)
- No truncation - full data always
- Meaningful exit codes for chaining
- Rich metadata for LLM reasoning
- Deterministic output structure
"""

import click
import json
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from .safe_regex import safe_compile, RegexTimeoutError, RegexPatternTooLongError

# Exit codes
EXIT_SUCCESS = 0  # Success with results
EXIT_NO_RESULTS = 1  # Success but no results found
EXIT_USER_ERROR = 2  # Invalid arguments, file not found
EXIT_INTERNAL_ERROR = 3  # Unexpected exception


def _output_json(data: Dict[str, Any], pretty: bool = False) -> None:
    """Output JSON to stdout."""
    if pretty:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        click.echo(json.dumps(data, default=str))


def _error_json(message: str, code: int = EXIT_USER_ERROR) -> None:
    """Output error as JSON and exit."""
    _output_json({"error": message, "code": code})
    sys.exit(code)


def _parse_duration(duration: str) -> timedelta:
    """Parse duration string like '30m', '2h', '1d' to timedelta."""
    match = re.match(r"^(\d+)(s|m|h|d)$", duration.lower())
    if not match:
        raise ValueError(f"Invalid duration format: {duration}. Use format like '30m', '2h', '1d'")

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "s":
        return timedelta(seconds=value)
    elif unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    else:
        raise ValueError(f"Unknown time unit: {unit}")


def _expand_globs(patterns: List[str]) -> List[str]:
    """Expand glob patterns to file paths."""
    import glob

    files = []
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            files.extend(matches)
        elif Path(pattern).exists():
            files.append(pattern)
    return sorted(set(files))


@click.group()
def llm():
    """
    LLM-first CLI commands - optimized for AI agents.

    All commands output structured JSON by default.
    No truncation - full data is always returned.

    Exit codes:
      0 - Success with results
      1 - Success but no results found
      2 - User error (invalid args, file not found)
      3 - Internal error
    """
    pass


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--sample-size", default=1000, help="Number of entries to analyze (default: 1000)")
@click.option("--full", is_flag=True, help="Analyze all entries (slow for large files)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def schema(files: tuple, sample_size: int, full: bool, pretty: bool):
    """
    Infer the structure/schema of log files.

    Analyzes log files to determine available fields, formats,
    and data patterns. Useful for understanding log structure
    before running queries.

    Example:
        logler llm schema app.log worker.log
    """
    from .parser import LogParser

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        parser = LogParser()

        # Track schema information
        field_presence = defaultdict(int)
        level_values = defaultdict(int)
        format_counts = defaultdict(int)
        thread_patterns = set()
        correlation_patterns = set()
        custom_fields = set()
        timestamps = []
        total_entries = 0

        for file_path in file_list:
            try:
                with open(file_path, "r", errors="replace") as f:
                    for i, line in enumerate(f):
                        if not full and i >= sample_size:
                            break

                        line = line.rstrip()
                        if not line:
                            continue

                        entry = parser.parse_line(i + 1, line)
                        total_entries += 1

                        # Track field presence
                        if entry.timestamp:
                            field_presence["timestamp"] += 1
                            timestamps.append(entry.timestamp)
                        if entry.level:
                            field_presence["level"] += 1
                            level_values[str(entry.level)] += 1
                        if entry.message:
                            field_presence["message"] += 1
                        if entry.thread_id:
                            field_presence["thread_id"] += 1
                            thread_patterns.add(entry.thread_id)
                        if entry.correlation_id:
                            field_presence["correlation_id"] += 1
                            correlation_patterns.add(entry.correlation_id)
                        if entry.trace_id:
                            field_presence["trace_id"] += 1
                        if entry.span_id:
                            field_presence["span_id"] += 1

                        # Track format
                        format_name = getattr(entry, "format", None) or "Unknown"
                        format_counts[str(format_name)] += 1

                        # Track custom fields from extra
                        if hasattr(entry, "extra") and entry.extra:
                            for key in entry.extra.keys():
                                custom_fields.add(key)

            except FileNotFoundError:
                _error_json(f"File not found: {file_path}")
            except PermissionError:
                _error_json(f"Permission denied: {file_path}")

        if total_entries == 0:
            _output_json(
                {
                    "files_analyzed": len(file_list),
                    "total_entries": 0,
                    "schema": {},
                    "error": "No log entries found",
                },
                pretty,
            )
            sys.exit(EXIT_NO_RESULTS)

        # Build schema output
        schema_data = {}
        for field, count in field_presence.items():
            presence = count / total_entries
            schema_data[field] = {"present": round(presence, 3)}

            if field == "level":
                schema_data[field]["values"] = list(level_values.keys())
            elif field == "thread_id" and thread_patterns:
                # Extract patterns from thread IDs
                patterns = _extract_patterns(list(thread_patterns)[:100])
                if patterns:
                    schema_data[field]["patterns"] = patterns
            elif field == "correlation_id" and correlation_patterns:
                patterns = _extract_patterns(list(correlation_patterns)[:100])
                if patterns:
                    schema_data[field]["patterns"] = patterns

        # Time range
        time_range = None
        if timestamps:
            sorted_ts = sorted([t for t in timestamps if t])
            if sorted_ts:
                time_range = {"earliest": str(sorted_ts[0]), "latest": str(sorted_ts[-1])}

        # Format distribution
        format_dist = {}
        for fmt, count in format_counts.items():
            format_dist[fmt] = round(count / total_entries, 3)

        result = {
            "files_analyzed": len(file_list),
            "files": file_list,
            "total_entries": total_entries,
            "sample_size": sample_size if not full else total_entries,
            "schema": schema_data,
            "detected_formats": format_dist,
            "custom_fields": sorted(list(custom_fields)) if custom_fields else [],
        }

        if time_range:
            result["time_range"] = time_range

        _output_json(result, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


def _extract_patterns(values: List[str]) -> List[str]:
    """Extract regex-like patterns from a list of values."""
    if not values:
        return []

    patterns = set()

    # Common patterns
    for val in values[:50]:
        # worker-N pattern
        if re.match(r"^[a-z]+-\d+$", val, re.I):
            patterns.add(r"[a-z]+-\d+")
        # UUID-like
        elif re.match(r"^[a-f0-9-]{36}$", val, re.I):
            patterns.add(r"uuid")
        # req-xxx pattern
        elif re.match(r"^req-[a-z0-9]+$", val, re.I):
            patterns.add(r"req-[a-z0-9]+")
        # trace-xxx pattern
        elif re.match(r"^trace-[a-z0-9]+$", val, re.I):
            patterns.add(r"trace-[a-z0-9]+")
        else:
            # Just add a sample
            if len(patterns) < 5:
                patterns.add(val)

    return sorted(list(patterns))[:10]


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--level", help="Filter by log level (ERROR, WARN, INFO, DEBUG)")
@click.option("--query", help="Regex pattern to match in message")
@click.option("--thread", help="Filter by thread ID")
@click.option("--correlation", help="Filter by correlation ID")
@click.option("--after", help="Only entries after this timestamp (ISO8601)")
@click.option("--before", help="Only entries before this timestamp (ISO8601)")
@click.option("--last", help="Only entries in last N duration (e.g., 30m, 2h)")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--context", type=int, default=0, help="Include N context lines")
@click.option("--include-raw/--no-raw", default=True, help="Include raw log line")
@click.option("--aggregate/--no-aggregate", default=True, help="Include aggregations")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def search(
    files: tuple,
    level: Optional[str],
    query: Optional[str],
    thread: Optional[str],
    correlation: Optional[str],
    after: Optional[str],
    before: Optional[str],
    last: Optional[str],
    limit: Optional[int],
    context: int,
    include_raw: bool,
    aggregate: bool,
    pretty: bool,
):
    """
    Search logs with full results - no truncation.

    Returns complete search results with metadata.
    Use --limit to restrict results if needed.

    Example:
        logler llm search app.log --level ERROR --query "timeout"
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        # Calculate time filters
        after_ts = None
        before_ts = None

        if last:
            try:
                duration = _parse_duration(last)
                before_ts = datetime.now()
                after_ts = before_ts - duration
            except ValueError as e:
                _error_json(str(e))
        else:
            if after:
                try:
                    after_ts = datetime.fromisoformat(after.replace("Z", "+00:00"))
                except ValueError:
                    _error_json(f"Invalid timestamp format for --after: {after}")
            if before:
                try:
                    before_ts = datetime.fromisoformat(before.replace("Z", "+00:00"))
                except ValueError:
                    _error_json(f"Invalid timestamp format for --before: {before}")

        # Call search
        result = investigate.search(
            files=file_list,
            query=query,
            level=level,
            thread_id=thread,
            correlation_id=correlation,
            limit=limit,
            context_lines=context,
            output_format="full",
        )

        # Build LLM-optimized output
        results = result.get("results", [])

        # Apply time filters if specified
        if after_ts or before_ts:
            filtered = []
            for item in results:
                entry = item.get("entry", {})
                ts_str = entry.get("timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if after_ts and ts < after_ts:
                            continue
                        if before_ts and ts > before_ts:
                            continue
                    except (ValueError, TypeError):
                        pass
                filtered.append(item)
            results = filtered

        # Transform results
        output_results = []
        for item in results:
            entry = item.get("entry", {})
            out_entry = {
                "file": entry.get("file", file_list[0] if len(file_list) == 1 else None),
                "line_number": entry.get("line_number"),
                "timestamp": entry.get("timestamp"),
                "level": entry.get("level"),
                "message": entry.get("message"),
            }

            # Optional fields
            if entry.get("thread_id"):
                out_entry["thread_id"] = entry["thread_id"]
            if entry.get("correlation_id"):
                out_entry["correlation_id"] = entry["correlation_id"]
            if entry.get("trace_id"):
                out_entry["trace_id"] = entry["trace_id"]
            if entry.get("span_id"):
                out_entry["span_id"] = entry["span_id"]
            if include_raw and entry.get("raw"):
                out_entry["raw"] = entry["raw"]

            # Context if requested
            if context > 0:
                if item.get("context_before"):
                    out_entry["context_before"] = item["context_before"]
                if item.get("context_after"):
                    out_entry["context_after"] = item["context_after"]

            output_results.append(out_entry)

        output = {
            "query": {
                "files": file_list,
                "level": level,
                "pattern": query,
                "thread": thread,
                "correlation": correlation,
            },
            "summary": {
                "total_matches": len(output_results),
                "files_searched": len(file_list),
            },
            "results": output_results,
        }

        # Add aggregations if requested
        if aggregate and output_results:
            agg_by_level = defaultdict(int)
            agg_by_thread = defaultdict(int)

            for r in output_results:
                if r.get("level"):
                    agg_by_level[r["level"]] += 1
                if r.get("thread_id"):
                    agg_by_thread[r["thread_id"]] += 1

            output["aggregations"] = {
                "by_level": dict(agg_by_level),
                "by_thread": dict(agg_by_thread) if agg_by_thread else None,
            }

        _output_json(output, pretty)

        if len(output_results) == 0:
            sys.exit(EXIT_NO_RESULTS)
        else:
            sys.exit(EXIT_SUCCESS)

    except RuntimeError as e:
        if "Rust backend" in str(e):
            _error_json(
                "Rust backend not available. Build with: maturin develop --release",
                EXIT_INTERNAL_ERROR,
            )
        raise
    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option(
    "--strategy",
    type=click.Choice(["random", "diverse", "errors_focused", "head", "tail", "edges"]),
    default="diverse",
    help="Sampling strategy",
)
@click.option("--size", type=int, default=100, help="Sample size (default: 100)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def sample(files: tuple, strategy: str, size: int, pretty: bool):
    """
    Get a statistically representative sample of log entries.

    Strategies:
      random - Pure random sample
      diverse - Cover all levels, threads, time ranges
      errors_focused - Prioritize errors and warnings
      head - First N entries
      tail - Last N entries
      edges - Boundaries and transitions

    Example:
        logler llm sample app.log --strategy errors_focused --size 50
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        result = investigate.smart_sample(files=file_list, strategy=strategy, sample_size=size)

        # Build output
        output = {
            "population": {"total_entries": result.get("total_population", 0), "files": file_list},
            "sample": {
                "size": result.get("sample_size", 0),
                "strategy": strategy,
            },
            "entries": [],
        }

        # Add coverage info if available
        if "level_distribution" in result:
            output["sample"]["coverage"] = {"levels": result["level_distribution"]}

        # Transform entries
        for entry in result.get("entries", []):
            out_entry = {
                "line_number": entry.get("line_number"),
                "timestamp": entry.get("timestamp"),
                "level": entry.get("level"),
                "message": entry.get("message"),
            }
            if entry.get("thread_id"):
                out_entry["thread_id"] = entry["thread_id"]
            if entry.get("selection_reason"):
                out_entry["selection_reason"] = entry["selection_reason"]

            output["entries"].append(out_entry)

        _output_json(output, pretty)

        if len(output["entries"]) == 0:
            sys.exit(EXIT_NO_RESULTS)
        else:
            sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--last", help="Analyze last N duration (e.g., 30m, 2h)")
@click.option("--after", help="Start timestamp (ISO8601)")
@click.option("--before", help="End timestamp (ISO8601)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def triage(
    files: tuple, last: Optional[str], after: Optional[str], before: Optional[str], pretty: bool
):
    """
    Quick severity assessment for incident response.

    Returns severity level, top issues, and suggested actions.
    Designed for rapid initial assessment during incidents.

    Example:
        logler llm triage /var/log/app/*.log --last 1h
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        # Run auto-insights
        result = investigate.analyze_with_insights(files=file_list, auto_investigate=True)

        overview = result.get("overview", {})
        insights = result.get("insights", [])

        # Determine severity
        error_rate = overview.get("error_rate", 0)
        if error_rate > 0.2:
            severity = "critical"
            confidence = 0.95
        elif error_rate > 0.1:
            severity = "high"
            confidence = 0.9
        elif error_rate > 0.05:
            severity = "medium"
            confidence = 0.85
        elif error_rate > 0.01:
            severity = "low"
            confidence = 0.8
        else:
            severity = "healthy"
            confidence = 0.9

        # Build top issues
        top_issues = []
        for insight in insights[:5]:
            issue = {
                "type": insight.get("type"),
                "severity": insight.get("severity"),
                "description": insight.get("description"),
            }
            if insight.get("count"):
                issue["count"] = insight["count"]
            top_issues.append(issue)

        # Build suggested actions
        suggested_actions = []
        for insight in insights[:3]:
            if insight.get("suggestion"):
                suggested_actions.append({"action": "investigate", "reason": insight["suggestion"]})

        output = {
            "assessment": {
                "severity": severity,
                "confidence": confidence,
                "summary": f"Error rate: {error_rate:.1%}, {len(insights)} issues detected",
            },
            "metrics": {
                "error_rate": round(error_rate, 4),
                "error_count": overview.get("error_count", 0),
                "total_entries": overview.get("total_logs", 0),
                "log_levels": overview.get("log_levels", {}),
            },
            "top_issues": top_issues,
            "suggested_actions": suggested_actions,
            "next_steps": result.get("next_steps", []),
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("identifier")
@click.option("--files", "-f", multiple=True, help="Files to search (supports globs)")
@click.option(
    "--type",
    "id_type",
    type=click.Choice(["auto", "correlation_id", "trace_id", "thread_id"]),
    default="auto",
    help="Identifier type",
)
@click.option("--window", default="1h", help="Time window to search (e.g., 30m, 2h)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def correlate(identifier: str, files: tuple, id_type: str, window: str, pretty: bool):
    """
    Trace a request/correlation ID across files and services.

    Builds a complete timeline of all log entries matching
    the identifier across multiple files.

    Example:
        logler llm correlate req-abc123 --files "*.log"
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

        # Determine ID type
        correlation_id = None
        trace_id = None
        thread_id = None

        if id_type == "auto":
            if identifier.startswith("trace-") or len(identifier) == 32:
                trace_id = identifier
                detected_type = "trace_id"
            elif identifier.startswith("req-") or identifier.startswith("corr-"):
                correlation_id = identifier
                detected_type = "correlation_id"
            else:
                correlation_id = identifier
                detected_type = "correlation_id"
        elif id_type == "correlation_id":
            correlation_id = identifier
            detected_type = "correlation_id"
        elif id_type == "trace_id":
            trace_id = identifier
            detected_type = "trace_id"
        elif id_type == "thread_id":
            thread_id = identifier
            detected_type = "thread_id"

        result = investigate.follow_thread(
            files=file_list, thread_id=thread_id, correlation_id=correlation_id, trace_id=trace_id
        )

        entries = result.get("entries", [])

        # Build timeline
        timeline = []
        services = set()
        start_time = None

        for i, entry in enumerate(entries):
            ts = entry.get("timestamp")
            if ts and not start_time:
                start_time = ts

            service = entry.get("service") or entry.get("service_name")
            if service:
                services.add(service)

            timeline_entry = {
                "sequence": i + 1,
                "timestamp": ts,
                "file": entry.get("file"),
                "line_number": entry.get("line_number"),
                "level": entry.get("level"),
                "message": entry.get("message"),
            }

            if entry.get("thread_id"):
                timeline_entry["thread_id"] = entry["thread_id"]
            if service:
                timeline_entry["service"] = service

            timeline.append(timeline_entry)

        # Find error point
        error_point = None
        for entry in timeline:
            if entry.get("level") in ["ERROR", "FATAL", "CRITICAL"]:
                error_point = entry
                break

        output = {
            "identifier": identifier,
            "identifier_type": detected_type,
            "trace": {
                "total_entries": len(timeline),
                "services": list(services),
                "duration_ms": result.get("duration_ms"),
                "outcome": "error" if error_point else "success",
            },
            "timeline": timeline,
        }

        if error_point:
            output["error_point"] = error_point

        _output_json(output, pretty)

        if len(timeline) == 0:
            sys.exit(EXIT_NO_RESULTS)
        else:
            sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("identifier")
@click.option("--files", "-f", multiple=True, help="Files to search (supports globs)")
@click.option("--max-depth", type=int, help="Maximum hierarchy depth")
@click.option("--min-confidence", type=float, default=0.0, help="Minimum confidence (0.0-1.0)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def hierarchy(
    identifier: str, files: tuple, max_depth: Optional[int], min_confidence: float, pretty: bool
):
    """
    Build full parent-child hierarchy tree as structured data.

    Detects thread/span relationships using:
    - Explicit parent_span_id (OpenTelemetry)
    - Naming patterns (worker-1.task-a)
    - Temporal inference

    Example:
        logler llm hierarchy trace-xyz789 --files "*.log"
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

        result = investigate.follow_thread_hierarchy(
            files=file_list,
            root_identifier=identifier,
            max_depth=max_depth,
            min_confidence=min_confidence,
        )

        # Output directly - hierarchy result is already structured
        _output_json(result, pretty)

        if not result.get("roots"):
            sys.exit(EXIT_NO_RESULTS)
        else:
            sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command("verify-pattern")
@click.argument("files", nargs=-1, required=True)
@click.option("--pattern", required=True, help="Regex pattern to verify")
@click.option("--extract-groups", is_flag=True, help="Extract and analyze capture groups")
@click.option("--hypothesis", help="Natural language hypothesis (for documentation)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def verify_pattern(
    files: tuple, pattern: str, extract_groups: bool, hypothesis: Optional[str], pretty: bool
):
    """
    Test a hypothesis about log patterns programmatically.

    Verifies if a pattern exists in logs and optionally
    extracts/analyzes capture groups.

    Example:
        logler llm verify-pattern app.log --pattern "timeout after (\\d+)ms" --extract-groups
    """
    from .parser import LogParser

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        try:
            regex = safe_compile(pattern)
        except (re.error, RegexTimeoutError, RegexPatternTooLongError) as e:
            _error_json(f"Invalid regex pattern: {e}")

        parser = LogParser()

        matches = []
        total_entries = 0
        group_values = defaultdict(lambda: defaultdict(int))
        by_thread = defaultdict(int)
        first_match = None
        last_match = None

        for file_path in file_list:
            try:
                with open(file_path, "r", errors="replace") as f:
                    for i, line in enumerate(f):
                        line = line.rstrip()
                        if not line:
                            continue

                        total_entries += 1
                        entry = parser.parse_line(i + 1, line)

                        # Try matching against message and raw
                        match = regex.search(entry.message or "") or regex.search(line)

                        if match:
                            match_info = {
                                "file": file_path,
                                "line_number": i + 1,
                                "raw": line[:200],
                            }

                            if extract_groups and match.groups():
                                match_info["groups"] = list(match.groups())
                                for j, grp in enumerate(match.groups()):
                                    if grp:
                                        group_values[f"group_{j+1}"][grp] += 1

                            matches.append(match_info)

                            if not first_match:
                                first_match = entry.timestamp
                            last_match = entry.timestamp

                            # Track by thread
                            if entry.thread_id:
                                by_thread[entry.thread_id] += 1

            except FileNotFoundError:
                _error_json(f"File not found: {file_path}")
            except PermissionError:
                _error_json(f"Permission denied: {file_path}")

        # Build output
        output = {
            "pattern": pattern,
            "hypothesis": hypothesis,
            "verified": len(matches) > 0,
            "statistics": {
                "total_matches": len(matches),
                "total_entries": total_entries,
                "match_rate": round(len(matches) / total_entries, 6) if total_entries > 0 else 0,
                "first_match": str(first_match) if first_match else None,
                "last_match": str(last_match) if last_match else None,
            },
            "sample_matches": matches[:20],  # First 20 matches as samples
        }

        if extract_groups and group_values:
            extracted = {}
            for group_name, values in group_values.items():
                # Get numeric stats if all values are numeric
                numeric_vals = []
                for v in values.keys():
                    try:
                        numeric_vals.append(float(v))
                    except (ValueError, TypeError):
                        pass

                group_data = {"values": dict(values), "unique_count": len(values)}

                if numeric_vals:
                    group_data["min"] = min(numeric_vals)
                    group_data["max"] = max(numeric_vals)
                    group_data["mean"] = round(sum(numeric_vals) / len(numeric_vals), 2)

                extracted[group_name] = group_data

            output["extracted_groups"] = extracted

        if by_thread:
            output["distribution"] = {"by_thread": dict(by_thread)}

        _output_json(output, pretty)

        if len(matches) == 0:
            sys.exit(EXIT_NO_RESULTS)
        else:
            sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--level", help="Filter by level")
@click.option("--query", help="Filter by pattern")
@click.option("--fields", help="Comma-separated fields to include")
@click.option("--compact", is_flag=True, help="Minimal JSON (short keys)")
def emit(
    files: tuple, level: Optional[str], query: Optional[str], fields: Optional[str], compact: bool
):
    """
    Stream parsed entries as JSONL for processing.

    Outputs one JSON object per line, suitable for piping
    to other tools or processing large files.

    Example:
        logler llm emit app.log --level ERROR | head -100
    """
    from .parser import LogParser

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        parser = LogParser()

        # Parse field list
        include_fields = None
        if fields:
            include_fields = set(f.strip() for f in fields.split(","))

        # Compile query regex if provided
        query_regex = None
        if query:
            try:
                query_regex = safe_compile(query, re.IGNORECASE)
            except (re.error, RegexTimeoutError, RegexPatternTooLongError) as e:
                _error_json(f"Invalid regex pattern: {e}")

        for file_path in file_list:
            try:
                with open(file_path, "r", errors="replace") as f:
                    for i, line in enumerate(f):
                        line = line.rstrip()
                        if not line:
                            continue

                        entry = parser.parse_line(i + 1, line)

                        # Apply level filter
                        if level and str(entry.level).upper() != level.upper():
                            continue

                        # Apply query filter
                        if query_regex:
                            if not query_regex.search(entry.message or ""):
                                if not query_regex.search(line):
                                    continue

                        # Build output
                        if compact:
                            out = {
                                "ln": i + 1,
                                "ts": str(entry.timestamp) if entry.timestamp else None,
                                "lv": str(entry.level) if entry.level else None,
                                "msg": entry.message,
                            }
                            if entry.thread_id:
                                out["th"] = entry.thread_id
                        else:
                            out = {
                                "file": file_path,
                                "line_number": i + 1,
                                "timestamp": str(entry.timestamp) if entry.timestamp else None,
                                "level": str(entry.level) if entry.level else None,
                                "message": entry.message,
                            }
                            if entry.thread_id:
                                out["thread_id"] = entry.thread_id
                            if entry.correlation_id:
                                out["correlation_id"] = entry.correlation_id

                        # Filter fields if specified
                        if include_fields:
                            out = {k: v for k, v in out.items() if k in include_fields}

                        click.echo(json.dumps(out, default=str))

            except FileNotFoundError:
                pass  # Skip missing files in emit mode
            except PermissionError:
                pass

        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        # In emit mode, errors go to stderr
        import sys as _sys

        _sys.stderr.write(json.dumps({"error": str(e)}) + "\n")
        sys.exit(EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--before-start", help="Before period start (ISO8601)")
@click.option("--before-end", help="Before period end (ISO8601)")
@click.option("--after-start", help="After period start (ISO8601)")
@click.option("--after-end", help="After period end (ISO8601)")
@click.option("--baseline", help="Use last N as baseline (e.g., 1h)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def diff(
    files: tuple,
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
    from .parser import LogParser
    from datetime import timezone

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

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
                (after_metrics["total"] - before_metrics["total"]) / before_metrics["total"] * 100,
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


# Session management subgroup
@llm.group()
def session():
    """
    Stateful investigation sessions for complex analyses.

    Sessions track investigation steps and can be saved/resumed.
    """
    pass


@session.command("create")
@click.option("--files", "-f", multiple=True, required=True, help="Files to include")
@click.option("--name", help="Session name")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_create(files: tuple, name: Optional[str], pretty: bool):
    """Create a new investigation session."""
    import uuid
    from pathlib import Path

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session_name = name or f"investigation-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        session_data = {
            "session_id": session_id,
            "name": session_name,
            "created_at": datetime.now().isoformat(),
            "files": file_list,
            "status": "active",
            "log": [],
        }

        # Save session
        sessions_dir = Path.home() / ".logler" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        session_file = sessions_dir / f"{session_id}.json"
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        output = {
            "session_id": session_id,
            "name": session_name,
            "created_at": session_data["created_at"],
            "files": file_list,
            "status": "active",
            "session_file": str(session_file),
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("list")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_list(pretty: bool):
    """List all investigation sessions."""
    from pathlib import Path

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"

        if not sessions_dir.exists():
            _output_json({"sessions": []}, pretty)
            sys.exit(EXIT_SUCCESS)

        sessions = []
        for session_file in sessions_dir.glob("sess_*.json"):
            try:
                with open(session_file) as f:
                    data = json.load(f)
                    sessions.append(
                        {
                            "session_id": data.get("session_id"),
                            "name": data.get("name"),
                            "created_at": data.get("created_at"),
                            "status": data.get("status"),
                            "files_count": len(data.get("files", [])),
                        }
                    )
            except (json.JSONDecodeError, KeyError):
                pass

        # Sort by created_at descending
        sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        _output_json({"sessions": sessions}, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("query")
@click.argument("session_id")
@click.option("--level", help="Filter by level")
@click.option("--query", help="Search pattern")
@click.option("--limit", type=int, help="Limit results")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_query(
    session_id: str, level: Optional[str], query: Optional[str], limit: Optional[int], pretty: bool
):
    """Query logs within a session context."""
    from pathlib import Path
    from . import investigate

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"
        session_file = sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            _error_json(f"Session not found: {session_id}")

        with open(session_file) as f:
            session_data = json.load(f)

        files = session_data.get("files", [])

        result = investigate.search(
            files=files, query=query, level=level, limit=limit, output_format="full"
        )

        # Log the query
        session_data["log"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "query",
                "params": {"level": level, "query": query, "limit": limit},
                "results_count": len(result.get("results", [])),
            }
        )

        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        _output_json(result, pretty)
        sys.exit(EXIT_SUCCESS if result.get("results") else EXIT_NO_RESULTS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("note")
@click.argument("session_id")
@click.option("--text", required=True, help="Note text")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_note(session_id: str, text: str, pretty: bool):
    """Add a note to a session."""
    from pathlib import Path

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"
        session_file = sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            _error_json(f"Session not found: {session_id}")

        with open(session_file) as f:
            session_data = json.load(f)

        note_entry = {"timestamp": datetime.now().isoformat(), "action": "note", "text": text}

        session_data["log"].append(note_entry)

        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        _output_json({"status": "ok", "note": note_entry}, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@session.command("conclude")
@click.argument("session_id")
@click.option("--summary", required=True, help="Investigation summary")
@click.option("--root-cause", help="Root cause description")
@click.option("--confidence", type=float, default=0.8, help="Confidence level (0.0-1.0)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def session_conclude(
    session_id: str, summary: str, root_cause: Optional[str], confidence: float, pretty: bool
):
    """Conclude a session with findings."""
    from pathlib import Path

    try:
        sessions_dir = Path.home() / ".logler" / "sessions"
        session_file = sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            _error_json(f"Session not found: {session_id}")

        with open(session_file) as f:
            session_data = json.load(f)

        conclusion = {
            "summary": summary,
            "root_cause": root_cause,
            "confidence": confidence,
            "concluded_at": datetime.now().isoformat(),
        }

        session_data["status"] = "concluded"
        session_data["conclusion"] = conclusion
        session_data["log"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "conclude",
                "conclusion": conclusion,
            }
        )

        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, default=str)

        output = {
            "session_id": session_id,
            "conclusion": conclusion,
            "investigation_log": session_data["log"],
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)
