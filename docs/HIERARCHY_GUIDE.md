# Thread Hierarchy Detection & Visualization Guide

This guide covers logler's hierarchical thread/span visualization system for debugging async, concurrent, and distributed systems.

## Table of Contents

1. [Overview](#overview)
2. [Log Format Requirements](#log-format-requirements)
3. [Detection Methods](#detection-methods)
4. [CLI Usage](#cli-usage)
5. [Python API](#python-api)
6. [Visualization Modes](#visualization-modes)
7. [Error Flow Analysis](#error-flow-analysis)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

---

## Overview

Logler's hierarchy detection builds parent-child relationship trees from your logs, enabling:

- **Visual debugging** of async/concurrent code execution flow
- **Distributed tracing** across microservices
- **Bottleneck identification** in request pipelines
- **Error root cause analysis** with propagation tracking
- **Performance optimization** through critical path analysis

### What You Get

```
🧵 api-gateway (req-001, 520ms)
├─ 🔹 auth-service (45ms)
│  ├─ 🔸 jwt-validate (5ms)
│  └─ 🔸 user-lookup (25ms)
├─ 🔹 product-service (450ms) ⚠️ BOTTLENECK
│  ├─ 🔸 inventory-check (340ms)
│  │  └─ 🔸 db-query (300ms)
│  └─ 🔸 cache-update (45ms) ❌ ERROR
└─ 🔹 response-assembly (10ms)
```

---

## Log Format Requirements

### Perfect Format (100% Accurate Detection)

For guaranteed accurate hierarchy detection, include `parent_span_id`:

```json
{
  "timestamp": "2024-01-15T10:00:00.123Z",
  "level": "INFO",
  "message": "Processing request",
  "thread_id": "worker-1",
  "correlation_id": "req-abc123",
  "trace_id": "trace-xyz789",
  "span_id": "span-001",
  "parent_span_id": "span-000"
}
```

### OpenTelemetry Compatibility

Logler recognizes standard OpenTelemetry fields:

| Field | Purpose |
|-------|---------|
| `trace_id` | Groups all spans in a trace |
| `span_id` | Unique identifier for this operation |
| `parent_span_id` | Links to parent operation |

### Minimum Requirements

At minimum, include one of these identifier pairs:

1. **Span-based**: `span_id` + `parent_span_id` (best)
2. **Thread-based**: `thread_id` with naming patterns like `worker-1.task-a`
3. **Correlation-based**: `correlation_id` for request-level grouping

---

## Detection Methods

Logler uses three detection strategies, in order of confidence:

### 1. Explicit Parent ID (Confidence: 1.0)

```json
{"span_id": "child", "parent_span_id": "parent"}
```

This is the gold standard - 100% accurate, no inference needed.

### 2. Naming Patterns (Confidence: 0.8)

Logler detects parent-child relationships from thread naming conventions:

| Pattern | Example | Detection |
|---------|---------|-----------|
| Dot-separated | `worker-1.task-a` | `worker-1` → `worker-1.task-a` |
| Colon-separated | `main:subtask-1` | `main` → `main:subtask-1` |
| Dash-separated | `req-123-auth` | `req-123` → `req-123-auth` |

### 3. Temporal Inference (Confidence: 0.6)

When a log entry appears within ~1 second after another with no explicit relationship, logler may infer a parent-child relationship based on timing.

### Viewing Detection Confidence

```bash
# Show confidence scores in output
logler investigate app.log --hierarchy --correlation req-123
```

In the tree output, nodes show their relationship evidence:
```
├─ db-query (confidence=1.0, evidence=["Explicit parent_span_id"])
├─ cache-task (confidence=0.8, evidence=["Naming pattern: dot-separated"])
```

---

## CLI Usage

### Basic Hierarchy View

```bash
# Show hierarchy for a correlation ID
logler investigate app.log --correlation req-123 --hierarchy

# Show hierarchy for a thread
logler investigate app.log --thread worker-1 --hierarchy

# Show hierarchy for a trace
logler investigate app.log --trace trace-abc123 --hierarchy
```

### Visualization Modes

```bash
# Tree view (default)
logler investigate app.log --correlation req-123 --hierarchy

# Waterfall timeline
logler investigate app.log --correlation req-123 --hierarchy --waterfall

# Flamegraph (performance view)
logler investigate app.log --correlation req-123 --hierarchy --flamegraph

# Error flow analysis
logler investigate app.log --hierarchy --show-error-flow
```

### Filtering Options

```bash
# Limit depth
logler investigate app.log --hierarchy --max-depth 3

# Filter by confidence
logler investigate app.log --hierarchy --min-confidence 0.8

# Combined
logler investigate app.log --correlation req-123 --hierarchy --waterfall --max-depth 5
```

### Output Formats

```bash
# JSON output for automation
logler investigate app.log --hierarchy --correlation req-123 --json

# Summary output (token-efficient for LLMs)
logler investigate app.log --hierarchy --output summary
```

---

## Python API

### Building Hierarchies

```python
import logler.investigate as investigate

# Build hierarchy from files
hierarchy = investigate.follow_thread_hierarchy(
    files=["app.log", "service.log"],
    root_identifier="req-123",  # correlation_id, trace_id, or thread_id
    max_depth=10,
    use_naming_patterns=True,
    use_temporal_inference=True,
    min_confidence=0.5
)

print(f"Total nodes: {hierarchy['total_nodes']}")
print(f"Max depth: {hierarchy['max_depth']}")
print(f"Detection method: {hierarchy['detection_method']}")

# Check for bottleneck
if hierarchy.get('bottleneck'):
    bn = hierarchy['bottleneck']
    print(f"Bottleneck: {bn['node_id']} ({bn['duration_ms']}ms)")
```

### Formatting Output

```python
from logler.tree_formatter import format_tree, format_waterfall, format_flamegraph

# Tree view
tree = format_tree(hierarchy, mode="detailed", show_duration=True)
print(tree)

# Waterfall timeline
waterfall = format_waterfall(hierarchy, width=100)
print(waterfall)

# Flamegraph
flamegraph = format_flamegraph(hierarchy, width=100, use_colors=True)
print(flamegraph)
```

### Error Flow Analysis

```python
# Analyze error propagation
error_analysis = investigate.analyze_error_flow(hierarchy)

# Get root causes
for cause in error_analysis['root_causes']:
    print(f"Root cause: {cause['node_id']}")
    print(f"  Path: {' -> '.join(cause['path'])}")
    print(f"  Confidence: {cause['confidence']*100:.0f}%")

# Get impact summary
impact = error_analysis['impact_summary']
print(f"Affected nodes: {impact['total_affected_nodes']}")
print(f"Affected percentage: {impact['affected_percentage']:.1f}%")

# Get recommendations
for rec in error_analysis['recommendations']:
    print(f"  - {rec}")
```

### Performance Analysis

```python
# Analyze performance
perf = investigate.analyze_hierarchy_performance(hierarchy)

# Critical path
for node in perf['critical_path']:
    print(f"{node['id']}: {node['duration_ms']}ms ({node['percentage']:.1f}%)")

# Parallelization opportunities
for opp in perf['parallelization_opportunities']:
    print(f"Can parallelize: {opp['nodes']}")
    print(f"Potential savings: {opp['potential_savings_ms']}ms")

# Optimization suggestions
for suggestion in perf['optimization_suggestions']:
    print(f"  - {suggestion}")
```

### Using InvestigationSession

```python
session = investigate.InvestigationSession(files=["app.log"], name="incident")

# Build and explore hierarchy
session.build_hierarchy(root_identifier="req-123")
hierarchy = session.current_hierarchy

# Add notes during investigation
session.add_note("Database connection pool was exhausted")

# Generate report with hierarchy visualization
report = session.generate_report(format="markdown")
```

---

## Visualization Modes

### Tree View

Best for understanding structure and parent-child relationships.

```
THREAD HIERARCHY
======================================================================
Total nodes: 8
Max depth: 3
Detection: ExplicitParentId
Total duration: 520ms

⚠️  BOTTLENECK: product-service (450ms, 86.5%)
❌ 1 node(s) with errors
----------------------------------------------------------------------

└── api-gateway (10 entries, 520ms)
    ├── auth-service (5 entries, 45ms)
    │   ├── jwt-validate (2 entries, 5ms)
    │   └── user-lookup (3 entries, 25ms)
    ├── ❌ [1 errors] product-service (8 entries, 450ms)
    │   ├── inventory-check (4 entries, 340ms)
    │   │   └── db-query (2 entries, 300ms)
    │   └── cache-update (2 entries, 45ms)
    └── response-assembly (3 entries, 10ms)
======================================================================
```

### Waterfall View

Best for seeing temporal relationships and parallel execution.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Timeline: req-001 (520ms)                                            │
├──────────────────────────────────────────────────────────────────────┤
│ api-gateway          ████████████████████████████████████████  520ms │
│   ├─ auth-service    ████                                      45ms │
│   ├─ product-service      ████████████████████████████████    450ms │
│   │  ├─ inventory              ██████████████████████         340ms │
│   │  └─ cache-update                              ████❌        45ms │
│   └─ response                                          ██      10ms │
└──────────────────────────────────────────────────────────────────────┘

⚠️  Bottleneck: product-service (450ms, 86.5% of total)
```

### Flamegraph View

Best for identifying which operations consume the most time.

```
======================================================================
🔥 FLAMEGRAPH VISUALIZATION
======================================================================
Total Duration: 520ms

┌────────────────────────────────────────────────────────────────────┐
│ api-gateway (520ms)                                                │
├───────────┬────────────────────────────────────────────────────────┤
│ auth (45) │ ⚠ product-service (450ms)                              │
│           ├─────────────────────────────┬──────────────────────────┤
│           │ inventory-check (340ms)     │ cache-update (45ms) ❌   │
└───────────┴─────────────────────────────┴──────────────────────────┘

Legend:
  ⚠ = Bottleneck   Red = Error
  Width proportional to duration
```

---

## Error Flow Analysis

### Understanding Error Propagation

Error flow analysis traces how errors cascade through your system:

```
🔍 Error Flow Analysis

Root Causes (ordered by likelihood):
  1. cache-update (Leaf node)
     Type: Span
     Errors: 2
     Depth: 3
     Confidence: 100%
     Timestamp: 2024-01-15T10:00:00.450Z
     Path: api-gateway → product-service → cache-update

Propagation Chains:
  Chain 1: cache-update → product-service
    Total affected: 2 nodes
    Propagation type: upward

Impact Summary:
  Total affected nodes: 3
  Affected percentage: 37.5%
  Max propagation depth: 2
  Concurrent failures: 0

Recommendations:
  - Primary root cause: cache-update (100% confidence)
  - Error originated at leaf node (depth 3) - check external dependencies
  - Chain involves 2 nodes - consider adding circuit breakers
```

### Using Error Flow in Code

```python
error_analysis = investigate.analyze_error_flow(hierarchy)

# Check if there are errors
if error_analysis['has_errors']:
    # Get the primary root cause
    primary = error_analysis['root_causes'][0]
    print(f"Root cause: {primary['node_id']}")

    # Check propagation
    for chain in error_analysis['propagation_chains']:
        print(f"Error propagated from {chain['root_cause']} to {chain['total_affected']} nodes")
```

---

## Best Practices

### 1. Use OpenTelemetry-Style Logging

```python
import logging
import uuid

class SpanContext:
    def __init__(self, parent=None):
        self.trace_id = parent.trace_id if parent else uuid.uuid4().hex[:32]
        self.span_id = uuid.uuid4().hex[:16]
        self.parent_span_id = parent.span_id if parent else None

# Usage
root_span = SpanContext()
child_span = SpanContext(parent=root_span)

logger.info("Starting operation", extra={
    "trace_id": child_span.trace_id,
    "span_id": child_span.span_id,
    "parent_span_id": child_span.parent_span_id
})
```

### 2. Consistent Thread Naming

If you can't use span IDs, use hierarchical thread naming:

```python
# Good: Hierarchical naming
thread_name = f"{parent_thread}.{task_name}"  # "worker-1.db-query"

# Good: Colon-separated
thread_name = f"{service}:{operation}"  # "auth:validate-jwt"

# Bad: Random names
thread_name = "Thread-42"  # No relationship detectable
```

### 3. Include Correlation IDs

Always include a correlation ID to group related log entries:

```python
request_id = str(uuid.uuid4())[:8]

# All logs for this request include the same correlation_id
logger.info("Request started", extra={"correlation_id": f"req-{request_id}"})
```

### 4. Log Span Boundaries

Log at the start and end of operations:

```python
logger.info("Starting database query", extra={"span_id": span.span_id})
# ... do work ...
logger.info("Database query complete", extra={
    "span_id": span.span_id,
    "duration_ms": elapsed
})
```

---

## Troubleshooting

### "No hierarchy detected"

**Cause**: Logs don't contain relationship information.

**Fix**:
1. Add `parent_span_id` to your logs
2. Use hierarchical thread naming
3. Lower `min_confidence` to include temporal inference

```bash
logler investigate app.log --hierarchy --min-confidence 0.0
```

### "Too many root nodes"

**Cause**: Logs from multiple requests are mixed together.

**Fix**: Filter by correlation ID or trace ID:

```bash
logler investigate app.log --correlation req-123 --hierarchy
```

### "Hierarchy is too deep to display"

**Fix**: Use `--max-depth` to limit display:

```bash
logler investigate app.log --hierarchy --max-depth 5
```

### "Low confidence relationships"

**Cause**: Using temporal or naming inference.

**Fix**:
1. Add explicit `parent_span_id` to logs
2. Filter by confidence:

```bash
logler investigate app.log --hierarchy --min-confidence 0.8
```

### "Waterfall shows no timing"

**Cause**: Logs missing timestamps or duration information.

**Fix**: Ensure logs include ISO 8601 timestamps:

```json
{"timestamp": "2024-01-15T10:00:00.123Z", ...}
```

---

## Further Reading

- [Perfect Log Format](../README.md#-perfect-log-format-for-maximum-features) - Optimal log structure
- [LLM Investigation API](./LLM_INVESTIGATION_API.md) - Complete API reference
- [Examples](../examples/en/15_hierarchy_visualization.py) - Working code examples
