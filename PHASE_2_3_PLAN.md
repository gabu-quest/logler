# Logler Quality Fix Plan - Phase 2 & 3

This document captures the remaining work from the Logler Quality Fix Plan.
Phase 1 (Python-only fixes) has been completed.

## Context

Logler is an LLM-first log analysis CLI tool. The primary use case is for AI agents
to analyze logs via the CLI. The Python library and marimo UI are secondary.

**Core Problem Still Outstanding**: Duration is calculated from timestamps instead
of the `duration_ms` field in Rust. This causes 0ms durations everywhere, breaking
flamegraphs, waterfalls, bottleneck detection, etc.

---

## Phase 2: Rust Changes + Blocked Python

These fixes require modifying the Rust codebase.

### 2.1 Fix Duration Calculation (Rust) - HIGH PRIORITY

**File**: `crates/logler-core/src/hierarchy.rs`

Modify `build_node()` function to:
1. **First**: Check `entry.fields["duration_ms"]` for explicit duration
2. **Fallback**: Only calculate from timestamps if field missing

**Current behavior** (broken):
```rust
// Duration is always calculated from end_time - start_time
let duration_ms = (end_time - start_time).as_millis();
```

**Expected behavior**:
```rust
// Prefer explicit duration_ms field from log entry
let duration_ms = entry.fields.get("duration_ms")
    .and_then(|v| v.as_u64())
    .unwrap_or_else(|| {
        // Fallback to timestamp calculation
        (end_time - start_time).as_millis() as u64
    });
```

**Impact**: Fixes flamegraphs, waterfalls, bottleneck detection globally.

### 2.2 Fix Entry Deduplication (Rust)

**File**: `crates/logler-py/src/investigate.rs`

When multiple IDs (correlation_id, trace_id, thread_id) match the same log entry,
the entry appears multiple times in results.

**Fix**: Deduplicate entries by `(file_path, line_number)` tuple before returning.

```rust
// After collecting entries, dedupe by location
let mut seen: HashSet<(String, u32)> = HashSet::new();
entries.retain(|entry| {
    let key = (entry.file.clone(), entry.line_number);
    seen.insert(key)
});
```

**Workaround applied**: `cross_service_timeline()` in Python now only passes
ONE of correlation_id/trace_id to avoid duplication (Phase 1 fix).

### 2.3 Expand Name Extraction (Rust)

**File**: `crates/logler-core/src/hierarchy.rs`

The `infer_node_name()` function should check more fields for readable names.

**Current** checks:
1. `operation_name`
2. `name`

**Should also check**:
3. First line of `message` field (new)
4. `service` field (new fallback)

```rust
fn infer_node_name(entry: &LogEntry) -> Option<String> {
    // Existing checks
    if let Some(name) = entry.fields.get("operation_name") {
        return Some(name.as_str()?.to_string());
    }
    if let Some(name) = entry.fields.get("name") {
        return Some(name.as_str()?.to_string());
    }

    // NEW: Extract from message first line
    if let Some(msg) = &entry.message {
        let first_line = msg.lines().next()?;
        if first_line.len() < 50 {
            return Some(first_line.to_string());
        }
    }

    // NEW: Fallback to service name
    if let Some(service) = entry.fields.get("service") {
        return Some(service.as_str()?.to_string());
    }

    None
}
```

### 2.4 Fix Coverage Metrics (Rust)

**Issue**: `smart_sample()` returns "0 unique threads" even when threads exist.

**File**: Likely `crates/logler-core/src/sampling.rs` or similar.

**Investigation needed**:
1. Check how thread_id extraction works in sampling
2. Verify thread_id is being populated correctly
3. Fix counting logic

---

## Phase 3: Tour Rewrites

All 14 marimo tours need rewriting to:
- Use `operation_name` field for readable labels
- Include ERROR logs where error detection is demoed
- Explain OpenTelemetry conventions
- Explain Jaeger/Zipkin formats
- Actually teach useful things
- Fix tour_12 duplication issue

### Tour Files

| Tour | File | Focus |
|------|------|-------|
| 01 | `tour_01_fundamentals.py` | Basic concepts |
| 02 | `tour_02_*.py` | - |
| 03 | `tour_03_*.py` | - |
| 04 | `tour_04_investigation.py` | Investigation workflow |
| 05 | `tour_05_patterns.py` | Pattern detection |
| 06 | `tour_06_flamegraph.py` | Flamegraph visualization |
| 07 | `tour_07_error_flow.py` | Error flow analysis |
| 08 | `tour_08_comparison.py` | Log comparison |
| 09 | `tour_09_tracing_exports.py` | Trace exports |
| 10 | `tour_10_sampling.py` | Sampling strategies |
| 11 | `tour_11_ai_insights.py` | AI insights |
| 12 | `tour_12_multi_file_interleaving.py` | Multi-file (has duplication bug) |
| 13 | `tour_13_live_watching.py` | Live log watching |
| 14 | `tour_14_performance.py` | Performance analysis |

### Tour Guidelines

Each tour should:

1. **Generate realistic sample data** with:
   - `operation_name` / `name` fields for readability
   - `duration_ms` fields with realistic values
   - Mix of log levels including ERROR
   - Proper trace/span IDs

2. **Explain conventions**:
   - What OpenTelemetry fields mean
   - Why span IDs matter
   - How correlation IDs connect requests

3. **Show practical workflows**:
   - How an LLM agent would use these tools
   - What questions each feature answers
   - When to use which visualization

4. **Fix tour_12 duplication**: The multi-file interleaving tour shows
   duplicate entries - this is the Rust deduplication bug manifesting.

---

## Implementation Order (Recommended)

1. **2.1 Duration Calculation** - Highest impact, enables all timing features
2. **2.2 Entry Deduplication** - Removes Python workaround, cleaner output
3. **2.3 Name Extraction** - Better display names
4. **2.4 Coverage Metrics** - Quality of life
5. **Phase 3 Tours** - Documentation/education

---

## Verification Steps

After Phase 2 Rust changes:

```bash
# Build Rust extension
maturin develop --release

# Run tests
uv run pytest

# Manual verification
uv run logler llm hierarchy trace-xyz --files test.log --pretty
# Should show non-zero duration_ms values

uv run logler llm bottleneck trace-xyz --files test.log --pretty
# Should identify actual bottlenecks
```

After Phase 3 Tour rewrites:

```bash
# Run each tour in marimo
uv run marimo edit examples/tours/tour_01_fundamentals.py
# Verify sample data has proper fields
# Verify visualizations show meaningful data
```

---

## Files Modified in Phase 1 (Completed)

| File | Changes |
|------|---------|
| `src/logler/models.py` | NEW - Pydantic models for type safety |
| `src/logler/investigate.py` | Deduplication workaround |
| `src/logler/tree_formatter.py` | Name-first display, 0ms handling |
| `src/logler/llm_cli.py` | sql, bottleneck, context, export commands |
| `src/logler/__init__.py` | Export Pydantic models |
| `pyproject.toml` | Add pydantic dependency |

---

## Notes

- **Breaking changes OK**: No backwards compatibility needed
- **CLI is first-class**: Optimize for AI agent usage
- **Tests must pass**: All changes should have test coverage
- **Rust session separate**: Don't modify Rust in same session as Python
