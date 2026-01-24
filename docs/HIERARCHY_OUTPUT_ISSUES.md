## Context

While validating Logler as a real-world log analysis tool, a simple trace-like
log exposed hierarchy output issues that make the CLI summaries misleading
and the visualizations noisy.

### Minimal Repro Log

```json
{"timestamp":"2024-01-15T10:00:00Z","level":"INFO","message":"GET /api/orders started","thread_id":"worker-1","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"checkout.request","parent_span_id":null,"operation_name":"Checkout Request","service":"api"}
{"timestamp":"2024-01-15T10:00:00.050Z","level":"INFO","message":"Inventory check","thread_id":"worker-2","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"inventory.check","parent_span_id":"checkout.request","operation_name":"Inventory Check","service":"inventory","duration_ms":80}
{"timestamp":"2024-01-15T10:00:00.090Z","level":"WARN","message":"Low stock for SKU-3","thread_id":"worker-2","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"inventory.check","parent_span_id":"checkout.request","operation_name":"Inventory Check","service":"inventory"}
{"timestamp":"2024-01-15T10:00:00.120Z","level":"INFO","message":"Payment processing","thread_id":"worker-3","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"payment.process","parent_span_id":"checkout.request","operation_name":"Process Payment","service":"payment","duration_ms":300}
{"timestamp":"2024-01-15T10:00:00.200Z","level":"ERROR","message":"Payment gateway timeout","thread_id":"worker-3","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"payment.process","parent_span_id":"checkout.request","operation_name":"Process Payment","service":"payment"}
{"timestamp":"2024-01-15T10:00:00.260Z","level":"INFO","message":"Retrying payment","thread_id":"worker-3","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"payment.process","parent_span_id":"checkout.request","operation_name":"Process Payment","service":"payment"}
{"timestamp":"2024-01-15T10:00:00.350Z","level":"INFO","message":"Payment authorized","thread_id":"worker-3","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"payment.process","parent_span_id":"checkout.request","operation_name":"Process Payment","service":"payment"}
{"timestamp":"2024-01-15T10:00:00.420Z","level":"INFO","message":"Response sent 200 OK","thread_id":"worker-1","correlation_id":"req-100","trace_id":"trace-aaa","span_id":"checkout.request","parent_span_id":null,"operation_name":"Checkout Request","service":"api","duration_ms":420}
```

Command:

```bash
logler investigate app.log --correlation req-100 --hierarchy --waterfall
```

## Issues Observed

### 1) Duplicate roots produce repeated nodes and errors

Actual:
- `roots` include `checkout.request`, `inventory.check`, and `payment.process`
- The tree prints `payment.process` and `inventory.check` twice
- `error_nodes` contains `payment.process` twice

Expected:
- Only true root span(s) should be in `roots`
- Child spans appear once, under their parent

Candidate fix:
- When building hierarchy for correlation/trace IDs, select root span IDs
  as those with `parent_span_id` missing or not in the span set.
- Ignore non-span groupings if span IDs are present.

### 2) Bottleneck percentage is wrong (and 0.0% in summaries)

Actual:
- Rust emits `percentage_of_total` based on the sum of all node durations
  (nested durations inflate total).
- Python display expects `percentage`, so CLI prints `0.0%`.

Expected:
- Bottleneck percent should be computed against total request duration.
- CLI should display the correct percent.

Candidate fix:
- Use `total_duration_ms` as denominator in Rust.
- Normalize the key in Python (`percentage` vs `percentage_of_total`).

### 3) Waterfall header uses detection method

Actual:
- Waterfall header prints `Timeline: {'Mixed': ...}`.

Expected:
- Header should show the root span name or ID.

Candidate fix:
- Prefer root node name/id for header; fall back to detection method if needed.

### 4) Error flow analysis duplicates root causes

Actual:
- Root causes list includes `payment.process` twice.

Expected:
- Each node appears once.

Candidate fix:
- Fix root duplication (Issue #1).
- Deduplicate `error_nodes` as a safety net.

### 5) LLM schema `detected_formats` is always `Unknown`

Actual:
- `logler llm schema` reports `detected_formats: {"Unknown": 1.0}` even on JSON logs.

Expected:
- JSON logs should report `Json` (or similar).

Candidate fix:
- Add a `format` attribute to the Python `LogEntry` and populate it in `LogParser`.
  This is separate from hierarchy, but surfaced during the same validation.

## Fixes Implemented (branch: fix/hierarchy-output)

- Roots now filter to true root spans (no parent in the span set) to prevent
  duplicate trees and error_nodes.
- Bottleneck percentage uses `total_duration_ms` and Rust emits `percentage`
  plus `depth`.
- `detection_method` is serialized as a string; `detection_methods` is added
  for detailed method listing.
- `error_nodes` is de-duplicated defensively.
- Waterfall header uses the root span name/id instead of the detection method.
- Python `LogParser` sets `format` so `logler llm schema` reports real formats.
