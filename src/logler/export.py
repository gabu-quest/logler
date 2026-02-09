"""
Jaeger and Zipkin trace export from hierarchy data.

Public API surface is re-exported by :mod:`logler.investigate`.
"""

from typing import List, Optional, Dict, Any


def export_to_jaeger(
    hierarchy: Dict[str, Any],
    service_name: str = "logler-export",
) -> Dict[str, Any]:
    """Export hierarchy to Jaeger-compatible JSON format.

    The output follows the Jaeger JSON format and can be imported into the
    Jaeger UI for visualisation.

    Args:
        hierarchy: Hierarchy from :func:`follow_thread_hierarchy`.
        service_name: Name of the service for Jaeger.

    Returns:
        JaegerExport dict with shape::

            {"data": [{"traceID": str, "spans": [...], "processes": {...}}]}

    Example::

        >>> jaeger = export_to_jaeger(hierarchy, service_name="my-service")
        >>> with open("trace.json", "w") as f:
        ...     json.dump(jaeger, f)
    """
    import uuid
    from datetime import datetime

    trace_id = uuid.uuid4().hex[:32]
    spans = []

    def convert_node(node: Dict[str, Any], parent_span_id: Optional[str] = None):
        span_id = uuid.uuid4().hex[:16]

        # Parse timestamps
        start_time = node.get("start_time")
        if start_time:
            if isinstance(start_time, str):
                try:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    start_us = int(dt.timestamp() * 1_000_000)
                except Exception:
                    start_us = 0
            else:
                start_us = 0
        else:
            start_us = 0

        duration_us = int((node.get("duration_ms", 0) or 0) * 1000)

        span = {
            "traceID": trace_id,
            "spanID": span_id,
            "operationName": node.get("id", "unknown"),
            "references": [],
            "startTime": start_us,
            "duration": duration_us,
            "tags": [
                {"key": "node_type", "type": "string", "value": node.get("node_type", "unknown")},
                {"key": "entry_count", "type": "int64", "value": node.get("entry_count", 0)},
                {"key": "error_count", "type": "int64", "value": node.get("error_count", 0)},
            ],
            "logs": [],
            "processID": "p1",
            "warnings": [],
        }

        if parent_span_id:
            span["references"].append(
                {
                    "refType": "CHILD_OF",
                    "traceID": trace_id,
                    "spanID": parent_span_id,
                }
            )

        if node.get("error_count", 0) > 0:
            span["tags"].append({"key": "error", "type": "bool", "value": True})

        spans.append(span)

        # Process children
        for child in node.get("children", []):
            convert_node(child, span_id)

    # Convert all roots
    for root in hierarchy.get("roots", []):
        convert_node(root)

    return {
        "data": [
            {
                "traceID": trace_id,
                "spans": spans,
                "processes": {
                    "p1": {
                        "serviceName": service_name,
                        "tags": [
                            {"key": "exported_by", "type": "string", "value": "logler"},
                        ],
                    }
                },
                "warnings": [],
            }
        ]
    }


def export_to_zipkin(
    hierarchy: Dict[str, Any],
    service_name: str = "logler-export",
) -> List[Dict[str, Any]]:
    """Export hierarchy to Zipkin V2 JSON format.

    Args:
        hierarchy: Hierarchy from :func:`follow_thread_hierarchy`.
        service_name: Name of the service.

    Returns:
        List of spans in Zipkin V2 format.

    Example::

        >>> spans = export_to_zipkin(hierarchy)
        >>> # POST to Zipkin: curl -X POST http://localhost:9411/api/v2/spans ...
    """
    import uuid
    from datetime import datetime

    trace_id = uuid.uuid4().hex[:32]
    spans = []

    def convert_node(node: Dict[str, Any], parent_id: Optional[str] = None):
        span_id = uuid.uuid4().hex[:16]

        # Parse timestamp
        start_time = node.get("start_time")
        timestamp_us = 0
        if start_time:
            if isinstance(start_time, str):
                try:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    timestamp_us = int(dt.timestamp() * 1_000_000)
                except Exception:
                    pass

        duration_us = int((node.get("duration_ms", 0) or 0) * 1000)

        span = {
            "traceId": trace_id,
            "id": span_id,
            "name": node.get("id", "unknown"),
            "timestamp": timestamp_us,
            "duration": duration_us,
            "localEndpoint": {
                "serviceName": service_name,
            },
            "tags": {
                "node_type": node.get("node_type", "unknown"),
                "entry_count": str(node.get("entry_count", 0)),
            },
        }

        if parent_id:
            span["parentId"] = parent_id

        if node.get("error_count", 0) > 0:
            span["tags"]["error"] = "true"

        spans.append(span)

        for child in node.get("children", []):
            convert_node(child, span_id)

    for root in hierarchy.get("roots", []):
        convert_node(root)

    return spans
