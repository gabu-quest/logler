# API Reference

Tested contracts for logler's public Python API. Each contract ID `[CXX]` has a
corresponding test in `tests/test_readme.py` — CI proves these examples work.

## Contracts

### [C02] Token-efficient search

```python
import logler.investigate as investigate

errors = investigate.search(files=["app.log"], level="ERROR", output_format="summary")
# Returns aggregated stats instead of all entries - perfect for limited context windows
```

`search()` with `output_format="summary"` returns a dict with `total_matches` at the
top level, the count of every match even when `limit` is given. Its other counts
(`log_levels`, `by_file`, `unique_messages`, `top_messages`) are over every match too;
`limit`, `tail` and `offset` choose only the `sample_entries`. In `top_messages` two
messages of equal count come in the order of their first match. The summary is always
smaller than full output — designed for LLM context windows.

### [C03] Compare threads

```python
import logler.investigate as investigate

diff = investigate.compare_threads(
    files=["app.log"],
    correlation_a="req-success-123",
    correlation_b="req-failed-456"
)
print(diff['summary'])  # Comparison of two request flows
```

Returns `{summary, thread_a, thread_b, differences}`. Each thread side includes
`entry_count` and level breakdown.

### [C04] Cross-service timeline

```python
import logler.investigate as investigate

timeline = investigate.cross_service_timeline(
    files={"api": ["api.log"], "db": ["db.log"], "cache": ["cache.log"]},
    correlation_id="req-12345"
)
# See request flow: API → DB → Cache with latency breakdown
```

Pass a dict mapping service names to file lists. Returns `{timeline, total_entries}`
where `timeline` is a list of events ordered by timestamp, each tagged with its service.

### [C05] Investigation sessions

```python
import logler.investigate as investigate

session = investigate.InvestigationSession(files=["app.log"], name="incident_2024")
session.search(level="ERROR")
session.add_note("Database connection pool exhausted")
report = session.generate_report(format="markdown")  # Auto-generate report
```

Sessions track operation history (init, search, note, etc.) with undo/redo support.
`generate_report()` includes session name, search results, and user notes.

### [C06] Smart sampling

```python
import logler.investigate as investigate

sample = investigate.smart_sample(
    files=["huge.log"],
    strategy="errors_focused",  # or "diverse", "representative", "chronological"
    sample_size=50
)
```

Returns `{samples, total_population, sample_size, strategy, coverage}`. The
`errors_focused` strategy over-represents error entries relative to their population
rate. Every strategy returns exactly `sample_size` entries, or every entry when the
files hold fewer.

### [C08] Thread hierarchy

```python
import logler.investigate as investigate

hierarchy = investigate.follow_thread_hierarchy(
    files=["app.log"],
    root_identifier="req-123",
    min_confidence=0.8  # Only show high-confidence relationships
)
# Automatic bottleneck detection
if hierarchy.get('bottleneck'):
    print(f"Bottleneck: {hierarchy['bottleneck']['node_id']} spent {hierarchy['bottleneck']['duration_ms']}ms of its own")
```

Builds a span tree from `span_id`/`parent_span_id` fields, and from naming patterns
and timing where those are missing. Returns `{roots, total_nodes, max_depth,
total_duration_ms, concurrent_count, bottleneck, error_nodes, detection_method,
detection_methods}`. The bottleneck is the node with the most self-time: its duration
less the durations of its direct children. Its `duration_ms` and `percentage` are that
self-time, not the node's whole duration. A node counts its own log lines, each once
(`entry_count`, `error_count`, `level_counts`).

### [C09] Hierarchy summary

```python
import logler.investigate as investigate

# Using hierarchy from [C08]
summary = investigate.get_hierarchy_summary(hierarchy)
print(summary)  # Shows tree structure, errors, bottlenecks
```

Returns a human-readable string describing the hierarchy: node count, structure,
and any detected bottlenecks.

### [C10] Tree visualization

```python
from logler.tree_formatter import print_tree, print_waterfall

# Using hierarchy from [C08]
print_tree(hierarchy, mode="detailed", show_duration=True)
print_waterfall(hierarchy, width=100)  # Waterfall timeline
```

`print_tree()` prints a tree headed `Thread Hierarchy (N nodes, max depth: D, Xms)`.
`format_tree(hierarchy, use_colors=False)` returns the same tree as plain text under a
`THREAD HIERARCHY` banner. `print_waterfall()` renders a timeline with duration bars in
milliseconds.

## Return Type Reference

All investigation functions return plain dicts with TypedDict definitions in
`logler.types`. Key shapes:

| Function | Return keys |
|----------|------------|
| `search()` | `results`, `total_matches`, `search_time_ms` (`query` and `exclude_query` are regexes read without regard to letter case over the whole line and the message; a pattern that is not a regex raises `ValueError`; every result has `relevance_score` 1.0, in time order) |
| `compare_threads()` | `summary`, `thread_a`, `thread_b`, `differences` |
| `cross_service_timeline()` | `timeline`, `services`, `total_entries`, `duration_ms`, `service_breakdown` |
| `smart_sample()` | `samples`, `total_population`, `sample_size`, `strategy`, `coverage` |
| `follow_thread_hierarchy()` | `roots`, `total_nodes`, `max_depth`, `total_duration_ms`, `concurrent_count`, `bottleneck`, `error_nodes`, `detection_method`, `detection_methods` |
| `get_hierarchy_summary()` | plain string |

## Additional APIs

These functions are part of the public API but not yet covered by contract tests:

| Function | Purpose |
|----------|---------|
| `extract_ids()` | Find all thread/correlation/trace IDs in log files. An all-zero trace, span or parent span id (16 or 32 characters of `0`, what OpenTelemetry writes outside a span) means no id and is never listed |
| `follow_thread()` | Reconstruct a single thread's timeline |
| `get_context()` | Get surrounding log lines for a specific entry; a line number the file has no entry for raises `ValueError` |
| `find_patterns()` | Detect repeated log patterns with frequency |
| `get_metadata()` | Extract metadata and field statistics |
| `analyze_thread_health()` (in `logler.helpers`) | Each thread's entry count per level: `{thread_id: {"INFO": 3, "ERROR": 2, "total": 5}}`. Only levels that occur are keys (`UNKNOWN` for an entry with no level); `total` is the thread's number of entries; several files add up; an entry with no thread id is in no thread's counts |
| `analyze_error_flow()` | Trace error propagation through the hierarchy |
| `extract_metrics()` | Extract numeric values with stats (min/max/mean/p95/p99) |
| `detect_formats()` | Auto-detect log format with confidence scoring |
| `mine_log_templates()` | Drain algorithm template mining |
| `export_to_jaeger()`, `export_to_zipkin()`, `export_to_otlp()` | A hierarchy as a Jaeger, Zipkin V2 or OTLP JSON trace. Arguments: `hierarchy`, `service_name` (default `logler-export`), `identifier`. A span is under its node's `service` (the `service_name` of the first of the node's entries that has one), else under `service_name`. With `identifier=` the trace id is made from it; an id that is all zeros is never kept |

See `logler.types` for full TypedDict definitions.
