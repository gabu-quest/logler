import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    mo.md(r"""
    # Logler Tour: Distributed Tracing Exports

    Logler can export hierarchies to standard distributed tracing formats:
    - **Jaeger** - Popular open-source tracing backend
    - **Zipkin** - Another widely-used tracing system

    This lets you visualize Logler-analyzed traces in those UIs.

    **What you'll learn:**
    1. Exporting to Jaeger format
    2. Exporting to Zipkin format
    3. Understanding the output structure
    4. How to import into tracing UIs

    Let's dive in!
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Setting Up - Trace Data

    We'll create a multi-service trace to export.
    """)
    return


@app.cell
def _():
    import json
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    logs = []

    # E-commerce checkout flow
    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=0)).isoformat(),
            "level": "INFO",
            "message": "Checkout started",
            "trace_id": "trace-export-001",
            "span_id": "span-checkout",
            "parent_span_id": None,
            "operation_name": "Checkout Start",
            "service": "checkout-service",
            "duration_ms": 1500,
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=10)).isoformat(),
            "level": "INFO",
            "message": "Validating cart",
            "trace_id": "trace-export-001",
            "span_id": "span-cart",
            "parent_span_id": "span-checkout",
            "operation_name": "Validate Cart",
            "service": "cart-service",
            "duration_ms": 200,
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=220)).isoformat(),
            "level": "INFO",
            "message": "Processing payment",
            "trace_id": "trace-export-001",
            "span_id": "span-payment",
            "parent_span_id": "span-checkout",
            "operation_name": "Process Payment",
            "service": "payment-service",
            "duration_ms": 800,
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=230)).isoformat(),
            "level": "INFO",
            "message": "Calling payment gateway",
            "trace_id": "trace-export-001",
            "span_id": "span-gateway",
            "parent_span_id": "span-payment",
            "operation_name": "Payment Gateway Call",
            "service": "stripe-gateway",
            "duration_ms": 600,
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=1050)).isoformat(),
            "level": "INFO",
            "message": "Creating order",
            "trace_id": "trace-export-001",
            "span_id": "span-order",
            "parent_span_id": "span-checkout",
            "operation_name": "Create Order",
            "service": "order-service",
            "duration_ms": 300,
        }
    )

    logs.append(
        {
            "timestamp": (base_time + timedelta(milliseconds=1360)).isoformat(),
            "level": "INFO",
            "message": "Sending confirmation",
            "trace_id": "trace-export-001",
            "span_id": "span-notify",
            "parent_span_id": "span-checkout",
            "operation_name": "Send Confirmation",
            "service": "notification-service",
            "duration_ms": 100,
        }
    )

    # Write to temp file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "trace.log"
    with open(log_file, "w") as _f:
        for _log in logs:
            _f.write(json.dumps(_log) + "\n")

    print(f"Created {len(logs)} log entries for checkout trace")
    return log_file, temp_dir


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Building the Hierarchy

    First, build the hierarchy from the logs.
    """)
    return


@app.cell
def _():
    from logler.investigate import follow_thread_hierarchy, export_to_jaeger, export_to_zipkin
    return export_to_jaeger, export_to_zipkin, follow_thread_hierarchy


@app.cell
def _(follow_thread_hierarchy, log_file):
    hierarchy = follow_thread_hierarchy(files=[str(log_file)], root_identifier="trace-export-001")

    print("=== Hierarchy ===")
    print(f"Total nodes: {hierarchy['total_nodes']}")
    print(f"Total duration: {hierarchy.get('total_duration_ms', 0)}ms")
    return (hierarchy,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Exporting to Jaeger Format

    Jaeger is a popular distributed tracing platform.
    The export follows Jaeger's JSON format specification.
    """)
    return


@app.cell
def _(export_to_jaeger, hierarchy):
    # Export to Jaeger format
    jaeger_trace = export_to_jaeger(hierarchy, service_name="logler-checkout-demo")

    print("=== Jaeger Export ===\n")
    print(f"Trace ID: {jaeger_trace['data'][0]['traceID']}")
    print(f"Number of spans: {len(jaeger_trace['data'][0]['spans'])}")
    print(f"Service: {jaeger_trace['data'][0]['processes']['p1']['serviceName']}")
    return (jaeger_trace,)


@app.cell
def _(jaeger_trace):
    print("=== Jaeger Spans ===\n")

    for _span in jaeger_trace["data"][0]["spans"][:5]:
        print(f"Span: {_span['operationName']}")
        print(f"  ID: {_span['spanID']}")
        print(f"  Duration: {_span['duration'] / 1000:.0f}ms")

        # Show parent reference if exists
        if _span["references"]:
            _parent = _span["references"][0]["spanID"]
            print(f"  Parent: {_parent}")

        # Show tags
        _tags = {_t["key"]: _t["value"] for _t in _span["tags"]}
        print(f"  Type: {_tags.get('node_type', 'unknown')}")
        print()
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Jaeger Export Structure

    The Jaeger format includes:
    - **traceID**: Unique identifier for the trace
    - **spans**: Array of span objects
    - **processes**: Service metadata
    - **references**: Parent-child relationships
    """)
    return


@app.cell
def _(jaeger_trace):
    import json as _json

    print("=== Full Jaeger JSON (truncated) ===\n")
    _full = _json.dumps(jaeger_trace, indent=2)
    print(_full[:1500] + "\n..." if len(_full) > 1500 else _full)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Exporting to Zipkin Format

    Zipkin uses a different format - an array of spans
    with direct parentId references.
    """)
    return


@app.cell
def _(export_to_zipkin, hierarchy):
    # Export to Zipkin format
    zipkin_spans = export_to_zipkin(hierarchy, service_name="logler-checkout-demo")

    print("=== Zipkin Export ===\n")
    print(f"Number of spans: {len(zipkin_spans)}")
    if zipkin_spans:
        print(f"Trace ID: {zipkin_spans[0]['traceId']}")
    return (zipkin_spans,)


@app.cell
def _(zipkin_spans):
    print("=== Zipkin Spans ===\n")

    for _span in zipkin_spans[:5]:
        print(f"Span: {_span['name']}")
        print(f"  ID: {_span['id']}")
        print(f"  Duration: {_span['duration'] / 1000:.0f}ms")

        if _span.get("parentId"):
            print(f"  Parent: {_span['parentId']}")

        print(f"  Service: {_span['localEndpoint']['serviceName']}")
        print(f"  Tags: {_span.get('tags', {})}")
        print()
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Zipkin Export Structure

    Zipkin format is simpler - just an array of spans:
    - **traceId**: Trace identifier
    - **id**: Span identifier
    - **parentId**: Direct parent reference (optional)
    - **localEndpoint**: Service info
    - **tags**: Metadata
    """)
    return


@app.cell
def _(zipkin_spans):
    import json as _json2

    print("=== Full Zipkin JSON (truncated) ===\n")
    _full2 = _json2.dumps(zipkin_spans, indent=2)
    print(_full2[:1500] + "\n..." if len(_full2) > 1500 else _full2)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. How to Import

    **Jaeger:**
    ```bash
    # Save to file
    python -c "import json; print(json.dumps(jaeger_trace))" > trace.json

    # Import via Jaeger UI or API
    # Jaeger Query UI can import JSON traces directly
    ```

    **Zipkin:**
    ```bash
    # Save to file
    python -c "import json; print(json.dumps(zipkin_spans))" > spans.json

    # POST to Zipkin
    curl -X POST http://localhost:9411/api/v2/spans \
         -H 'Content-Type: application/json' \
         -d @spans.json
    ```
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Saving Exports to Files
    """)
    return


@app.cell
def _(jaeger_trace, temp_dir, zipkin_spans):
    import json as _json3
    from pathlib import Path as _Path

    # Save Jaeger export
    jaeger_file = _Path(temp_dir) / "jaeger_trace.json"
    with open(jaeger_file, "w") as _f:
        _json3.dump(jaeger_trace, _f, indent=2)
    print(f"Saved Jaeger export to: {jaeger_file}")

    # Save Zipkin export
    zipkin_file = _Path(temp_dir) / "zipkin_spans.json"
    with open(zipkin_file, "w") as _f:
        _json3.dump(zipkin_spans, _f, indent=2)
    print(f"Saved Zipkin export to: {zipkin_file}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Summary

    You've learned how to export traces:

    - **`export_to_jaeger(hierarchy, service_name)`** - Jaeger JSON format
    - **`export_to_zipkin(hierarchy, service_name)`** - Zipkin V2 format

    **Format Differences:**
    | Feature | Jaeger | Zipkin |
    |---------|--------|--------|
    | Structure | Nested data object | Flat span array |
    | Parent ref | references array | parentId field |
    | Processes | Separate section | In localEndpoint |

    **Use Cases:**
    - Import log-derived traces into existing tracing UI
    - Compare Logler analysis with production traces
    - Share traces with teams using different tools

    **Next Steps:**
    - **Tour 10**: Smart sampling strategies
    - **Tour 11**: AI-powered insights
    """)
    return


@app.cell
def _(temp_dir):
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    print("Cleaned up temp files")
    return


if __name__ == "__main__":
    app.run()
