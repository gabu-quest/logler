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
top level. The summary is always smaller than full output — designed for LLM context
windows.

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

Returns `{samples, total_population, strategy}`. The `errors_focused` strategy
over-represents error entries relative to their population rate. All strategies
return exactly `sample_size` entries.

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
    print(f"Bottleneck: {hierarchy['bottleneck']['node_id']} took {hierarchy['bottleneck']['duration_ms']}ms")
```

Builds a span tree from `span_id`/`parent_span_id` fields. Returns
`{roots, total_nodes, bottleneck}`. The bottleneck is the node consuming the most
wall-clock time.

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

`print_tree()` renders an ASCII tree with the `THREAD HIERARCHY` header.
`print_waterfall()` renders a timeline with duration bars in milliseconds.

## Return Type Reference

All investigation functions return plain dicts with TypedDict definitions in
`logler.types`. Key shapes:

| Function | Return keys |
|----------|------------|
| `search()` | `results`, `total_matches`, `query` |
| `compare_threads()` | `summary`, `thread_a`, `thread_b`, `differences` |
| `cross_service_timeline()` | `timeline`, `total_entries` |
| `smart_sample()` | `samples`, `total_population`, `strategy` |
| `follow_thread_hierarchy()` | `roots`, `total_nodes`, `bottleneck` |
| `get_hierarchy_summary()` | plain string |

## Additional APIs

These functions are part of the public API but not yet covered by contract tests:

| Function | Purpose |
|----------|---------|
| `extract_ids()` | Find all thread/correlation/trace IDs in log files |
| `follow_thread()` | Reconstruct a single thread's timeline |
| `get_context()` | Get surrounding log lines for a specific entry |
| `find_patterns()` | Detect repeated log patterns with frequency |
| `get_metadata()` | Extract metadata and field statistics |
| `analyze_error_flow()` | Trace error propagation through the hierarchy |
| `extract_metrics()` | Extract numeric values with stats (min/max/mean/p95/p99) |
| `detect_formats()` | Auto-detect log format with confidence scoring |
| `mine_log_templates()` | Drain algorithm template mining |

See `logler.types` for full TypedDict definitions.
