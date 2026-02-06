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
from .config import find_config, load_config, find_correlations_config, load_correlations_config
from .builtin_formats import get_builtin_formats, get_builtin_format

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


def _apply_max_bytes(data: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """Truncate results list to fit within max_bytes budget."""
    serialized = json.dumps(data, default=str)
    if len(serialized.encode("utf-8")) <= max_bytes:
        return data

    # Binary search for the right number of results to keep
    results_key = None
    for key in (
        "results",
        "entries",
        "timeline",
        "thread_ids",
        "bottlenecks",
        "errors",
        "warnings",
    ):
        if key in data and isinstance(data[key], list):
            results_key = key
            break

    if results_key is None:
        return data

    original_count = len(data[results_key])
    lo, hi = 0, original_count
    best = 0

    while lo <= hi:
        mid = (lo + hi) // 2
        trial = dict(data)
        trial[results_key] = data[results_key][:mid]
        # Include truncation metadata in size estimate (it will be in final output)
        trial["truncated"] = True
        trial["truncated_at"] = mid
        trial["original_count"] = original_count
        trial_size = len(json.dumps(trial, default=str).encode("utf-8"))
        if trial_size <= max_bytes:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    data[results_key] = data[results_key][:best]
    data["truncated"] = True
    data["truncated_at"] = best
    data["original_count"] = original_count
    # Update summary.returned if present so LLMs see consistent counts
    if "summary" in data and isinstance(data["summary"], dict):
        data["summary"]["returned"] = best
    return data


def time_filter_options(f):
    """Add --last, --after, --before to a command."""
    f = click.option(
        "--last", "last_duration", help="Only entries in last N duration (e.g., 30m, 2h)"
    )(f)
    f = click.option(
        "--after", help="Only entries after this time (ISO8601 or relative: -1h, -30m)"
    )(f)
    f = click.option(
        "--before", help="Only entries before this time (ISO8601 or relative: -1h, -30m)"
    )(f)
    return f


def _resolve_time_filters(
    last_duration: Optional[str], after: Optional[str], before: Optional[str]
) -> tuple:
    """Resolve time filter options into (time_start, time_end) ISO strings.

    Supports relative time with '-' prefix: --after=-1h --before=-30m
    means "between 1 hour ago and 30 minutes ago".
    """
    from . import investigate as inv_mod

    if last_duration:
        tr = inv_mod._build_time_range(last=last_duration)
        return (tr.get("start") if tr else None, tr.get("end") if tr else None)

    time_start = None
    time_end = None
    if after:
        time_start = _parse_time_arg(after, "--after")
    if before:
        time_end = _parse_time_arg(before, "--before")
    return (time_start, time_end)


def _parse_time_arg(value: str, flag_name: str) -> str:
    """Parse a time argument, supporting both ISO8601 and relative durations.

    Relative format: -30m, -2h, -1d (dash prefix + duration)
    """
    if value.startswith("-"):
        # Relative time: subtract duration from now
        try:
            delta = _parse_duration(value[1:])
            from datetime import timezone

            return (datetime.now(timezone.utc) - delta).isoformat()
        except ValueError:
            _error_json(
                f"Invalid relative duration for {flag_name}: {value}. "
                f"Use format like '-30m', '-2h', '-1d'"
            )
    else:
        # Absolute ISO8601 timestamp
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            _error_json(f"Invalid timestamp format for {flag_name}: {value}")


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
@click.option("--level", help="Filter by log level (comma-separated: ERROR,WARN)")
@click.option("--exclude-level", help="Exclude log levels (comma-separated)")
@click.option("--query", help="Regex pattern to match in message")
@click.option("--exclude-query", help="Regex pattern to exclude matching entries")
@click.option("--thread", help="Filter by thread ID (comma-separated for multi)")
@click.option("--correlation", help="Filter by correlation ID (comma-separated)")
@click.option("--trace", help="Filter by trace ID (comma-separated)")
@click.option("--service", help="Filter by service name (comma-separated)")
@time_filter_options
@click.option("--limit", type=int, help="Limit number of results (first N)")
@click.option("--head", "head_n", type=int, help="Alias for --limit")
@click.option("--tail", "tail_n", type=int, help="Return last N matches by timestamp")
@click.option("--context", type=int, default=0, help="Include N context lines")
@click.option("--fields", help="Comma-separated fields to include in output")
@click.option("--include-raw/--no-raw", default=True, help="Include raw log line")
@click.option("--aggregate/--no-aggregate", default=True, help="Include aggregations")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes (truncates)")
@click.option("--count-only", is_flag=True, help="Return only match count, no results")
@click.option("--offset", type=int, default=0, help="Skip first N results (for pagination)")
@click.option(
    "--compact", is_flag=True, help="Use short field names (ts/lv/msg/src/svc/th/cid/trc)"
)
@click.option("--metadata-only", is_flag=True, help="Return aggregations only, no results array")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def search(
    files: tuple,
    level: Optional[str],
    exclude_level: Optional[str],
    query: Optional[str],
    exclude_query: Optional[str],
    thread: Optional[str],
    correlation: Optional[str],
    trace: Optional[str],
    service: Optional[str],
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    limit: Optional[int],
    head_n: Optional[int],
    tail_n: Optional[int],
    context: int,
    fields: Optional[str],
    include_raw: bool,
    aggregate: bool,
    max_bytes: Optional[int],
    count_only: bool,
    offset: int,
    compact: bool,
    metadata_only: bool,
    pretty: bool,
):
    """
    Search logs with full results - no truncation.

    Returns complete search results with metadata.
    Use --limit to restrict results if needed.

    Example:
        logler llm search app.log --level ERROR,WARN --query "timeout"
        logler llm search app.log --exclude-level DEBUG --tail 20
        logler llm search app.log --service api --last 1h
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        # Resolve time filters → push to Rust
        time_start, time_end = _resolve_time_filters(last_duration, after, before)

        # --head is alias for --limit
        effective_limit = limit or head_n

        # When using offset, we need to fetch offset + limit from Rust
        # so we have enough results to skip the first `offset` entries
        backend_limit = effective_limit
        if offset > 0 and effective_limit:
            backend_limit = effective_limit + offset

        # Parse fields list
        field_list = [f.strip() for f in fields.split(",")] if fields else None

        # Call search — time filtering now happens in Rust
        result = investigate.search(
            files=file_list,
            query=query,
            level=level,
            exclude_level=exclude_level,
            exclude_query=exclude_query,
            thread_id=thread,
            correlation_id=correlation,
            trace_id=trace,
            service_name=service,
            limit=backend_limit,
            tail=tail_n,
            time_start=time_start,
            time_end=time_end,
            context_lines=context,
            output_format="full",
            fields=field_list,
        )

        # Build LLM-optimized output
        results = result.get("results", [])
        total_matches = result.get("total_matches", len(results))

        # --count-only: return just the count, no results
        if count_only:
            output: Dict[str, Any] = {
                "total_matches": total_matches,
                "files_searched": len(file_list),
            }
            _output_json(output, pretty)
            sys.exit(EXIT_SUCCESS if total_matches > 0 else EXIT_NO_RESULTS)
            return

        # Transform results
        output_results = []
        for item in results:
            entry = item.get("entry", {})

            if compact:
                out_entry: Dict[str, Any] = {
                    "ln": entry.get("line_number"),
                    "ts": entry.get("timestamp"),
                    "lv": entry.get("level"),
                    "msg": entry.get("message"),
                }
                if entry.get("file"):
                    out_entry["src"] = Path(entry["file"]).name
                if entry.get("thread_id"):
                    out_entry["th"] = entry["thread_id"]
                if entry.get("correlation_id"):
                    out_entry["cid"] = entry["correlation_id"]
                if entry.get("trace_id"):
                    out_entry["trc"] = entry["trace_id"]
                if entry.get("span_id"):
                    out_entry["sid"] = entry["span_id"]
                if entry.get("service_name"):
                    out_entry["svc"] = entry["service_name"]
            else:
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
                if entry.get("service_name"):
                    out_entry["service_name"] = entry["service_name"]
                if include_raw and entry.get("raw"):
                    out_entry["raw"] = entry["raw"]

            # Context if requested
            if context > 0:
                if item.get("context_before"):
                    out_entry["context_before"] = item["context_before"]
                if item.get("context_after"):
                    out_entry["context_after"] = item["context_after"]

            # Field projection at CLI level
            if field_list:
                out_entry = {k: v for k, v in out_entry.items() if k in field_list}

            output_results.append(out_entry)

        # Apply offset for pagination
        if offset > 0:
            output_results = output_results[offset:]

        # Trim back to effective_limit after offset (we fetched offset+limit from backend)
        if effective_limit and len(output_results) > effective_limit:
            output_results = output_results[:effective_limit]

        has_more = (offset + len(output_results)) < total_matches

        # Build aggregations from ALL results (before offset) for metadata-only
        agg_by_level: Dict[str, int] = defaultdict(int)
        agg_by_thread: Dict[str, int] = defaultdict(int)
        agg_by_service: Dict[str, int] = defaultdict(int)

        if aggregate or metadata_only:
            for item in results:
                entry = item.get("entry", {})
                if entry.get("level"):
                    agg_by_level[entry["level"]] += 1
                if entry.get("thread_id"):
                    agg_by_thread[entry["thread_id"]] += 1
                if entry.get("service_name"):
                    agg_by_service[entry["service_name"]] += 1

        # --metadata-only: aggregations without results array
        if metadata_only:
            output = {
                "query": {
                    "files": file_list,
                    "level": level,
                    "exclude_level": exclude_level,
                    "pattern": query,
                    "service": service,
                },
                "summary": {
                    "total_matches": total_matches,
                    "files_searched": len(file_list),
                },
                "aggregations": {
                    "by_level": dict(agg_by_level),
                    "by_thread": dict(agg_by_thread) if agg_by_thread else None,
                    "by_service": dict(agg_by_service) if agg_by_service else None,
                },
            }
            _output_json(output, pretty)
            sys.exit(EXIT_SUCCESS if total_matches > 0 else EXIT_NO_RESULTS)
            return

        output = {
            "query": {
                "files": file_list,
                "level": level,
                "exclude_level": exclude_level,
                "pattern": query,
                "exclude_query": exclude_query,
                "thread": thread,
                "correlation": correlation,
                "trace": trace,
                "service": service,
            },
            "summary": {
                "total_matches": total_matches,
                "returned": len(output_results),
                "files_searched": len(file_list),
                "offset": offset,
                "has_more": has_more,
            },
            "results": output_results,
        }

        # Add aggregations if requested
        if aggregate and output_results:
            output["aggregations"] = {
                "by_level": dict(agg_by_level),
                "by_thread": dict(agg_by_thread) if agg_by_thread else None,
            }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

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
@time_filter_options
@click.option(
    "--type",
    "id_type",
    type=click.Choice(["thread", "correlation", "trace", "service", "all"]),
    default="all",
    help="Type of IDs to extract",
)
@click.option("--limit", type=int, help="Limit number of IDs per category")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def ids(
    files: tuple,
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    id_type: str,
    limit: Optional[int],
    max_bytes: Optional[int],
    pretty: bool,
):
    """
    Discover all unique IDs in log files.

    Returns thread IDs, correlation IDs, trace IDs, and service names
    with counts and first/last seen timestamps.

    Example:
        logler llm ids app.log --last 5m
        logler llm ids app.log --type thread --limit 10
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        time_start, time_end = _resolve_time_filters(last_duration, after, before)

        result = investigate.extract_ids(
            files=file_list,
            time_start=time_start,
            time_end=time_end,
        )

        # Filter by type
        if id_type != "all":
            key_map = {
                "thread": "thread_ids",
                "correlation": "correlation_ids",
                "trace": "trace_ids",
                "service": "services",
            }
            keep_key = key_map[id_type]
            for key in ["thread_ids", "correlation_ids", "trace_ids", "services"]:
                if key != keep_key:
                    result[key] = []

        # Apply limit
        if limit:
            for key in ["thread_ids", "correlation_ids", "trace_ids", "services"]:
                if key in result:
                    result[key] = result[key][:limit]

        if max_bytes:
            result = _apply_max_bytes(result, max_bytes)

        _output_json(result, pretty)
        sys.exit(EXIT_SUCCESS)

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
@click.option("--level", help="Filter by log level (comma-separated: ERROR,WARN)")
@click.option("--exclude-level", help="Exclude log levels (comma-separated)")
@click.option("--service", help="Filter by service name (comma-separated)")
@time_filter_options
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def sample(
    files: tuple,
    strategy: str,
    size: int,
    level: Optional[str],
    exclude_level: Optional[str],
    service: Optional[str],
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    pretty: bool,
):
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

        # Resolve time filters
        time_start, time_end = _resolve_time_filters(last_duration, after, before)

        result = investigate.smart_sample(
            files=file_list, level=level, strategy=strategy, sample_size=size
        )

        # Post-filter by exclude_level, service, and time
        entries = result.get("samples", []) or result.get("entries", [])
        if exclude_level:
            excl_set = {level.strip().upper() for level in exclude_level.split(",")}
            entries = [e for e in entries if (e.get("level") or "").upper() not in excl_set]
        if service:
            svc_set = {s.strip() for s in service.split(",")}
            entries = [
                e
                for e in entries
                if e.get("service_name") in svc_set or e.get("service") in svc_set
            ]
        if time_start:
            entries = [e for e in entries if e.get("timestamp") and e["timestamp"] >= time_start]
        if time_end:
            entries = [e for e in entries if e.get("timestamp") and e["timestamp"] <= time_end]

        result["samples"] = entries

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

        # Transform entries (key is 'samples' from Rust, not 'entries')
        for entry in result.get("samples", []) or result.get("entries", []):
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
@time_filter_options
@click.option("--service", help="Filter by service name (comma-separated)")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def triage(
    files: tuple,
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    service: Optional[str],
    max_bytes: Optional[int],
    pretty: bool,
):
    """
    Quick severity assessment for incident response.

    Returns severity level, error rate, and log level distribution.
    Designed for rapid initial assessment during incidents.

    Example:
        logler llm triage /var/log/app/*.log --last 1h
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        # Resolve time filters
        time_start, time_end = _resolve_time_filters(last_duration, after, before)

        # Get summary stats using search
        result = investigate.search(
            files=file_list,
            service_name=service,
            time_start=time_start,
            time_end=time_end,
            output_format="summary",
        )

        total = result.get("total_matches", 0)
        levels = result.get("log_levels", {})
        error_count = levels.get("ERROR", 0) + levels.get("FATAL", 0)
        error_rate = error_count / total if total > 0 else 0

        # Determine severity
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

        # Build suggested actions based on error rate
        suggested_actions = []
        if error_rate > 0.05:
            suggested_actions.append(
                {
                    "action": "investigate",
                    "reason": "High error rate detected - investigate most common errors",
                }
            )
        if error_count > 0:
            suggested_actions.append(
                {
                    "action": "search_errors",
                    "reason": "Run: logler llm search --level ERROR to find error details",
                }
            )

        output = {
            "assessment": {
                "severity": severity,
                "confidence": confidence,
                "summary": f"Error rate: {error_rate:.1%}, {error_count} errors in {total} entries",
            },
            "metrics": {
                "error_rate": round(error_rate, 4),
                "error_count": error_count,
                "total_entries": total,
                "log_levels": levels,
            },
            "suggested_actions": suggested_actions,
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

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
@time_filter_options
@click.option("--max-bytes", type=int, help="Maximum output size in bytes (truncates)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def correlate(
    identifier: str,
    files: tuple,
    id_type: str,
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    max_bytes: Optional[int],
    pretty: bool,
):
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

        # Resolve time filters
        time_start, time_end = _resolve_time_filters(last_duration, after, before)

        result = investigate.follow_thread(
            files=file_list, thread_id=thread_id, correlation_id=correlation_id, trace_id=trace_id
        )

        entries = result.get("entries", [])

        # Apply time filters to entries
        if time_start:
            entries = [e for e in entries if e.get("timestamp") and e["timestamp"] >= time_start]
        if time_end:
            entries = [e for e in entries if e.get("timestamp") and e["timestamp"] <= time_end]

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

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

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
@time_filter_options
@click.option("--max-bytes", type=int, help="Maximum output size in bytes (truncates)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def hierarchy(
    identifier: str,
    files: tuple,
    max_depth: Optional[int],
    min_confidence: float,
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    max_bytes: Optional[int],
    pretty: bool,
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
        if max_bytes:
            result = _apply_max_bytes(result, max_bytes)

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
                                        group_values[f"group_{j + 1}"][grp] += 1

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
@click.option("--level", help="Filter by level (comma-separated: ERROR,WARN)")
@click.option("--exclude-level", help="Exclude log levels (comma-separated)")
@click.option("--query", help="Filter by pattern")
@click.option("--exclude-query", help="Regex pattern to exclude matching entries")
@click.option("--service", help="Filter by service name")
@click.option("--fields", help="Comma-separated fields to include")
@click.option("--compact", is_flag=True, help="Minimal JSON (short keys)")
@click.option("--limit", type=int, help="Maximum entries to emit")
@click.option("--tail", "tail_n", type=int, help="Emit last N entries by timestamp")
@time_filter_options
def emit(
    files: tuple,
    level: Optional[str],
    exclude_level: Optional[str],
    query: Optional[str],
    exclude_query: Optional[str],
    service: Optional[str],
    fields: Optional[str],
    compact: bool,
    limit: Optional[int],
    tail_n: Optional[int],
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
):
    """
    Stream parsed entries as JSONL for processing.

    Outputs one JSON object per line, suitable for piping
    to other tools or processing large files.

    Example:
        logler llm emit app.log --level ERROR --last 1h --limit 100
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

        # Parse level filters (comma-separated)
        level_set = None
        if level:
            level_set = {lvl.strip().upper() for lvl in level.split(",") if lvl.strip()}
        exclude_level_set = None
        if exclude_level:
            exclude_level_set = {
                lvl.strip().upper() for lvl in exclude_level.split(",") if lvl.strip()
            }

        # Time filters
        time_start_str, time_end_str = _resolve_time_filters(last_duration, after, before)
        time_start_dt = datetime.fromisoformat(time_start_str) if time_start_str else None
        time_end_dt = datetime.fromisoformat(time_end_str) if time_end_str else None

        # Compile query regex if provided
        query_regex = None
        if query:
            try:
                query_regex = safe_compile(query, re.IGNORECASE)
            except (re.error, RegexTimeoutError, RegexPatternTooLongError) as e:
                _error_json(f"Invalid regex pattern: {e}")

        exclude_regex = None
        if exclude_query:
            try:
                exclude_regex = safe_compile(exclude_query, re.IGNORECASE)
            except (re.error, RegexTimeoutError, RegexPatternTooLongError) as e:
                _error_json(f"Invalid exclude regex: {e}")

        # Collect entries (for tail mode we need to buffer)
        emitted = 0
        buffer = [] if tail_n else None

        for file_path in file_list:
            try:
                with open(file_path, "r", errors="replace") as f:
                    for i, line in enumerate(f):
                        line = line.rstrip()
                        if not line:
                            continue

                        entry = parser.parse_line(i + 1, line)
                        entry_level = str(entry.level).upper() if entry.level else None

                        # Apply level filter (comma-separated)
                        if level_set and entry_level not in level_set:
                            continue
                        if exclude_level_set and entry_level in exclude_level_set:
                            continue

                        # Apply service filter
                        if service:
                            svc = getattr(entry, "service_name", None)
                            if not svc or svc != service:
                                continue

                        # Apply time filter
                        if time_start_dt or time_end_dt:
                            ts = entry.timestamp
                            if ts:
                                if isinstance(ts, str):
                                    try:
                                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                    except (ValueError, TypeError):
                                        ts = None
                                if ts:
                                    if time_start_dt and ts < time_start_dt:
                                        continue
                                    if time_end_dt and ts > time_end_dt:
                                        continue

                        # Apply query filter
                        if query_regex:
                            if not query_regex.search(entry.message or ""):
                                if not query_regex.search(line):
                                    continue

                        # Apply exclude query filter
                        if exclude_regex:
                            if exclude_regex.search(entry.message or "") or exclude_regex.search(
                                line
                            ):
                                continue

                        # Build output
                        if compact:
                            out = {
                                "ln": i + 1,
                                "ts": str(entry.timestamp) if entry.timestamp else None,
                                "lv": entry_level,
                                "msg": entry.message,
                            }
                            if len(file_list) > 1:
                                out["src"] = Path(file_path).name
                            if entry.thread_id:
                                out["th"] = entry.thread_id
                        else:
                            out = {
                                "file": file_path,
                                "line_number": i + 1,
                                "timestamp": str(entry.timestamp) if entry.timestamp else None,
                                "level": entry_level,
                                "message": entry.message,
                            }
                            if entry.thread_id:
                                out["thread_id"] = entry.thread_id
                            if entry.correlation_id:
                                out["correlation_id"] = entry.correlation_id
                            if hasattr(entry, "service_name") and entry.service_name:
                                out["service_name"] = entry.service_name

                        # Filter fields if specified
                        if include_fields:
                            out = {k: v for k, v in out.items() if k in include_fields}

                        if buffer is not None:
                            buffer.append(out)
                        else:
                            click.echo(json.dumps(out, default=str))
                            emitted += 1
                            if limit and emitted >= limit:
                                break

            except FileNotFoundError:
                pass
            except PermissionError:
                pass

            if limit and emitted >= limit and buffer is None:
                break

        # Handle tail mode
        if buffer is not None:
            tail_entries = buffer[-tail_n:] if tail_n else buffer
            for out in tail_entries:
                click.echo(json.dumps(out, default=str))

        sys.exit(EXIT_SUCCESS)

    except Exception as e:
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


# =============================================================================
# SQL Query Command - High value for LLM log analysis
# =============================================================================


@llm.command()
@click.argument("query", required=False)
@click.option("--files", "-f", multiple=True, help="Files to load (supports globs)")
@click.option("--stdin", is_flag=True, help="Read SQL query from stdin")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def sql(query: Optional[str], files: tuple, stdin: bool, pretty: bool):
    """
    Execute SQL queries on log files using DuckDB.

    Loads log files into a 'logs' table with columns:
    - line_number, timestamp, level, message, thread_id,
    - correlation_id, trace_id, span_id, file, raw

    Supports all DuckDB SQL including:
    - Aggregations (COUNT, GROUP BY, HAVING)
    - Window functions
    - CTEs (WITH clauses)
    - JOINs (if loading multiple file groups)

    Examples:
        # Count errors by level
        logler llm sql "SELECT level, COUNT(*) FROM logs GROUP BY level" -f "*.log"

        # Find top error messages
        logler llm sql "SELECT message, COUNT(*) as cnt FROM logs WHERE level='ERROR'
                        GROUP BY message ORDER BY cnt DESC LIMIT 10" -f app.log

        # Query from stdin
        echo "SELECT * FROM logs LIMIT 5" | logler llm sql --stdin -f "*.log"

        # Complex analysis
        logler llm sql "
            WITH error_threads AS (
                SELECT DISTINCT thread_id FROM logs WHERE level = 'ERROR'
            )
            SELECT l.* FROM logs l
            JOIN error_threads e ON l.thread_id = e.thread_id
            ORDER BY l.timestamp
        " -f "*.log"
    """
    import duckdb

    try:
        # Get query from argument or stdin
        if stdin:
            import sys as _sys

            query = _sys.stdin.read().strip()
        elif not query:
            _error_json("SQL query required. Provide as argument or use --stdin.")

        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

        # Parse log files
        from .parser import LogParser

        parser = LogParser()
        entries = []

        for file_path in file_list:
            try:
                with open(file_path, "r", errors="replace") as f:
                    for i, line in enumerate(f):
                        line = line.rstrip()
                        if not line:
                            continue

                        entry = parser.parse_line(i + 1, line)
                        entries.append(
                            {
                                "line_number": i + 1,
                                "timestamp": str(entry.timestamp) if entry.timestamp else None,
                                "level": str(entry.level).upper() if entry.level else None,
                                "message": entry.message,
                                "thread_id": entry.thread_id,
                                "correlation_id": entry.correlation_id,
                                "trace_id": getattr(entry, "trace_id", None),
                                "span_id": getattr(entry, "span_id", None),
                                "file": file_path,
                                "raw": line,
                            }
                        )
            except (FileNotFoundError, PermissionError) as e:
                _error_json(f"Cannot read file {file_path}: {e}")

        if not entries:
            _output_json(
                {
                    "query": query,
                    "files": file_list,
                    "total_entries": 0,
                    "results": [],
                    "error": "No log entries found",
                },
                pretty,
            )
            sys.exit(EXIT_NO_RESULTS)

        # Create DuckDB connection and load data
        conn = duckdb.connect(":memory:")

        # Create table from entries
        conn.execute(
            """
            CREATE TABLE logs (
                line_number INTEGER,
                timestamp VARCHAR,
                level VARCHAR,
                message VARCHAR,
                thread_id VARCHAR,
                correlation_id VARCHAR,
                trace_id VARCHAR,
                span_id VARCHAR,
                file VARCHAR,
                raw VARCHAR
            )
        """
        )

        # Insert entries
        conn.executemany(
            """
            INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    e["line_number"],
                    e["timestamp"],
                    e["level"],
                    e["message"],
                    e["thread_id"],
                    e["correlation_id"],
                    e["trace_id"],
                    e["span_id"],
                    e["file"],
                    e["raw"],
                )
                for e in entries
            ],
        )

        # Execute the user's query
        try:
            result = conn.execute(query).fetchall()
            columns = [desc[0] for desc in conn.description]
        except duckdb.Error as e:
            _error_json(f"SQL error: {e}", EXIT_USER_ERROR)

        # Convert results to list of dicts
        rows = [dict(zip(columns, row)) for row in result]

        output = {
            "query": query,
            "files": file_list,
            "total_entries": len(entries),
            "columns": columns,
            "row_count": len(rows),
            "results": rows,
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if rows else EXIT_NO_RESULTS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


# =============================================================================
# Bottleneck Analysis Command
# =============================================================================


@llm.command()
@click.argument("identifier")
@click.option("--files", "-f", multiple=True, help="Files to search (supports globs)")
@click.option("--threshold-ms", type=int, default=100, help="Minimum duration to consider (ms)")
@click.option("--top-n", type=int, default=10, help="Number of top bottlenecks to return")
@time_filter_options
@click.option("--max-bytes", type=int, help="Maximum output size in bytes (truncates)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def bottleneck(
    identifier: str,
    files: tuple,
    threshold_ms: int,
    top_n: int,
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    max_bytes: Optional[int],
    pretty: bool,
):
    """
    Analyze performance bottlenecks for a trace/correlation ID.

    Identifies the slowest operations and shows where time is spent.

    Example:
        logler llm bottleneck trace-abc123 --files "*.log" --top-n 5
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

        # Get hierarchy to analyze
        hierarchy = investigate.follow_thread_hierarchy(
            files=file_list,
            root_identifier=identifier,
        )

        if not hierarchy.get("roots"):
            _output_json(
                {
                    "identifier": identifier,
                    "error": "No hierarchy found for identifier",
                },
                pretty,
            )
            sys.exit(EXIT_NO_RESULTS)

        # Collect all nodes with durations
        nodes_with_duration = []

        def collect_nodes(node: Dict[str, Any], path: List[str]):
            node_id = node.get("id", "unknown")
            duration = node.get("duration_ms", 0) or 0
            current_path = path + [node_id]

            if duration >= threshold_ms:
                nodes_with_duration.append(
                    {
                        "node_id": node_id,
                        "name": node.get("name") or node.get("operation_name"),
                        "duration_ms": duration,
                        "depth": node.get("depth", 0),
                        "entry_count": node.get("entry_count", 0),
                        "error_count": node.get("error_count", 0),
                        "path": current_path,
                        "children_count": len(node.get("children", [])),
                    }
                )

            for child in node.get("children", []):
                collect_nodes(child, current_path)

        for root in hierarchy.get("roots", []):
            collect_nodes(root, [])

        # Sort by duration descending
        nodes_with_duration.sort(key=lambda x: -x["duration_ms"])
        top_bottlenecks = nodes_with_duration[:top_n]

        # Calculate percentages
        total_duration = hierarchy.get("total_duration_ms", 0) or 1
        for node in top_bottlenecks:
            node["percentage"] = round(node["duration_ms"] / total_duration * 100, 1)

        output = {
            "identifier": identifier,
            "total_duration_ms": hierarchy.get("total_duration_ms"),
            "total_nodes": hierarchy.get("total_nodes", 0),
            "analysis": {
                "threshold_ms": threshold_ms,
                "nodes_above_threshold": len(nodes_with_duration),
            },
            "bottlenecks": top_bottlenecks,
            "hierarchy_bottleneck": hierarchy.get("bottleneck"),
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


# =============================================================================
# Context Command
# =============================================================================


@llm.command()
@click.argument("file")
@click.argument("line", type=int)
@click.option("--before", "-B", type=int, default=10, help="Lines before")
@click.option("--after", "-A", type=int, default=10, help="Lines after")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def context(file: str, line: int, before: int, after: int, pretty: bool):
    """
    Get context lines around a specific log entry.

    Returns parsed entries with context, useful for understanding
    what happened before and after a specific log line.

    Example:
        logler llm context app.log 1523 --before 20 --after 10
    """
    from . import investigate

    try:
        if not Path(file).exists():
            _error_json(f"File not found: {file}")

        result = investigate.get_context(
            file=file,
            line_number=line,
            lines_before=before,
            lines_after=after,
        )

        # Transform to cleaner output
        output = {
            "file": file,
            "line_number": line,
            "context_lines": {"before": before, "after": after},
            "target": result.get("target"),
            "context_before": result.get("context_before", []),
            "context_after": result.get("context_after", []),
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


# =============================================================================
# Trace Export Command
# =============================================================================


@llm.command("export")
@click.argument("identifier")
@click.option("--files", "-f", multiple=True, help="Files to search (supports globs)")
@click.option(
    "--format",
    "export_format",
    type=click.Choice(["jaeger", "zipkin", "otlp"]),
    default="jaeger",
    help="Export format",
)
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def export_trace(identifier: str, files: tuple, export_format: str, pretty: bool):
    """
    Export traces to Jaeger/Zipkin/OTLP format.

    Converts log-based traces to standard distributed tracing formats
    that can be imported into Jaeger, Zipkin, or other tracing systems.

    Example:
        logler llm export trace-abc123 --files "*.log" --format jaeger
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

        # Get hierarchy for the trace
        hierarchy = investigate.follow_thread_hierarchy(
            files=file_list,
            root_identifier=identifier,
        )

        if not hierarchy.get("roots"):
            _output_json(
                {
                    "identifier": identifier,
                    "format": export_format,
                    "error": "No trace data found for identifier",
                },
                pretty,
            )
            sys.exit(EXIT_NO_RESULTS)

        # Convert hierarchy to spans
        spans = []

        def node_to_span(node: Dict[str, Any], parent_span_id: Optional[str] = None):
            node_id = node.get("id", "unknown")

            # Generate span ID if not present
            span_id = node.get("span_id") or f"span-{hash(node_id) & 0xFFFFFFFF:08x}"

            span = {
                "traceId": identifier.replace("trace-", "").replace("-", "")[:32].ljust(32, "0"),
                "spanId": span_id.replace("-", "")[:16].ljust(16, "0"),
                "operationName": node.get("name") or node.get("operation_name") or node_id,
                "serviceName": node.get("service_name", "unknown"),
                "startTime": node.get("start_time"),
                "duration": (node.get("duration_ms", 0) or 0) * 1000,  # Convert to microseconds
                "tags": [],
                "logs": [],
            }

            if parent_span_id:
                span["parentSpanId"] = parent_span_id.replace("-", "")[:16].ljust(16, "0")

            # Add tags
            if node.get("error_count", 0) > 0:
                span["tags"].append({"key": "error", "value": True})

            if node.get("entry_count"):
                span["tags"].append({"key": "log.entry_count", "value": node["entry_count"]})

            spans.append(span)

            for child in node.get("children", []):
                node_to_span(child, span_id)

        for root in hierarchy.get("roots", []):
            node_to_span(root)

        # Format output based on target format
        if export_format == "jaeger":
            trace_output = {
                "data": [
                    {
                        "traceID": identifier.replace("trace-", "")
                        .replace("-", "")[:32]
                        .ljust(32, "0"),
                        "spans": spans,
                        "processes": {
                            "p1": {
                                "serviceName": "logler-export",
                                "tags": [],
                            }
                        },
                    }
                ],
                "total": 1,
                "limit": 0,
                "offset": 0,
                "errors": None,
            }
        elif export_format == "zipkin":
            trace_output = [
                {
                    "traceId": span["traceId"],
                    "id": span["spanId"],
                    "name": span["operationName"],
                    "timestamp": span.get("startTime"),
                    "duration": span["duration"],
                    "localEndpoint": {"serviceName": span.get("serviceName", "unknown")},
                    "parentId": span.get("parentSpanId"),
                    "tags": {t["key"]: str(t["value"]) for t in span.get("tags", [])},
                }
                for span in spans
            ]
        else:  # otlp
            trace_output = {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": [
                                {"key": "service.name", "value": {"stringValue": "logler-export"}}
                            ]
                        },
                        "scopeSpans": [
                            {
                                "scope": {"name": "logler"},
                                "spans": [
                                    {
                                        "traceId": span["traceId"],
                                        "spanId": span["spanId"],
                                        "name": span["operationName"],
                                        "startTimeUnixNano": span.get("startTime"),
                                        "endTimeUnixNano": None,
                                        "parentSpanId": span.get("parentSpanId"),
                                    }
                                    for span in spans
                                ],
                            }
                        ],
                    }
                ]
            }

        output = {
            "identifier": identifier,
            "format": export_format,
            "span_count": len(spans),
            "export": trace_output,
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


# =============================================================================
# Compare Command - Compare two requests side by side
# =============================================================================


@llm.command()
@click.argument("id1")
@click.argument("id2")
@click.option("--files", "-f", multiple=True, help="Files to search (supports globs)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def compare(id1: str, id2: str, files: tuple, pretty: bool):
    """
    Compare two requests/traces side by side.

    Shows differences between a failed and successful request,
    helping identify what went wrong.

    Example:
        logler llm compare req-001 req-003 --files "*.log"
    """
    from . import investigate

    try:
        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

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
                        "description": f"{id1} has {analysis1['entry_count']} entries, {id2} has {analysis2['entry_count']}",
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
            "summary": f"{id1}: {analysis1.get('outcome', 'not found')}, {id2}: {analysis2.get('outcome', 'not found')}",
        }

        # Add recommendation if one failed and one succeeded
        if analysis1.get("outcome") == "error" and analysis2.get("outcome") == "success":
            if analysis1.get("errors"):
                output["recommendation"] = (
                    f"Investigate error in {id1}: {analysis1['errors'][0].get('message', 'Unknown error')}"
                )
        elif analysis2.get("outcome") == "error" and analysis1.get("outcome") == "success":
            if analysis2.get("errors"):
                output["recommendation"] = (
                    f"Investigate error in {id2}: {analysis2['errors'][0].get('message', 'Unknown error')}"
                )

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


# =============================================================================
# Summarize Command - Quick text summary for LLMs
# =============================================================================


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option(
    "--focus",
    type=click.Choice(["errors", "all", "warnings"]),
    default="errors",
    help="What to focus on",
)
@click.option("--service", help="Filter by service name (comma-separated)")
@time_filter_options
@click.option("--max-bytes", type=int, help="Maximum output size in bytes (truncates)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def summarize(
    files: tuple,
    focus: str,
    service: Optional[str],
    last_duration: Optional[str],
    after: Optional[str],
    before: Optional[str],
    max_bytes: Optional[int],
    pretty: bool,
):
    """
    Generate a concise summary of log contents.

    Returns structured data with a human-readable summary,
    perfect for LLM context.

    Example:
        logler llm summarize app.log --focus errors
    """
    from .parser import LogParser

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        # Resolve time and service filters
        time_start, time_end = _resolve_time_filters(last_duration, after, before)
        svc_set = {s.strip() for s in service.split(",")} if service else None

        parser = LogParser()

        # Collect stats
        total = 0
        by_level = defaultdict(int)
        errors = []
        warnings = []
        unique_errors = defaultdict(int)
        time_range = {"start": None, "end": None}
        correlation_ids = set()

        for file_path in file_list:
            try:
                with open(file_path, "r", errors="replace") as f:
                    for i, line in enumerate(f):
                        line = line.rstrip()
                        if not line:
                            continue

                        entry = parser.parse_line(i + 1, line)

                        # Apply time filters
                        if time_start and entry.timestamp:
                            if str(entry.timestamp) < time_start:
                                continue
                        if time_end and entry.timestamp:
                            if str(entry.timestamp) > time_end:
                                continue

                        # Apply service filter
                        if svc_set:
                            entry_svc = getattr(entry, "service_name", None) or getattr(
                                entry, "service", None
                            )
                            if entry_svc not in svc_set:
                                continue

                        total += 1

                        level = str(entry.level).upper() if entry.level else "UNKNOWN"
                        by_level[level] += 1

                        if entry.timestamp:
                            ts_str = str(entry.timestamp)
                            if not time_range["start"] or ts_str < time_range["start"]:
                                time_range["start"] = ts_str
                            if not time_range["end"] or ts_str > time_range["end"]:
                                time_range["end"] = ts_str

                        if entry.correlation_id:
                            correlation_ids.add(entry.correlation_id)

                        if level == "ERROR":
                            msg = entry.message or line[:100]
                            unique_errors[msg] += 1
                            if len(errors) < 10:
                                errors.append(
                                    {
                                        "line": i + 1,
                                        "message": msg,
                                        "correlation_id": entry.correlation_id,
                                    }
                                )
                        elif level in ["WARN", "WARNING"]:
                            if len(warnings) < 5:
                                warnings.append(
                                    {
                                        "line": i + 1,
                                        "message": entry.message or line[:100],
                                    }
                                )

            except (FileNotFoundError, PermissionError):
                pass

        # Build human-readable summary
        error_count = by_level.get("ERROR", 0)
        warn_count = by_level.get("WARN", 0) + by_level.get("WARNING", 0)

        if error_count == 0 and warn_count == 0:
            summary_text = f"Clean: {total} log entries, no errors or warnings"
        elif error_count == 0:
            summary_text = f"{total} entries with {warn_count} warnings, no errors"
        else:
            error_types = len(unique_errors)
            summary_text = f"{total} entries, {error_count} errors ({error_types} unique), {warn_count} warnings"

            # Add top error
            if unique_errors:
                top_error = max(unique_errors.items(), key=lambda x: x[1])
                summary_text += f'. Top error: "{top_error[0][:50]}" ({top_error[1]}x)'

        output = {
            "summary": summary_text,
            "stats": {
                "total_entries": total,
                "by_level": dict(by_level),
                "unique_correlation_ids": len(correlation_ids),
                "time_range": time_range if time_range["start"] else None,
            },
            "errors": errors if focus in ["errors", "all"] else [],
            "warnings": warnings if focus in ["warnings", "all"] else [],
            "unique_error_messages": dict(unique_errors) if unique_errors else {},
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if total > 0 else EXIT_NO_RESULTS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


# =============================================================================
# Format Management Commands (M1.3)
# =============================================================================


@llm.group()
def format():
    """
    Manage log format definitions.

    List built-in formats, test regex patterns against log files,
    and validate .logler/formats.yaml config files.
    """
    pass


@format.command("list")
@click.option("--builtin/--no-builtin", default=True, help="Include built-in formats")
@click.option("--config-dir", help="Directory to search for .logler/formats.yaml")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def format_list(builtin: bool, config_dir: Optional[str], pretty: bool):
    """List available log format definitions.

    Shows built-in formats and any user-defined formats from
    .logler/formats.yaml config files.
    """
    try:
        output: Dict[str, Any] = {
            "builtin_formats": {},
            "user_formats": {},
            "config_path": None,
        }

        # Built-in formats
        if builtin:
            for name, fmt in get_builtin_formats().items():
                output["builtin_formats"][name] = {
                    "regex": fmt.regex,
                    "timestamp_format": fmt.timestamp_format,
                    "file_patterns": fmt.file_patterns,
                }

        # User config
        search_dir = Path(config_dir) if config_dir else Path.cwd()
        config_path = find_config(search_dir)
        if config_path:
            output["config_path"] = str(config_path)
            try:
                config = load_config(config_path)
                for name, fmt in config.formats.items():
                    output["user_formats"][name] = {
                        "regex": fmt.regex,
                        "timestamp_format": fmt.timestamp_format,
                        "file_patterns": fmt.file_patterns,
                    }
            except Exception as e:
                output["config_error"] = str(e)

        has_any = output["builtin_formats"] or output["user_formats"]
        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if has_any else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@format.command("test")
@click.option("--files", "-f", multiple=True, required=True, help="Log files to test")
@click.option("--regex", "-r", help="Regex pattern to test (with named groups)")
@click.option("--name", "-n", help="Built-in or user format name to test")
@click.option("--limit", default=20, help="Max lines to show")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def format_test(
    files: tuple,
    regex: Optional[str],
    name: Optional[str],
    limit: int,
    pretty: bool,
):
    """Test a format regex against log files.

    Provide either --regex with a pattern, or --name for a built-in/user format.
    Shows which lines match and the extracted named groups.
    """
    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {files}")

        # Resolve the regex to test
        test_regex = None
        format_source = None

        if regex:
            test_regex = regex
            format_source = "inline"
        elif name:
            # Try built-in first
            fmt = get_builtin_format(name)
            if fmt:
                test_regex = fmt.regex
                format_source = "builtin"
            else:
                # Try user config
                config_path = find_config(Path(file_list[0]).parent)
                if config_path:
                    config = load_config(config_path)
                    if name in config.formats:
                        test_regex = config.formats[name].regex
                        format_source = "user_config"

            if not test_regex:
                _error_json(f"Format '{name}' not found in built-in or user config")
        else:
            _error_json("Provide either --regex or --name")

        # Compile the regex
        try:
            compiled = safe_compile(test_regex)
        except (re.error, RegexTimeoutError, RegexPatternTooLongError) as e:
            _error_json(f"Invalid regex: {e}")

        if not compiled.groupindex:
            _error_json("Regex must have at least one named group (?P<name>...)")

        # Test against files
        results = []
        total_lines = 0
        matched_lines = 0

        for file_path in file_list:
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        line = line.rstrip("\n\r")
                        if not line:
                            continue
                        total_lines += 1
                        match = compiled.match(line)
                        if match:
                            matched_lines += 1
                            if len(results) < limit:
                                results.append(
                                    {
                                        "file": file_path,
                                        "line_number": i,
                                        "matched": True,
                                        "groups": match.groupdict(),
                                        "raw": line[:500],
                                    }
                                )
                        elif len(results) < limit and total_lines <= limit * 2:
                            results.append(
                                {
                                    "file": file_path,
                                    "line_number": i,
                                    "matched": False,
                                    "groups": {},
                                    "raw": line[:500],
                                }
                            )
            except OSError as e:
                results.append(
                    {
                        "file": file_path,
                        "error": str(e),
                    }
                )

        match_rate = (matched_lines / total_lines * 100) if total_lines > 0 else 0

        output = {
            "regex": test_regex,
            "format_source": format_source,
            "named_groups": list(compiled.groupindex.keys()),
            "files_tested": file_list,
            "total_lines": total_lines,
            "matched_lines": matched_lines,
            "match_rate_percent": round(match_rate, 1),
            "results": results,
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if matched_lines > 0 else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@format.command("validate")
@click.option("--config-dir", help="Directory to search for .logler/formats.yaml")
@click.option("--regex", "-r", help="Validate a single regex pattern")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def format_validate(
    config_dir: Optional[str],
    regex: Optional[str],
    pretty: bool,
):
    """Validate format definitions.

    Without --regex, validates the .logler/formats.yaml config file.
    With --regex, validates a single regex pattern for use as a log format.
    """
    try:
        if regex:
            # Validate a single regex
            issues = []
            try:
                compiled = safe_compile(regex)
            except re.error as e:
                _output_json(
                    {
                        "valid": False,
                        "regex": regex,
                        "issues": [f"Regex compilation error: {e}"],
                    },
                    pretty,
                )
                sys.exit(EXIT_USER_ERROR)
            except (RegexTimeoutError, RegexPatternTooLongError) as e:
                _output_json(
                    {
                        "valid": False,
                        "regex": regex,
                        "issues": [f"Regex safety check failed: {e}"],
                    },
                    pretty,
                )
                sys.exit(EXIT_USER_ERROR)

            named_groups = list(compiled.groupindex.keys())
            if not named_groups:
                issues.append("Regex has no named groups. Use (?P<name>...) syntax.")

            # Check for recommended groups
            recommended = {"message", "timestamp", "level"}
            present = set(named_groups)
            missing_recommended = recommended - present
            if missing_recommended:
                issues.append(
                    f"Missing recommended groups: {', '.join(sorted(missing_recommended))}. "
                    f"Present: {', '.join(named_groups)}"
                )

            output = {
                "valid": len(issues) == 0 or all("Missing recommended" in i for i in issues),
                "regex": regex,
                "named_groups": named_groups,
                "issues": issues,
            }
            _output_json(output, pretty)
            sys.exit(EXIT_SUCCESS)

        # Validate config file
        search_dir = Path(config_dir) if config_dir else Path.cwd()
        config_path = find_config(search_dir)

        if not config_path:
            _output_json(
                {
                    "valid": False,
                    "config_path": None,
                    "issues": [f"No .logler/formats.yaml found starting from {search_dir}"],
                },
                pretty,
            )
            sys.exit(EXIT_NO_RESULTS)

        issues = []
        formats_valid = {}

        try:
            config = load_config(config_path)
        except Exception as e:
            _output_json(
                {
                    "valid": False,
                    "config_path": str(config_path),
                    "issues": [f"Config load error: {e}"],
                },
                pretty,
            )
            sys.exit(EXIT_USER_ERROR)

        for fmt_name, fmt in config.formats.items():
            fmt_issues = []
            compiled = safe_compile(fmt.regex)
            named_groups = list(compiled.groupindex.keys())

            if "message" not in named_groups:
                fmt_issues.append("Missing recommended 'message' group")
            if "timestamp" not in named_groups:
                fmt_issues.append("Missing recommended 'timestamp' group")
            if not fmt.file_patterns:
                fmt_issues.append("No file_patterns defined (format won't auto-match)")

            formats_valid[fmt_name] = {
                "valid": len(fmt_issues) == 0,
                "named_groups": named_groups,
                "file_patterns": fmt.file_patterns,
                "issues": fmt_issues,
            }
            issues.extend(f"{fmt_name}: {i}" for i in fmt_issues)

        all_valid = all(f["valid"] for f in formats_valid.values())

        output = {
            "valid": all_valid,
            "config_path": str(config_path),
            "format_count": len(config.formats),
            "formats": formats_valid,
            "issues": issues,
        }

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


# =============================================================================
# Correlation Rule Commands (M2.4)
# =============================================================================


@llm.group()
def correlation():
    """
    Manage and run correlation rules.

    Apply user-defined correlation rules from .logler/correlations.yaml
    to discover relationships between log entries across files.
    """
    pass


@correlation.command("list")
@click.option("--config-dir", help="Directory to search for .logler/correlations.yaml")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def correlation_list(config_dir: Optional[str], pretty: bool):
    """List available correlation rule groups.

    Shows all correlation groups defined in .logler/correlations.yaml
    with their rule types and descriptions.
    """
    try:
        search_dir = Path(config_dir) if config_dir else Path.cwd()
        config_path = find_correlations_config(search_dir)

        output: Dict[str, Any] = {
            "config_path": None,
            "groups": {},
        }

        if not config_path:
            output["error"] = "No .logler/correlations.yaml found"
            _output_json(output, pretty)
            sys.exit(EXIT_NO_RESULTS)

        output["config_path"] = str(config_path)

        try:
            config = load_correlations_config(config_path)
        except Exception as e:
            output["config_error"] = str(e)
            _output_json(output, pretty)
            sys.exit(EXIT_USER_ERROR)

        for name, group in config.correlations.items():
            rules_summary = []
            for rule in group.rules:
                if rule.type == "field_match":
                    rules_summary.append(
                        {
                            "type": "field_match",
                            "source_field": rule.source.field,
                            "target_field": rule.target.field,
                            "source_pattern": rule.source.file_pattern,
                            "target_pattern": rule.target.file_pattern,
                        }
                    )
                elif rule.type == "temporal":
                    anchor_desc = {}
                    if rule.anchor.level:
                        anchor_desc["level"] = rule.anchor.level
                    if rule.anchor.pattern:
                        anchor_desc["pattern"] = rule.anchor.pattern
                    if rule.anchor.field:
                        anchor_desc["field"] = rule.anchor.field
                        anchor_desc["condition"] = rule.anchor.condition
                    rules_summary.append(
                        {
                            "type": "temporal",
                            "anchor": anchor_desc,
                            "window": rule.window,
                        }
                    )

            output["groups"][name] = {
                "description": group.description,
                "rule_count": len(group.rules),
                "rules": rules_summary,
            }

        has_groups = bool(output["groups"])
        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if has_groups else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


@correlation.command("run")
@click.option(
    "--files", "-f", multiple=True, required=True, help="Log files to correlate (supports globs)"
)
@click.option("--rule", "-r", "rule_name", help="Run only this named correlation group")
@click.option("--config-dir", help="Directory to search for .logler/correlations.yaml")
@click.option("--limit", type=int, help="Max clusters to return")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def correlation_run(
    files: tuple,
    rule_name: Optional[str],
    config_dir: Optional[str],
    limit: Optional[int],
    max_bytes: Optional[int],
    pretty: bool,
):
    """Run correlation rules against log files.

    Applies rules from .logler/correlations.yaml to discover relationships
    between entries across files. Creates virtual trace IDs linking related
    entries that share field values or temporal proximity.

    Examples:
        logler llm correlation run -f "factory/*.log"
        logler llm correlation run -f "mes_*.log" -f "plc_*.log" --rule batch-tracking
    """
    from . import investigate
    from .correlator import correlate_by_rules

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {list(files)}")

        # Find and load correlation config
        search_dir = Path(config_dir) if config_dir else Path.cwd()
        config_path = find_correlations_config(search_dir)
        if not config_path:
            _error_json("No .logler/correlations.yaml found. Create one or specify --config-dir.")

        config = load_correlations_config(config_path)
        if not config.correlations:
            _error_json("No correlation rules defined in config.")

        # Load all entries from files
        all_entries = []
        for file_path in file_list:
            try:
                result = investigate.search(
                    files=[file_path],
                    output_format="full",
                )
                for item in result.get("results", []):
                    entry = item.get("entry", {})
                    if entry:
                        all_entries.append(entry)
            except Exception:
                # Skip files that fail to load
                pass

        if not all_entries:
            output = {
                "config_path": str(config_path),
                "files_searched": len(file_list),
                "entries_loaded": 0,
                "clusters": [],
                "total_clusters": 0,
            }
            _output_json(output, pretty)
            sys.exit(EXIT_NO_RESULTS)

        # Run correlation
        result = correlate_by_rules(
            entries=all_entries,
            config=config,
            group_name=rule_name,
        )

        # Strip full entries from clusters for output (keep counts and metadata)
        output_clusters = []
        for cluster in result["clusters"]:
            slim = {
                "virtual_trace_id": cluster["virtual_trace_id"],
                "group": cluster["group"],
                "rule_type": cluster["rule_type"],
                "entry_count": cluster["entry_count"],
            }
            if cluster["rule_type"] == "field_match":
                slim["shared_value"] = cluster["shared_value"]
                slim["source_field"] = cluster["source_field"]
                slim["target_field"] = cluster["target_field"]
                slim["source_count"] = cluster["source_count"]
                slim["target_count"] = cluster["target_count"]
            elif cluster["rule_type"] == "temporal":
                slim["anchor_timestamp"] = cluster["anchor_timestamp"]
                slim["anchor_message"] = cluster["anchor_message"]
                slim["window"] = cluster["window"]

            # Include condensed entry references
            slim["entries"] = [
                {
                    "file": Path(e.get("file", "")).name,
                    "line_number": e.get("line_number"),
                    "timestamp": e.get("timestamp"),
                    "level": e.get("level"),
                    "message": (e.get("message") or "")[:200],
                }
                for e in cluster["entries"]
            ]

            output_clusters.append(slim)

        if limit:
            output_clusters = output_clusters[:limit]

        output = {
            "config_path": str(config_path),
            "files_searched": len(file_list),
            "entries_loaded": len(all_entries),
            "groups_applied": result["groups_applied"],
            "total_clusters": result["total_clusters"],
            "total_entries_correlated": result["total_entries_correlated"],
            "clusters": output_clusters,
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if result["total_clusters"] > 0 else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)
