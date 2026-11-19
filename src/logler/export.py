"""
Jaeger, Zipkin and OTLP trace export from hierarchy data.

Public API surface is re-exported by :mod:`logler.investigate`; ``logler llm export`` calls
these functions too.

Ids: a span id is 16 hexadecimal characters and a trace id 32, in lower case. A log's own
span id of that form is kept unless it is all zeros (which OTLP and W3C trace context call
invalid); any other id is replaced by one derived from it with SHA-256,
so an export is the same in every run. A node with no span id of its own (a thread or an
inferred node) gets an id derived from the trace id and its place in the tree.
"""

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_SERVICE = "logler-export"

# An id of this many hex digits that is not all zeros: OTLP and W3C trace context call an
# all-zero id invalid, and a logger writes one when no span is active.
_HEX16 = re.compile(r"(?!0{16})[0-9a-f]{16}")
_HEX32 = re.compile(r"(?!0{32})[0-9a-f]{32}")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _digest(text: str, length: int) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


def trace_hex_id(identifier: str | None, hierarchy: dict[str, Any]) -> str:
    """The trace id of an export: ``identifier`` when it is 32 hexadecimal characters and
    not all zeros, else derived from it; with no identifier, derived from the ids of the
    hierarchy's roots."""
    if identifier is None:
        identifier = "\n".join(str(root.get("id")) for root in hierarchy.get("roots", []))
    lower = identifier.lower()
    return lower if _HEX32.fullmatch(lower) else _digest(identifier, 32)


def _start_us(node: dict[str, Any]) -> int:
    """The node's start in microseconds since the epoch; 0 when it has none."""
    start_time = node.get("start_time")
    if not isinstance(start_time, str) or not start_time:
        return 0
    try:
        dt = datetime.fromisoformat(start_time)
    except ValueError:
        return 0
    return (dt.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1)


class _Span:
    """One node of the hierarchy as a span, with what every format needs."""

    __slots__ = ("duration_us", "node", "parent_id", "service", "span_id", "start_us")

    def __init__(
        self, node: dict[str, Any], span_id: str, parent_id: str | None, service: str
    ) -> None:
        self.node = node
        self.span_id = span_id
        self.parent_id = parent_id
        self.service = service
        self.start_us = _start_us(node)
        self.duration_us = int((node.get("duration_ms") or 0) * 1000)

    @property
    def name(self) -> str:
        return str(self.node.get("name") or self.node.get("id") or "unknown")

    @property
    def node_type(self) -> str:
        return str(self.node.get("node_type", "unknown"))

    @property
    def entry_count(self) -> int:
        return int(self.node.get("entry_count") or 0)

    @property
    def error_count(self) -> int:
        return int(self.node.get("error_count") or 0)


def _spans(hierarchy: dict[str, Any], trace_id: str, service_name: str) -> list[_Span]:
    """Every node of the hierarchy as a span, depth first, each with an id no other has.

    A span's service is its node's ``service``; a node with none is under ``service_name``.
    """
    used: set[str] = set()
    spans: list[_Span] = []

    def span_id_of(node: dict[str, Any], path: str) -> str:
        own = node.get("id")
        if node.get("node_type") == "Span" and isinstance(own, str) and own:
            source = own
            lower = own.lower()
            span_id = lower if _HEX16.fullmatch(lower) else _digest(own, 16)
        else:
            source = f"{trace_id}/{path}"
            span_id = _digest(source, 16)
        repeat = 0
        while span_id in used:
            repeat += 1
            span_id = _digest(f"{source}#{repeat}", 16)
        used.add(span_id)
        return span_id

    def walk(node: dict[str, Any], path: str, parent_id: str | None) -> None:
        span = _Span(
            node,
            span_id_of(node, path),
            parent_id,
            node.get("service") or service_name,
        )
        spans.append(span)
        for i, child in enumerate(node.get("children") or []):
            walk(child, f"{path}.{i}", span.span_id)

    for i, root in enumerate(hierarchy.get("roots", [])):
        walk(root, str(i), None)
    return spans


def export_to_jaeger(
    hierarchy: dict[str, Any],
    service_name: str = DEFAULT_SERVICE,
    identifier: str | None = None,
) -> dict[str, Any]:
    """Export hierarchy to Jaeger-compatible JSON format.

    The output follows the Jaeger JSON format and can be imported into the
    Jaeger UI for visualisation.

    Args:
        hierarchy: Hierarchy from :func:`follow_thread_hierarchy`.
        service_name: Name of the service for a span whose node names none (a node's
            ``service`` is the ``service_name`` of the first of its entries that has one).
        identifier: The trace or correlation id the hierarchy was built for; the trace id
            is made from it.

    Returns:
        JaegerExport dict with shape::

            {"data": [{"traceID": str, "spans": [...], "processes": {...},
                       "warnings": []}]}

        Each service has one process (``p1``, ``p2``, ... in order of first use), and a
        span names its service through ``processID``.

    Example::

        >>> jaeger = export_to_jaeger(hierarchy, service_name="my-service")
        >>> with open("trace.json", "w") as f:
        ...     json.dump(jaeger, f)
    """
    trace_id = trace_hex_id(identifier, hierarchy)
    processes: dict[str, dict[str, Any]] = {}
    process_of: dict[str, str] = {}
    spans = []
    for span in _spans(hierarchy, trace_id, service_name):
        if span.service not in process_of:
            process_of[span.service] = f"p{len(process_of) + 1}"
            processes[process_of[span.service]] = {
                "serviceName": span.service,
                "tags": [{"key": "exported_by", "type": "string", "value": "logler"}],
            }
        tags: list[dict[str, Any]] = [
            {"key": "node_type", "type": "string", "value": span.node_type},
            {"key": "entry_count", "type": "int64", "value": span.entry_count},
            {"key": "error_count", "type": "int64", "value": span.error_count},
        ]
        if span.error_count > 0:
            tags.append({"key": "error", "type": "bool", "value": True})
        references = []
        if span.parent_id:
            references.append(
                {"refType": "CHILD_OF", "traceID": trace_id, "spanID": span.parent_id}
            )
        spans.append(
            {
                "traceID": trace_id,
                "spanID": span.span_id,
                "operationName": span.name,
                "references": references,
                "startTime": span.start_us,
                "duration": span.duration_us,
                "tags": tags,
                "logs": [],
                "processID": process_of[span.service],
                "warnings": [],
            }
        )
    return {"data": [{"traceID": trace_id, "spans": spans, "processes": processes, "warnings": []}]}


def export_to_zipkin(
    hierarchy: dict[str, Any],
    service_name: str = DEFAULT_SERVICE,
    identifier: str | None = None,
) -> list[dict[str, Any]]:
    """Export hierarchy to Zipkin V2 JSON format.

    Args:
        hierarchy: Hierarchy from :func:`follow_thread_hierarchy`.
        service_name: Name of the service for a span whose node names none.
        identifier: The trace or correlation id; see :func:`export_to_jaeger`.

    Returns:
        List of spans in Zipkin V2 format; a span's service is its ``localEndpoint``.

    Example::

        >>> spans = export_to_zipkin(hierarchy)
        >>> # POST to Zipkin: curl -X POST http://localhost:9411/api/v2/spans ...
    """
    trace_id = trace_hex_id(identifier, hierarchy)
    out = []
    for span in _spans(hierarchy, trace_id, service_name):
        item: dict[str, Any] = {
            "traceId": trace_id,
            "id": span.span_id,
            "name": span.name,
            "timestamp": span.start_us,
            "duration": span.duration_us,
            "localEndpoint": {"serviceName": span.service},
            "tags": {"node_type": span.node_type, "entry_count": str(span.entry_count)},
        }
        if span.parent_id:
            item["parentId"] = span.parent_id
        if span.error_count > 0:
            item["tags"]["error"] = "true"
        out.append(item)
    return out


def _otlp_attr(key: str, value: str | int) -> dict[str, Any]:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def export_to_otlp(
    hierarchy: dict[str, Any],
    service_name: str = DEFAULT_SERVICE,
    identifier: str | None = None,
) -> dict[str, Any]:
    """Export hierarchy to the JSON form of OTLP (OpenTelemetry) traces.

    Args:
        hierarchy: Hierarchy from :func:`follow_thread_hierarchy`.
        service_name: Name of the service for a span whose node names none.
        identifier: The trace or correlation id; see :func:`export_to_jaeger`.

    Returns:
        OtlpExport dict with shape::

            {"resourceSpans": [{"resource": {"attributes": [service.name]},
                                "scopeSpans": [{"scope": {"name": "logler"},
                                                "spans": [...]}]}]}

        One ``resourceSpans`` entry per service, in order of first use. A span's
        ``traceId`` and ``spanId`` are hex text, its two ``...UnixNano`` times are decimal
        text of nanoseconds, and a root span has no ``parentSpanId``; a span with errors
        has ``status`` ``{"code": 2}``.
    """
    trace_id = trace_hex_id(identifier, hierarchy)
    by_service: dict[str, list[dict[str, Any]]] = {}
    for span in _spans(hierarchy, trace_id, service_name):
        item: dict[str, Any] = {"traceId": trace_id, "spanId": span.span_id}
        if span.parent_id:
            item["parentSpanId"] = span.parent_id
        item["name"] = span.name
        item["startTimeUnixNano"] = str(span.start_us * 1000)
        item["endTimeUnixNano"] = str((span.start_us + span.duration_us) * 1000)
        item["attributes"] = [
            _otlp_attr("node_type", span.node_type),
            _otlp_attr("entry_count", span.entry_count),
            _otlp_attr("error_count", span.error_count),
        ]
        if span.error_count > 0:
            item["status"] = {"code": 2}
        by_service.setdefault(span.service, []).append(item)
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_otlp_attr("service.name", service)]},
                "scopeSpans": [{"scope": {"name": "logler"}, "spans": spans}],
            }
            for service, spans in by_service.items()
        ]
    }


EXPORTERS: dict[str, Callable[..., Any]] = {
    "jaeger": export_to_jaeger,
    "zipkin": export_to_zipkin,
    "otlp": export_to_otlp,
}
