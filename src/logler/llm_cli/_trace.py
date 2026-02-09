"""Trace-related commands: correlate, hierarchy, bottleneck, context, export."""

import click
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

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
    from .. import investigate

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
    from .. import investigate

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
    from .. import investigate

    try:
        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

        # Get hierarchy to analyze
        hierarchy_result = investigate.follow_thread_hierarchy(
            files=file_list,
            root_identifier=identifier,
        )

        if not hierarchy_result.get("roots"):
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

        for root in hierarchy_result.get("roots", []):
            collect_nodes(root, [])

        # Sort by duration descending
        nodes_with_duration.sort(key=lambda x: -x["duration_ms"])
        top_bottlenecks = nodes_with_duration[:top_n]

        # Calculate percentages
        total_duration = hierarchy_result.get("total_duration_ms", 0) or 1
        for node in top_bottlenecks:
            node["percentage"] = round(node["duration_ms"] / total_duration * 100, 1)

        output = {
            "identifier": identifier,
            "total_duration_ms": hierarchy_result.get("total_duration_ms"),
            "total_nodes": hierarchy_result.get("total_nodes", 0),
            "analysis": {
                "threshold_ms": threshold_ms,
                "nodes_above_threshold": len(nodes_with_duration),
            },
            "bottlenecks": top_bottlenecks,
            "hierarchy_bottleneck": hierarchy_result.get("bottleneck"),
        }

        if max_bytes:
            output = _apply_max_bytes(output, max_bytes)

        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        _error_json(f"Internal error: {str(e)}", EXIT_INTERNAL_ERROR)


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
    from .. import investigate

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
    from .. import investigate

    try:
        file_list = _expand_globs(list(files)) if files else _expand_globs(["*.log"])
        if not file_list:
            _error_json(f"No files found matching: {files or ['*.log']}")

        # Get hierarchy for the trace
        hierarchy_result = investigate.follow_thread_hierarchy(
            files=file_list,
            root_identifier=identifier,
        )

        if not hierarchy_result.get("roots"):
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

        for root in hierarchy_result.get("roots", []):
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
