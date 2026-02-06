"""Metrics, detection, templates, verify-pattern, and emit commands."""

import click
import json
import re
import sys
from pathlib import Path
from typing import Optional
from collections import defaultdict
from datetime import datetime

from ._core import (
    llm,
    EXIT_SUCCESS,
    EXIT_NO_RESULTS,
    EXIT_INTERNAL_ERROR,
    _output_json,
    _error_json,
    _expand_globs,
    _apply_max_bytes,
    _resolve_time_filters,
    time_filter_options,
)
from ..safe_regex import safe_compile, RegexTimeoutError, RegexPatternTooLongError


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
    from ..parser import LogParser

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
    from ..parser import LogParser

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
@click.option(
    "--fields",
    help="Comma-separated list of field names to include (default: all)",
)
@click.option(
    "--bucket",
    help="Time bucket size for aggregation (e.g., 1s, 5s, 1m)",
)
@click.option(
    "--anomaly-threshold",
    type=float,
    default=2.0,
    help="Z-score threshold for anomaly detection (default: 2.0)",
)
@click.option("--compact", is_flag=True, help="Compact output (stats only, no buckets)")
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def metrics(
    files: tuple,
    fields: Optional[str],
    bucket: Optional[str],
    anomaly_threshold: float,
    compact: bool,
    max_bytes: Optional[int],
    pretty: bool,
):
    """Extract numeric values from log files and compute time-series statistics.

    Finds numeric fields in structured data (JSON fields, key=value pairs)
    and log messages (duration=123ms, temperature: 45.2).

    For each discovered field, computes: min, max, mean, median, stddev,
    p95, p99, and z-score anomalies.

    Examples:
        logler llm metrics app.log sensor.log
        logler llm metrics "*.log" --fields temperature,pressure --bucket 5s
        logler llm metrics app.log --compact --pretty
    """
    from .. import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {list(files)}")

        field_list = [f.strip() for f in fields.split(",")] if fields else None

        result = investigate.extract_metrics(
            files=file_list,
            fields=field_list,
            bucket_size=None if compact else bucket,
            anomaly_threshold=anomaly_threshold,
        )

        if compact:
            # Compact mode: stats only, no buckets or anomaly details
            compact_fields = {}
            for name, data in result.get("fields", {}).items():
                compact_fields[name] = {
                    "count": data["count"],
                    "stats": data["stats"],
                }
                if data.get("unit"):
                    compact_fields[name]["unit"] = data["unit"]
            result = {
                "fields": compact_fields,
                "entries_scanned": result["entries_scanned"],
                "files_searched": result["files_searched"],
            }

        if max_bytes:
            result = _apply_max_bytes(result, max_bytes)

        _output_json(result, pretty)

        has_fields = bool(result.get("fields"))
        sys.exit(EXIT_SUCCESS if has_fields else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error in metrics: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--sample", type=int, default=50, help="Lines to sample per file (default: 50)")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def detect(
    files: tuple,
    sample: int,
    pretty: bool,
):
    """Auto-detect the log format of files with confidence scoring.

    Samples lines from each file and scores them against known formats
    (JSON, syslog, Apache CLF, logfmt) and any custom formats from
    .logler/formats.yaml.

    Examples:
        logler llm detect app.log sensor.log
        logler llm detect "*.log" --sample 100 --pretty
    """
    from .. import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {list(files)}")

        result = investigate.detect_formats(
            files=file_list,
            sample_size=sample,
        )

        _output_json(result, pretty)
        sys.exit(EXIT_SUCCESS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error in detect: {str(e)}", EXIT_INTERNAL_ERROR)


@llm.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--max-clusters", type=int, default=200, help="Max template clusters (default: 200)")
@click.option(
    "--similarity",
    type=float,
    default=0.5,
    help="Token similarity threshold for merging (0.0-1.0, default: 0.5)",
)
@click.option("--max-bytes", type=int, help="Maximum output size in bytes")
@click.option("--pretty", is_flag=True, help="Pretty-print JSON output")
def templates(
    files: tuple,
    max_clusters: int,
    similarity: float,
    max_bytes: Optional[int],
    pretty: bool,
):
    """Mine recurring log templates using the Drain algorithm.

    Discovers common log message patterns and extracts variable positions.
    Templates show what patterns recur most often, helping to understand
    log structure and identify dominant behaviors.

    Examples:
        logler llm templates app.log
        logler llm templates "*.log" --max-clusters 50 --pretty
    """
    from .. import investigate

    try:
        file_list = _expand_globs(list(files))
        if not file_list:
            _error_json(f"No files found matching: {list(files)}")

        result = investigate.mine_log_templates(
            files=file_list,
            max_clusters=max_clusters,
            sim_threshold=similarity,
        )

        if max_bytes:
            result = _apply_max_bytes(result, max_bytes)

        _output_json(result, pretty)

        has_templates = result.get("unique_templates", 0) > 0
        sys.exit(EXIT_SUCCESS if has_templates else EXIT_NO_RESULTS)

    except SystemExit:
        raise
    except Exception as e:
        _error_json(f"Internal error in templates: {str(e)}", EXIT_INTERNAL_ERROR)
