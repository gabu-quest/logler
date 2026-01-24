# Logler Hierarchy Output Fix Report

Date: 2025-01-22
Branch: fix/hierarchy-output

## Scope
- Fix hierarchy output correctness and serialization consistency.
- Rebuild Rust extension and validate new JSON shape.
- Run linting + full test suite.
- Run a real-world usefulness check on a small trace log.
- Verify install in a clean uv-managed temp environment.

## Environment
- Repo: /home/gabu/projects/logler
- Python venv: /home/gabu/projects/logler/.venv (CPython 3.12.11)
- Rust: cargo 1.90.0
- Tools: maturin 1.10.2, ruff 0.14.7, pytest 9.0.1

## Build / Extension Setup
1) Clean Rust build artifacts to ensure the new Rust hierarchy output schema is compiled:

```
cargo clean -p logler-core -p logler-py
```

Result:
- Removed 1692 files, 553.5MiB total

2) Build + install Rust extension into the repo venv:

```
.venv/bin/maturin develop -m crates/logler-py/Cargo.toml
```

Result:
- Compiled logler-core + logler-py
- Installed editable `logler` into .venv

3) Confirmed Rust extension now emits new fields:

```
.venv/bin/python - <<'PY'
import json
from pathlib import Path
import logler_rs

entries = [
    {"timestamp": "2024-01-15T10:00:00.000Z", "level": "INFO", "message": "root start", "trace_id": "trace-123", "span_id": "span-root"},
    {"timestamp": "2024-01-15T10:00:00.200Z", "level": "INFO", "message": "child start", "trace_id": "trace-123", "span_id": "span-child", "parent_span_id": "span-root"},
    {"timestamp": "2024-01-15T10:00:00.500Z", "level": "ERROR", "message": "child error", "trace_id": "trace-123", "span_id": "span-child", "parent_span_id": "span-root"},
    {"timestamp": "2024-01-15T10:00:00.900Z", "level": "INFO", "message": "child end", "trace_id": "trace-123", "span_id": "span-child", "parent_span_id": "span-root"},
    {"timestamp": "2024-01-15T10:00:01.000Z", "level": "INFO", "message": "root end", "trace_id": "trace-123", "span_id": "span-root"},
]

path = Path('/tmp/logler-hierarchy-debug.jsonl')
path.write_text('\n'.join(json.dumps(e) for e in entries) + '\n', encoding='utf-8')

raw = logler_rs.build_hierarchy([str(path)], 'trace-123', None, False, False, 0.0)
print(raw)
PY
```

Output:
```
{"roots":[{"id":"span-root","node_type":"Span","name":"root start","parent_id":null,"children":[{"id":"span-child","node_type":"Span","name":"child error","parent_id":"span-root","children":[],"entry_ids":["c0beb27b-0bd7-4520-b9cf-467ba351687f","ca6b1b37-f114-49b9-903e-703b632680ef","92a8f908-ade6-45de-b7cc-67674d0a2074"],"start_time":"2024-01-15T10:00:00.200Z","end_time":"2024-01-15T10:00:00.900Z","duration_ms":700,"entry_count":3,"error_count":1,"level_counts":{"ERROR":1,"INFO":2},"depth":1,"confidence":1.0,"relationship_evidence":["explicit_parent_span_id"]}],"entry_ids":["0a410b7c-4b1b-45de-bad2-53364b9aa203","a8307642-5098-45c2-a79b-c8c321b766fb"],"start_time":"2024-01-15T10:00:00Z","end_time":"2024-01-15T10:00:01Z","duration_ms":1000,"entry_count":2,"error_count":0,"level_counts":{"INFO":2},"depth":0,"confidence":0.0,"relationship_evidence":[]}],"total_nodes":2,"max_depth":1,"total_duration_ms":1000,"concurrent_count":0,"bottleneck":{"node_id":"span-root","node_name":"root start","duration_ms":1000,"percentage":100.0,"depth":0},"error_nodes":["span-child"],"detection_method":"ExplicitParentId","detection_methods":["ExplicitParentId"]}
```

Key confirmations:
- `roots` only includes the true root span.
- `error_nodes` is de-duplicated.
- `bottleneck.percentage` is present and correct.
- `detection_method` is a string and `detection_methods` is present.

## Lint
```
.venv/bin/ruff check .
```
Result:
- All checks passed.

## Tests
### Targeted regression
```
.venv/bin/pytest tests/test_hierarchy_rust_output.py -q
```
Result:
- 1 passed

### Full suite (first attempt)
```
.venv/bin/pytest
```
Result:
- 31 failures due to `logler` and `python` not in PATH.
- The failures were environment-only (CLI entrypoint not found).

### Full suite (with PATH fix)
```
PATH="/home/gabu/projects/logler/.venv/bin:$PATH" .venv/bin/pytest
```
Result:
- 593 passed, 10 skipped in 62.01s

## Usefulness Test (Manual)
Created a compact trace-like log:
```
.sandbox/experiments/usefulness.log
```

### 1) Auto-insights
Command:
```
.venv/bin/logler investigate .sandbox/experiments/usefulness.log --auto-insights --output summary
```
Output:
```
🎯 Running automatic insights analysis...

╭──────────────────────────────── 📊 Overview ─────────────────────────────────╮
│ Total Logs: 8                                                                │
│ Error Count: 1                                                               │
│ Error Rate: 12.5%                                                            │
│ Log Levels: {'INFO': 6, 'WARN': 1, 'ERROR': 1}                               │
╰──────────────────────────────────────────────────────────────────────────────╯

💡 Automatic Insights

🔴 Insight #1: high_error_rate
   Severity: HIGH
   Description: High error rate: 12.5% (1/8)
   Suggestion: Investigate most common errors first

🟡 Insight #2: thread_failures
   Severity: MEDIUM
   Description: Errors across 1 different requests
   Suggestion: Compare successful vs failed requests

📝 Suggestions

  1. Start by examining the first error - it may be the root cause
  2. Use follow_thread() to see full request flow

🚀 Next Steps

  1. Run: find_patterns(files, min_occurrences=3)
  2. Use: compare_threads() to find differences
```

### 2) Hierarchy + waterfall + error flow
Command:
```
.venv/bin/logler investigate .sandbox/experiments/usefulness.log --correlation req-42 --hierarchy --waterfall --show-error-flow --output summary
```
Output:
```
🌳 Building hierarchy for correlation: req-42...

=== Thread Hierarchy Summary ===
Total nodes: 4
Max depth: 1
Detection method: Mixed (ExplicitParentId, NamingPattern, TemporalInference)
Total duration: 720ms (0.72s)
Concurrent operations: 2

⚠️  BOTTLENECK DETECTED:
  Node: http.request
  Duration: 720ms (100.0% of total)
  Depth: 0

❌ Errors in 1 node(s):
  - db.query

Tree Structure:
  📁 http.request (2 entries, 3 children)
  ├─ auth.check (2 entries) (70ms)
  ├─ payment.charge (1 entries)
  └─ ❌ db.query (3 entries) (220ms)

📊 Waterfall Timeline

┌───────────────────────────────────────────────────────────────────────────────
───────────────────┐
│ Timeline: HTTP Request (720ms)                                                
│
├───────────────────────────────────────────────────────────────────────────────
───────────────────┤
│ HTTP Request         ████████████████████████████████████████████████████████████████████████   720ms│
│ ├─ Auth Check            ██████                                                70ms│
│ ├─ Charge Payment                                                     █       <1ms│
│ ├─ DB Query                            ████████████████████❌                 220ms│
└───────────────────────────────────────────────────────────────────────────────
───────────────────┘

⚠️  Bottleneck: http.request (720ms, 100.0%)

🔍 Error Flow Analysis

======================================================================
🔍 ERROR FLOW ANALYSIS
======================================================================

Total error nodes: 1
Affected: 25.0% of hierarchy

----------------------------------------------------------------------
🔴 ROOT CAUSE(S)
----------------------------------------------------------------------

  1. db.query (leaf node)
     Type: Span
     Errors: 1
     Depth: 1
     Confidence: 100%
     Time: 2024-01-15T10:00:00.200Z
     Path: http.request → db.query

-----------------------------------------------------------------------
💡 RECOMMENDATIONS
-----------------------------------------------------------------------
  • Investigate db.query first - it appears to be the root cause
  • Error originated at leaf node (depth 1) - check external dependencies

======================================================================
```

## Install Test (uv + temp dir)
### Attempt 1 (default uv Python)
```
uv venv
uv pip install --python .venv/bin/python -e /home/gabu/projects/logler
```
Result: failed because uv selected Python 3.13, but PyO3 0.20.3 only supports up to 3.12.

Error excerpt:
```
error: the configured Python interpreter version (3.13) is newer than
PyO3's maximum supported version (3.12)
```

### Attempt 2 (explicit 3.12)
```
uv venv --python 3.12
uv pip install --python .venv/bin/python -e /home/gabu/projects/logler
.venv/bin/python - <<'PY'
import logler
print("logler version:", logler.__version__)
PY
.venv/bin/logler --version
```
Result:
```
logler version: 1.1.2
logler, version 1.1.2
```

## Known Local-Only Notes
- `uv run ...` reinstalled the old wheel and replaced the fresh Rust extension.
  For local validation, use `.venv/bin/python`, `.venv/bin/pytest`, and `.venv/bin/logler`
  after running `maturin develop`.

## Summary
- Hierarchy JSON output is corrected (roots, bottleneck % key, detection method format).
- Full test suite passes with PATH including `.venv/bin`.
- Lint passes.
- Manual usefulness run shows meaningful insights and readable hierarchy/flow.
- uv install works with explicit Python 3.12.
