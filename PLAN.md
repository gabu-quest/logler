# Logler Quality Audit & Fix Plan

## Executive Summary

Logler has significant quality issues affecting most features. The marimo tours expose these bugs clearly:
- **Flamegraph/waterfall show useless output** (0ms durations, truncated names)
- **Error detection doesn't work** (no errors found when errors exist)
- **Timeline duplicates entries** (tour 12 "killer feature")
- **Everything uses dicts** (no Python type safety)
- **CLI missing ~30% of features**

**Root cause**: The Rust hierarchy builder calculates duration from `(end_timestamp - start_timestamp)` instead of reading the `duration_ms` field from log entries. Since most spans have only one log entry, `start == end` → **0ms duration everywhere**.

---

## Issues by Severity

### 🔴 Critical (Breaks Core Functionality)

#### 1. Duration Calculation Bug
**Location**: `crates/logler-core/src/hierarchy.rs:539-547`

**Problem**:
```rust
fn calculate_duration(&self, start: &Option<DateTime<Utc>>, end: &Option<DateTime<Utc>>) -> Option<i64> {
    match (start, end) {
        (Some(s), Some(e)) => Some(e.timestamp_millis() - s.timestamp_millis()),
        _ => None,
    }
}
```

When a span has ONE log entry, `start_time == end_time` → duration = 0ms.
The `duration_ms` field in log JSON is **ignored**.

**Impact**:
- All bottleneck detection returns 0%
- Waterfall shows empty (skips 0ms nodes)
- Flamegraph bars have no width
- All timing analysis is broken

**Fix**: Check `entry.fields["duration_ms"]` before calculating from timestamps.

---

#### 2. Tour 12 Entry Duplication
**Location**: `crates/logler-py/src/investigate.rs:236-244`

**Problem**:
```rust
if let Some(ref cid) = correlation_id {
    all_entries.extend(index.get_correlation_entries(cid));
}
if let Some(ref tid) = trace_id {
    all_entries.extend(index.get_trace_entries(tid));  // Same entries added again!
}
```

When both IDs match the same entries, they're added twice.

**Impact**: Timeline shows every line doubled, embarrassing for "killer feature"

**Fix**: Deduplicate by (file, line_number) before returning.

---

### 🟠 High (Significantly Degrades UX)

#### 3. Name Extraction Too Narrow
**Location**: `crates/logler-core/src/hierarchy.rs:502-515`

**Problem**: Only checks `operation_name` and `name` fields for node labels.

**Impact**: Tree/flamegraph shows ugly `span-fraud`, `span-inv-db` instead of readable names.

**Fix**: Also check `message` and `service` fields as fallback.

---

#### 4. Visualization Inconsistencies
**Locations**:
- `src/logler/tree_formatter.py:706` - flamegraph uses `id` not `name`
- `src/logler/tree_formatter.py:309` - Rich tree uses `id` not `name`
- `src/logler/tree_formatter.py:528-537` - waterfall skips 0ms nodes

**Problem**: ASCII tree correctly uses `node.get("name") or node.get("id")`, but other formatters don't.

**Fix**: Standardize all formatters to prefer `name` over `id`.

---

#### 5. Tour Sample Data Missing Required Fields
**Location**: All tour files in `examples/tours/`

**Problem**: Tours use `service` field but not `operation_name`. Without `operation_name`, visualizations show span IDs.

**Fix**: Add `operation_name` to all sample data (already done for tour_03, need others).

---

### 🟡 Medium (Quality Issues)

#### 6. No Python Type Definitions
**Problem**: All API functions return `Dict[str, Any]`. No TypedDict, Pydantic, or dataclasses.

**Impact**: No IDE autocomplete, runtime errors instead of type errors.

**Fix**: Add `src/logler/types.py` with TypedDict definitions mirroring Rust types.

---

#### 7. CLI Missing Features
**Missing from CLI**:
- SQL query engine (`sql.py` not exposed at all!)
- `analyze_bottlenecks()`
- `diff_hierarchies()`
- `compare_threads()`
- `export_to_jaeger()` / `export_to_zipkin()`
- `get_context()`

**Fix**: Add CLI commands for these functions, especially SQL queries.

---

#### 8. Tour 10 Coverage Bug
**Problem**: Shows "Thread coverage: 0 unique threads" despite sample data having threads.

**Location**: Coverage calculation in `smart_sample` function.

**Fix**: Investigate and fix coverage metrics calculation.

---

### 🟢 Low (Polish)

#### 9. Tours Need Better Explanations
- What are Jaeger/Zipkin formats? (tour 09)
- Tour names aren't descriptive for real users
- Some tours are "godlike" but teach nothing useful

#### 10. README Gaps
- SQL query engine not documented
- LLM CLI subcommands under-documented
- `Investigator` class barely mentioned

---

## Implementation Plan

### Phase 1: Fix Core Duration Bug (Critical)
**Files**: `crates/logler-core/src/hierarchy.rs`

1. Modify `build_node()` to check `entry.fields["duration_ms"]` first
2. Fall back to timestamp calculation only if field missing
3. Update `calculate_time_range()` to extract duration from fields
4. Add tests for single-entry spans with duration_ms

**Estimated effort**: 2-3 hours (Rust changes + rebuild)

### Phase 2: Fix Entry Duplication (Critical)
**Files**: `crates/logler-py/src/investigate.rs`

1. Add deduplication by (file, line_number) after collecting entries
2. Alternatively: only use one ID type at a time (simpler)

**Estimated effort**: 1 hour

### Phase 3: Fix Name Extraction (High)
**Files**: `crates/logler-core/src/hierarchy.rs`

1. Expand `infer_node_name()` to check:
   - `operation_name` (current)
   - `name` (current)
   - Extract from `message` field (new)
   - Use `service` field as last resort (new)

**Estimated effort**: 1-2 hours

### Phase 4: Fix Visualization Consistency (High)
**Files**: `src/logler/tree_formatter.py`

1. Update `format_flamegraph()` to use `name` field
2. Update Rich tree formatter to use `name` field
3. Update waterfall to handle 0ms nodes gracefully (show but mark)

**Estimated effort**: 1 hour

### Phase 5: Update All Tours (High)
**Files**: `examples/tours/tour_*.py`

1. Add `operation_name` field to all sample data
2. Add ERROR level logs where error detection is demoed
3. Fix tour_12 to not pass both correlation_id and trace_id
4. Add explanations for Jaeger/Zipkin formats
5. Make tours actually teach useful things

**Estimated effort**: 4-6 hours

### Phase 6: Add Python Types (Medium)
**Files**: New `src/logler/types.py`, update `investigate.py`

1. Create TypedDict definitions for all return types
2. Update function signatures to use typed returns
3. Export types from `__init__.py`

**Estimated effort**: 3-4 hours

### Phase 7: CLI Enhancements (Medium)
**Files**: `src/logler/cli.py`, `src/logler/llm_cli.py`

1. Add `logler sql` command for SQL queries
2. Add `logler bottleneck` command
3. Add `logler export --format jaeger|zipkin`
4. Document all LLM CLI commands in README

**Estimated effort**: 4-6 hours

### Phase 8: Documentation (Low)
**Files**: `README.md`, tour docstrings

1. Document SQL query engine
2. Expand CLI documentation
3. Add "When to use" guidance for each feature
4. Improve tour explanations

**Estimated effort**: 2-3 hours

---

## Priority Order

1. **Phase 1** - Without this, nothing works (durations all 0)
2. **Phase 2** - Killer feature is embarrassing
3. **Phase 3+4** - Visualizations become useful
4. **Phase 5** - Tours actually teach
5. **Phase 6+7+8** - Polish

---

## Questions for User

1. **Rust changes**: Are you comfortable modifying the Rust codebase, or should fixes be Python-only workarounds?

2. **Type system**: Do you want full Pydantic models (runtime validation, new dependency) or just TypedDict (type hints only, no deps)?

3. **CLI priority**: Is SQL query exposure high priority for LLM usage?

4. **Tours scope**: Should we rewrite all 14 tours, or just fix the broken ones (3, 6, 7, 8, 10, 12)?

5. **Breaking changes**: Is a v2.0 with breaking API changes acceptable, or must everything be backward compatible?
