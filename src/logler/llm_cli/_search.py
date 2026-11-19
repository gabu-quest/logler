"""Search, schema, IDs, sample, triage, summarize, and SQL commands."""

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import click

from .._search_core import BUILD_HINT, level_text
from ._core import (
    EXIT_INTERNAL_ERROR,
    EXIT_NO_RESULTS,
    EXIT_SUCCESS,
    EXIT_USER_ERROR,
    _apply_max_bytes,
    _check_level_words,
    _db_file_source,
    _error_json,
    _extract_patterns,
    _level_texts,
    _output_json,
    _outside_bounds,
    _resolve_time_bounds,
    _resolve_time_filters,
    _time_text_outside_bounds,
    command,
    db_source_option,
    time_filter_options,
)


@command()
@click.argument("files", nargs=-1, required=False)
@db_source_option
@click.option("--sample-size", default=1000, help="Number of entries to analyze (default: 1000)")
@click.option("--full", is_flag=True, help="Analyze all entries (slow for large files)")
def schema(files: tuple, db_path: str | None, sample_size: int, full: bool, pretty: bool):
    """
    Infer the structure/schema of log files.

    Analyzes log files to determine available fields, formats,
    and data patterns. Useful for understanding log structure
    before running queries.

    Example:
        logler llm schema app.log worker.log
    """
    from ..parser import LogParser, read_lines

    with _db_file_source(files, db_path) as file_list:
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
                parser = LogParser.for_file(file_path)
                for number, line in read_lines(file_path):
                    if not full and number > sample_size:
                        break

                    if not line.strip():
                        continue

                    entry = parser.parse_line(number, line)
                    total_entries += 1

                    # Track field presence
                    if entry.timestamp:
                        field_presence["timestamp"] += 1
                        timestamps.append((entry.timestamp, entry.timestamp_text))
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
                        for key in entry.extra:
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
            sorted_ts = sorted(timestamps, key=lambda pair: pair[0])
            time_range = {"earliest": sorted_ts[0][1], "latest": sorted_ts[-1][1]}

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


@command()
@click.argument("files", nargs=-1, required=False)
@db_source_option
@click.option(
    "--level",
    help="Filter by log level (comma-separated: ERROR,WARN)",
    callback=_check_level_words,
)
@click.option(
    "--exclude-level", help="Exclude log levels (comma-separated)", callback=_check_level_words
)
@click.option("--query", help="Regex pattern to match in message")
@click.option("--exclude-query", help="Regex pattern to exclude matching entries")
@click.option("--thread", help="Filter by thread ID (comma-separated for multi)")
@click.option("--correlation", help="Filter by correlation ID (comma-separated)")
@click.option("--trace", help="Filter by trace ID (comma-separated)")
@click.option("--service", help="Filter by service name (comma-separated)")
@time_filter_options
@click.option(
    "--limit", type=click.IntRange(min=1), default=None, help="Limit number of results (first N)"
)
@click.option(
    "--head", "head_n", type=click.IntRange(min=1), default=None, help="Alias for --limit"
)
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
def search(
    files: tuple,
    db_path: str | None,
    level: str | None,
    exclude_level: str | None,
    query: str | None,
    exclude_query: str | None,
    thread: str | None,
    correlation: str | None,
    trace: str | None,
    service: str | None,
    last_duration: str | None,
    after: str | None,
    before: str | None,
    limit: int | None,
    head_n: int | None,
    tail_n: int | None,
    context: int,
    fields: str | None,
    include_raw: bool,
    aggregate: bool,
    max_bytes: int | None,
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
        logler llm search --db qler.db --level ERROR
    """
    from .. import investigate

    with _db_file_source(files, db_path) as file_list:
        try:
            # Resolve time filters -> push to Rust
            time_start, time_end = _resolve_time_filters(last_duration, after, before)

            # --head is alias for --limit
            effective_limit = limit or head_n

            # Parse fields list
            field_list = [f.strip() for f in fields.split(",")] if fields else None

            # Call search -- time filtering now happens in Rust
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
                limit=effective_limit,
                tail=tail_n,
                time_start=time_start,
                time_end=time_end,
                context_lines=context,
                output_format="full",
                fields=field_list,
                count_only=count_only,
                offset=offset,
            )

            # Build LLM-optimized output
            results = result.get("results", [])
            total_matches = result.get("total_matches", len(results))

            # --count-only: return just the count, no results
            if count_only:
                output: dict[str, Any] = {
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
                    out_entry: dict[str, Any] = {
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

            has_more = (offset + len(output_results)) < total_matches

            # Build aggregations from ALL results (before offset) for metadata-only
            agg_by_level: dict[str, int] = defaultdict(int)
            agg_by_thread: dict[str, int] = defaultdict(int)
            agg_by_service: dict[str, int] = defaultdict(int)

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
                    f"Rust backend not available. Build with: {BUILD_HINT}",
                    EXIT_INTERNAL_ERROR,
                )
            raise


@command()
@click.argument("files", nargs=-1, required=False)
@db_source_option
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
def ids(
    files: tuple,
    db_path: str | None,
    last_duration: str | None,
    after: str | None,
    before: str | None,
    id_type: str,
    limit: int | None,
    max_bytes: int | None,
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
    from .. import investigate

    with _db_file_source(files, db_path) as file_list:
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


@command()
@click.argument("files", nargs=-1, required=False)
@db_source_option
@click.option(
    "--strategy",
    type=click.Choice(["random", "diverse", "errors_focused", "head", "tail", "edges"]),
    default="diverse",
    help="Sampling strategy",
)
@click.option("--size", type=int, default=100, help="Sample size (default: 100)")
@click.option(
    "--level",
    help="Filter by log level (comma-separated: ERROR,WARN)",
    callback=_check_level_words,
)
@click.option(
    "--exclude-level", help="Exclude log levels (comma-separated)", callback=_check_level_words
)
@click.option("--service", help="Filter by service name (comma-separated)")
@time_filter_options
def sample(
    files: tuple,
    db_path: str | None,
    strategy: str,
    size: int,
    level: str | None,
    exclude_level: str | None,
    service: str | None,
    last_duration: str | None,
    after: str | None,
    before: str | None,
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
    from .. import investigate

    with _db_file_source(files, db_path) as file_list:
        # Resolve time filters
        time_start, time_end = _resolve_time_bounds(last_duration, after, before)

        result = investigate.smart_sample(
            files=file_list, level=level, strategy=strategy, sample_size=size
        )

        # Post-filter by exclude_level, service, and time
        entries = result.get("samples", []) or result.get("entries", [])
        if exclude_level:
            excl_set = _level_texts(exclude_level)
            entries = [e for e in entries if level_text(e.get("level")) not in excl_set]
        if service:
            svc_set = {s.strip() for s in service.split(",")}
            entries = [
                e
                for e in entries
                if e.get("service_name") in svc_set or e.get("service") in svc_set
            ]
        if time_start or time_end:
            entries = [
                e
                for e in entries
                if not _time_text_outside_bounds(e.get("timestamp"), time_start, time_end)
            ]

        result["samples"] = entries

        # Build output
        output = {
            "population": {
                "total_entries": result.get("total_population", 0),
                "files": file_list,
            },
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


@command()
@click.argument("files", nargs=-1, required=False)
@db_source_option
@time_filter_options
@click.option("--service", help="Filter by service name (comma-separated)")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
def triage(
    files: tuple,
    db_path: str | None,
    last_duration: str | None,
    after: str | None,
    before: str | None,
    service: str | None,
    max_bytes: int | None,
    pretty: bool,
):
    """
    Quick severity assessment for incident response.

    Returns severity level, error rate, and log level distribution.
    Designed for rapid initial assessment during incidents.

    Example:
        logler llm triage /var/log/app/*.log --last 1h
    """
    from .. import investigate

    with _db_file_source(files, db_path) as file_list:
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


@command()
@click.argument("files", nargs=-1, required=False)
@db_source_option
@click.option(
    "--focus",
    type=click.Choice(["errors", "all", "warnings"]),
    default="errors",
    help="What to focus on",
)
@click.option("--service", help="Filter by service name (comma-separated)")
@time_filter_options
@click.option("--max-bytes", type=int, help="Maximum output size in bytes (truncates)")
def summarize(
    files: tuple,
    db_path: str | None,
    focus: str,
    service: str | None,
    last_duration: str | None,
    after: str | None,
    before: str | None,
    max_bytes: int | None,
    pretty: bool,
):
    """
    Generate a concise summary of log contents.

    Returns structured data with a human-readable summary,
    perfect for LLM context.

    Example:
        logler llm summarize app.log --focus errors
    """
    from ..parser import LogParser, read_lines

    with _db_file_source(files, db_path) as file_list:
        # Resolve time and service filters
        time_start, time_end = _resolve_time_bounds(last_duration, after, before)
        svc_set = {s.strip() for s in service.split(",")} if service else None

        # Collect stats
        total = 0
        by_level = defaultdict(int)
        errors = []
        warnings = []
        unique_errors = defaultdict(int)
        first_time = last_time = first_text = last_text = None
        correlation_ids = set()

        for file_path in file_list:
            try:
                parser = LogParser.for_file(file_path)
                for number, line in read_lines(file_path):
                    if not line.strip():
                        continue

                    entry = parser.parse_line(number, line)

                    # Apply time filters
                    if _outside_bounds(entry.timestamp, time_start, time_end):
                        continue

                    # Apply service filter
                    if svc_set:
                        entry_svc = getattr(entry, "service_name", None) or getattr(
                            entry, "service", None
                        )
                        if entry_svc not in svc_set:
                            continue

                    total += 1

                    level_val = level_text(entry.level)
                    by_level[level_val] += 1

                    if entry.timestamp:
                        if first_time is None or entry.timestamp < first_time:
                            first_time, first_text = entry.timestamp, entry.timestamp_text
                        if last_time is None or entry.timestamp > last_time:
                            last_time, last_text = entry.timestamp, entry.timestamp_text

                    if entry.correlation_id:
                        correlation_ids.add(entry.correlation_id)

                    if level_val == "ERROR":
                        msg = entry.message or line[:100]
                        unique_errors[msg] += 1
                        if len(errors) < 10:
                            errors.append(
                                {
                                    "line": number,
                                    "message": msg,
                                    "correlation_id": entry.correlation_id,
                                }
                            )
                    elif level_val in ["WARN", "WARNING"] and len(warnings) < 5:
                        warnings.append(
                            {
                                "line": number,
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
            summary_text = (
                f"{total} entries, {error_count} errors ({error_types} unique), "
                f"{warn_count} warnings"
            )

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
                "time_range": ({"start": first_text, "end": last_text} if first_time else None),
            },
            "errors": errors if focus in ["errors", "all"] else [],
            "warnings": warnings if focus in ["warnings", "all"] else [],
            "unique_error_messages": dict(unique_errors) if unique_errors else {},
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS if total > 0 else EXIT_NO_RESULTS)


@command()
@click.argument("query", required=False)
@click.option("--files", "-f", multiple=True, help="Files to load (supports globs)")
@db_source_option
@click.option("--stdin", is_flag=True, help="Read SQL query from stdin")
def sql(query: str | None, files: tuple, db_path: str | None, stdin: bool, pretty: bool):
    """
    Execute SQL queries on log files using DuckDB.

    Loads log files into a 'logs' table with columns:
    - file, line_number, timestamp (a TIMESTAMP), level (upper case, UNKNOWN when
      the line has none), message, thread_id, correlation_id, trace_id, span_id, raw

    and a 'metrics' table of the numeric values found in the lines (built only for a
    query that reads it):
    - file, line_number, timestamp, field_name, value, unit

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
    """
    import duckdb

    from ..parser import LogParser, read_lines
    from ..sql import SqlEngine

    def entries(file_list):
        """The files' lines as engine entry dicts, one at a time."""
        for file_path in file_list:
            parser = LogParser.for_file(file_path)
            for number, line in read_lines(file_path):
                yield parser.parse_entry(number, line, file_path)

    with _db_file_source(files, db_path, default_glob="*.log") as file_list:
        # Get query from argument or stdin
        if stdin:
            import sys as _sys

            query = _sys.stdin.read().strip()
        if not query:
            _error_json("SQL query required. Provide as argument or use --stdin.")

        engine = SqlEngine()
        try:
            total_entries = engine.load_entries(
                entries(file_list), metrics=not engine.reads_only_logs(query)
            )

            if total_entries == 0:
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

            try:
                columns, rows = engine.execute(query)
            except duckdb.Error as e:
                _error_json(f"SQL error: {e}", EXIT_USER_ERROR)

            output = {
                "query": query,
                "files": file_list,
                "total_entries": total_entries,
                "columns": columns,
                "row_count": len(rows),
                "results": rows,
            }

            _output_json(output, pretty)
            sys.exit(EXIT_SUCCESS if rows else EXIT_NO_RESULTS)
        finally:
            engine.close()
