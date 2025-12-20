# 🌳 Sub-Threads & Hierarchical Visualization - Implementation Plan

**Status**: 🎯 Planning Phase
**Started**: 2024-12-20
**Goal**: Add hierarchical thread/span visualization to Logler for debugging async, concurrent, and distributed systems

---

## 🎯 Feature Overview

**What**: Visualize parent-child relationships between threads, spans, tasks, and requests in a tree structure.

**Why**:
- Debug async/concurrent code (Python asyncio, Go goroutines, etc.)
- Trace microservice call chains
- Understand nested transactions
- Identify bottlenecks in distributed systems

**How**: Detect hierarchies from OpenTelemetry spans, correlation IDs, thread naming patterns, and temporal proximity.

---

## 📋 Implementation Phases

### Phase 1: Core Detection & Data Structures ✅

**Goal**: Build the foundation for detecting and representing hierarchies

- [x] **1.1** Add hierarchy detection to Rust parser ✅
  - [x] Parse `parent_span_id` from OpenTelemetry logs (already in LogEntry!)
  - [x] Parse `parent_thread_id` or similar custom fields
  - [x] Detect thread naming patterns (`worker-1.task-a`, `main:subtask-1`)
  - [x] Create `SpanHierarchy` struct in Rust → `ThreadHierarchy`
  - [x] Build parent-child index during parsing → `HierarchyBuilder`

- [x] **1.2** Add hierarchy data structures to Rust ✅
  - [x] `SpanNode` with full metadata (duration, errors, confidence, evidence)
  - [x] `ThreadHierarchy` with statistics (depth, concurrent count, bottleneck)
  - [x] `HierarchyBuilder` for efficient tree construction
  - [x] `HierarchyConfig` for fine-grained control
  - [x] `DetectionMethod` enum (Explicit, NamingPattern, Temporal, Mixed)
  - [x] Confidence scoring (1.0 for explicit, 0.8 for naming, 0.6 for temporal)

- [x] **1.3** Expose hierarchy building to Python API ✅
  - [x] Add `build_hierarchy()` method to PyInvestigator
  - [x] Add standalone `build_hierarchy()` function
  - [x] Serialize hierarchy as JSON for Python consumption
  - [x] Full configuration options (max_depth, naming_patterns, temporal_inference, min_confidence)

- [ ] **1.4** Write unit tests for hierarchy detection
  - [ ] Test OpenTelemetry span relationships
  - [ ] Test thread naming pattern detection
  - [ ] Test nested transaction detection
  - [ ] Test edge cases (orphaned spans, cycles, missing parents)

**Files modified**:
- ✅ `crates/logler-core/src/hierarchy.rs` (NEW - 730+ lines)
- ✅ `crates/logler-core/src/lib.rs` (added hierarchy module)
- ✅ `crates/logler-core/src/investigate.rs` (added build_hierarchy method)
- ✅ `crates/logler-py/src/lib.rs` (Python bindings)
- ⏳ `tests/test_hierarchy_detection.py` (TODO)

**Commit**: `005eb03` - Rust hierarchy detection implementation complete!

---

### Phase 2: Python API ⏳

**Goal**: Provide Python API for querying hierarchies

- [ ] **2.1** Add `follow_thread_hierarchy()` function
  ```python
  def follow_thread_hierarchy(
      files: List[str],
      thread_id: Optional[str] = None,
      correlation_id: Optional[str] = None,
      trace_id: Optional[str] = None,
      max_depth: int = 10,
      include_siblings: bool = False,
  ) -> Dict[str, Any]:
      """
      Follow a thread and return hierarchical structure.

      Returns:
          {
              "root": {
                  "id": "worker-1",
                  "type": "thread",
                  "duration_ms": 1200,
                  "entries": 15,
                  "errors": 2,
                  "children": [
                      {
                          "id": "span-001",
                          "name": "auth-check",
                          "duration_ms": 5,
                          "entries": 3,
                          "children": [...]
                      }
                  ]
              },
              "total_depth": 4,
              "total_nodes": 12
          }
      """
  ```

- [ ] **2.2** Add `get_hierarchy_summary()` function
  ```python
  def get_hierarchy_summary(
      files: List[str],
      thread_id: str
  ) -> Dict[str, Any]:
      """
      Get quick summary of thread hierarchy.

      Returns:
          {
              "depth": 4,
              "total_spans": 12,
              "parallel_spans": 3,
              "longest_path_ms": 1200,
              "bottleneck": "db-query (850ms)"
          }
      """
  ```

- [ ] **2.3** Add hierarchy support to `InvestigationSession`
  - [ ] Add `session.view_hierarchy()` method
  - [ ] Include hierarchy in session reports

- [ ] **2.4** Write Python API tests
  - [ ] Test hierarchy following
  - [ ] Test max_depth limiting
  - [ ] Test summary generation

**Files to modify**:
- `src/logler/investigate.py`
- `tests/test_hierarchy_api.py` (new)
- `examples/en/08_hierarchy_investigation.py` (new example)

---

### Phase 3: CLI Visualization ⏳

**Goal**: Beautiful terminal output for hierarchies

- [ ] **3.1** Add `--hierarchy` flag to `investigate` command
  ```bash
  logler investigate app.log --thread worker-1 --hierarchy
  logler investigate app.log --correlation req-123 --hierarchy
  logler investigate app.log --trace-id abc123 --hierarchy --max-depth 5
  ```

- [ ] **3.2** Implement tree formatter
  ```python
  # Output example:
  🧵 worker-1 (15 logs, 1.2s, 2 errors)
  ├─ 🔹 auth-check (3 logs, 5ms)
  │  └─ 🔸 token-validate (2 logs, 2ms)
  ├─ 🔹 db-query (8 logs, 850ms) ⚠️ SLOW
  │  ├─ 🔸 pool-acquire (2 logs, 50ms)
  │  └─ 🔸 query-execute (4 logs, 780ms) 🔴 ERROR
  └─ 🔹 response-build (4 logs, 10ms)
  ```

- [ ] **3.3** Add color coding
  - [ ] Green: Fast spans (< 10ms)
  - [ ] Yellow: Slow spans (> 100ms)
  - [ ] Red: Errors in span
  - [ ] Dim: Trace/debug level only

- [ ] **3.4** Add summary line
  ```
  Summary: 3 sub-threads, max depth 3, bottleneck: db-query (850ms)
  ```

**Files to modify**:
- `src/logler/cli.py`
- `src/logler/formatters.py` (new - tree formatting logic)

---

### Phase 4: Waterfall Visualization ⏳

**Goal**: ASCII timeline showing parallel execution

- [ ] **4.1** Add `--waterfall` flag
  ```bash
  logler investigate app.log --thread worker-1 --waterfall
  ```

- [ ] **4.2** Implement waterfall renderer
  ```python
  # Output example:
  Timeline (ms):    0─────100────200────300────400────500────600────700────800────900
  worker-1          ████████████████████████████████████████████████████████████████████
  ├─ auth-check     ███
  ├─ db-query                    ██████████████████████████████████████████████████ ⚠️
  │  ├─ pool-acq                 ██████
  │  └─ execute                        ████████████████████████████████████████
  └─ response                                                                   ████

  Legend: █ Active  ⚠️ Slow (>100ms)  🔴 Error  ║ Concurrent
  ```

- [ ] **4.3** Handle concurrent/parallel spans
  ```python
  # Show parallel execution:
  worker-1          ████████████████████████████
  ├─ task-1         ████████
  ├─ task-2         ║║║║████  ← concurrent with task-1
  └─ task-3         ║║║║║║██  ← concurrent with task-1 & task-2
  ```

- [ ] **4.4** Add time scale options
  - [ ] Auto-scale based on total duration
  - [ ] Manual scale: `--waterfall-scale 10ms`
  - [ ] Zooming: `--waterfall-start 100ms --waterfall-end 500ms`

**Files to modify**:
- `src/logler/cli.py`
- `src/logler/waterfall.py` (new - waterfall rendering)

---

### Phase 5: Advanced Inference ⏳

**Goal**: Detect hierarchies even without explicit parent_span_id

- [ ] **5.1** Temporal proximity detection
  ```python
  # If logs lack parent_span_id, infer from timing:
  # - Log A creates task → Log B from that task appears soon after
  # - Pattern: "spawned thread-123", "created task-456", "forked worker-2"
  ```

- [ ] **5.2** Thread naming convention detection
  ```python
  # Detect patterns like:
  # - "worker-1" → "worker-1.auth", "worker-1.db"
  # - "main" → "main:task-1", "main:task-2"
  # - "req-123" → "req-123:auth", "req-123:db"
  ```

- [ ] **5.3** Correlation ID chaining
  ```python
  # Track correlation_id changes:
  # parent_correlation_id → child_correlation_id
  # request_id → subrequest_id
  ```

- [ ] **5.4** Custom pattern configuration
  ```python
  # Allow users to define patterns:
  investigate.follow_thread_hierarchy(
      files=["app.log"],
      thread_id="worker-1",
      hierarchy_rules={
          "parent_pattern": r"spawned (\w+)",
          "child_pattern": r"started as child of (\w+)",
      }
  )
  ```

- [ ] **5.5** Confidence scoring
  ```python
  # Mark inferred relationships with confidence:
  {
      "parent": "worker-1",
      "child": "task-1",
      "relationship": "inferred",
      "confidence": 0.85,
      "evidence": "temporal_proximity + naming_pattern"
  }
  ```

**Files to modify**:
- `crates/logler-core/src/hierarchy.rs` (new - inference logic)
- `src/logler/investigate.py`

---

### Phase 6: Error Propagation Analysis ⏳

**Goal**: Show how errors cascade through hierarchies

- [ ] **6.1** Track error propagation
  ```python
  # Detect error chains:
  🧵 main
  └─ 🔹 task-1 ✅
     ├─ 🔸 sub-a ✅
     └─ 🔸 sub-b ❌ ERROR: Connection timeout
        └─ 🔸 sub-c ❌ PROPAGATED: Failed due to sub-b
  ```

- [ ] **6.2** Identify root cause
  ```python
  # Highlight the first error in chain:
  Root Cause: sub-b (Connection timeout) at 2024-01-15T10:00:05.123Z
  Affected children: 3 spans
  Total propagated errors: 5
  ```

- [ ] **6.3** Add `--show-error-flow` flag
  ```bash
  logler investigate app.log --correlation req-123 --show-error-flow
  ```

**Files to modify**:
- `src/logler/investigate.py`
- `src/logler/cli.py`

---

### Phase 7: Web UI Enhancements ⏳

**Goal**: Interactive hierarchical view in web interface

- [ ] **7.1** Add collapsible tree view component
  - [ ] Use Alpine.js for expand/collapse
  - [ ] Click to expand children
  - [ ] Highlight selected span

- [ ] **7.2** Add interactive waterfall chart
  - [ ] Use SVG for precise rendering
  - [ ] Hover to see details
  - [ ] Click to filter logs to that span

- [ ] **7.3** Add hierarchy stats panel
  - [ ] Total depth
  - [ ] Parallel execution count
  - [ ] Bottleneck identification
  - [ ] Error propagation graph

- [ ] **7.4** Add hierarchy export
  - [ ] Export as JSON
  - [ ] Export as SVG/PNG (waterfall)
  - [ ] Export as Markdown (tree)

**Files to modify**:
- `src/logler/web/templates/viewer.html`
- `src/logler/web/static/hierarchy.js` (new)
- `src/logler/web/app.py` (new API endpoints)

---

### Phase 8: Performance Optimization ⏳

**Goal**: Make hierarchy detection fast even for huge logs

- [ ] **8.1** Index parent-child relationships
  - [ ] Build hash map: parent_span_id → [child_span_ids]
  - [ ] Cache hierarchy trees between queries

- [ ] **8.2** Lazy loading for deep trees
  - [ ] Only load depth=2 initially
  - [ ] Load more on demand: `--expand-depth 5`

- [ ] **8.3** Sampling for huge hierarchies
  - [ ] If > 1000 nodes, sample intelligently
  - [ ] Keep error paths
  - [ ] Keep slowest paths
  - [ ] Sample normal paths

- [ ] **8.4** Benchmark and optimize
  - [ ] Test with 1M+ log entries
  - [ ] Test with 1000+ spans
  - [ ] Optimize Rust hierarchy builder

**Files to modify**:
- `crates/logler-core/src/index.rs`
- `benchmarks/hierarchy_bench.rs` (new)

---

### Phase 9: Documentation & Examples ⏳

**Goal**: Make the feature discoverable and usable

- [ ] **9.1** Add to README
  - [ ] Quick example with waterfall
  - [ ] Explain use cases (async, microservices, etc.)

- [ ] **9.2** Create comprehensive guide
  - [ ] `docs/HIERARCHY_GUIDE.md`
  - [ ] Examples for different logging frameworks
  - [ ] Best practices for logging hierarchies

- [ ] **9.3** Add example scripts
  - [ ] `examples/en/08_hierarchy_investigation.py`
  - [ ] `examples/en/09_waterfall_analysis.py`
  - [ ] `examples/en/10_error_propagation.py`

- [ ] **9.4** Add to LLM docs
  - [ ] Update `docs/LLM_README.md`
  - [ ] Add hierarchy examples for AI agents

- [ ] **9.5** Create demo logs
  - [ ] `examples/logs/microservice_trace.log` - Distributed tracing
  - [ ] `examples/logs/async_workers.log` - Async Python
  - [ ] `examples/logs/nested_transactions.log` - Database transactions

**Files to modify**:
- `README.md`
- `docs/HIERARCHY_GUIDE.md` (new)
- `docs/LLM_README.md`
- `examples/` (multiple new files)

---

### Phase 10: Testing & Polish ⏳

**Goal**: Ensure quality and reliability

- [ ] **10.1** Comprehensive test suite
  - [ ] Unit tests for detection logic
  - [ ] Integration tests for full hierarchy building
  - [ ] CLI output tests
  - [ ] Waterfall rendering tests

- [ ] **10.2** Edge case handling
  - [ ] Circular dependencies (A→B→A)
  - [ ] Orphaned spans (parent missing)
  - [ ] Multiple roots
  - [ ] Very deep hierarchies (>50 levels)
  - [ ] Very wide hierarchies (>100 children)

- [ ] **10.3** User testing
  - [ ] Test with real production logs
  - [ ] Get feedback on visualization
  - [ ] Iterate on UX

- [ ] **10.4** Performance validation
  - [ ] Ensure <100ms for typical cases
  - [ ] Ensure <1s for complex hierarchies
  - [ ] Memory usage acceptable

**Files to modify**:
- `tests/test_hierarchy_*.py` (multiple)
- Update all existing tests

---

## 🎨 Visualization Examples

### Tree View (Terminal)
```
🧵 api-gateway (req-abc123, 1.2s, 1 error)
├─ 🔹 auth-service (45ms)
│  ├─ 🔸 jwt-validate (5ms)
│  └─ 🔸 user-lookup (35ms)
│     └─ 🔸 db-query (30ms)
├─ 🔹 product-service (850ms) ⚠️ SLOW
│  ├─ 🔸 inventory-check (500ms)
│  │  └─ 🔸 db-query (480ms) ⚠️
│  └─ 🔸 cache-update (340ms)
│     └─ 🔸 redis-write (320ms) 🔴 ERROR
└─ 🔹 response-assembly (15ms)
```

### Waterfall View (Terminal)
```
Timeline (ms):    0────100───200───300───400───500───600───700───800───900──1000──1100──1200
api-gateway       ████████████████████████████████████████████████████████████████████████████
├─ auth-service   ████████
│  ├─ jwt-val     ██
│  └─ user-look         ████████
│     └─ db-query         ███████
├─ product-svc               ████████████████████████████████████████████████████████ ⚠️
│  ├─ inventory                ███████████████████████████████
│  │  └─ db-query               ██████████████████████████
│  └─ cache-upd                                              ██████████████████████ 🔴
│     └─ redis-w                                              ████████████████████
└─ response                                                                         ████

Legend: █ Active  ⚠️ Slow (>100ms)  🔴 Error
```

### Error Propagation
```
🔍 Error Flow Analysis for req-abc123

Root Cause:
  🔴 redis-write failed at 2024-01-15T10:00:01.020Z
  Error: Connection refused (ECONNREFUSED)
  Location: product-service → cache-update → redis-write

Propagation Chain:
  1. redis-write ❌ Connection refused
     ↓
  2. cache-update ❌ Failed to update cache
     ↓
  3. product-service ⚠️ Completed with cache failure
     ↓
  4. api-gateway ⚠️ Partial success (cache miss)

Impact:
  - 3 spans affected
  - 1 critical error
  - 2 warnings
  - Request partially succeeded (degraded mode)

Recommendation:
  Check Redis connection pool status and connectivity
```

---

## 🔍 Detection Strategies

### 1. Explicit Fields (Highest Confidence)
```json
{
  "trace_id": "abc123",
  "span_id": "span-002",
  "parent_span_id": "span-001",  ← Direct parent reference
  "correlation_id": "req-abc123"
}
```

### 2. Thread Naming Patterns (High Confidence)
```
worker-1              ← parent
├─ worker-1.auth     ← child (pattern: parent.child)
├─ worker-1.db       ← child
└─ worker-1.cache    ← child

main                  ← parent
├─ main:task-1       ← child (pattern: parent:child)
└─ main:task-2       ← child
```

### 3. Log Messages (Medium Confidence)
```
2024-01-15 10:00:00 INFO [main] Spawned worker thread-123
2024-01-15 10:00:00 INFO [thread-123] Started as child of main
                                      ↑ Infer: main → thread-123
```

### 4. Temporal Proximity (Low Confidence)
```
2024-01-15 10:00:00.000 [worker-1] Starting async task
2024-01-15 10:00:00.001 [task-123] Processing...  ← Likely child (started right after)
2024-01-15 10:00:00.002 [task-123] Completed
2024-01-15 10:00:00.003 [worker-1] Task completed
```

---

## 🎯 Success Metrics

- [ ] Correctly detects 95%+ of hierarchies with explicit span fields
- [ ] Infers 70%+ of hierarchies without explicit fields
- [ ] Renders trees for logs with 1000+ spans in <1s
- [ ] Waterfall view handles parallel execution clearly
- [ ] Error propagation accurately identifies root causes
- [ ] CLI output is beautiful and informative
- [ ] Web UI provides interactive exploration
- [ ] Documentation enables users to adopt quickly

---

## 🚀 Future Enhancements (Post-MVP)

- [ ] Flamegraph view (like performance profiling)
- [ ] 3D visualization for complex distributed systems
- [ ] AI-powered bottleneck detection
- [ ] Automatic optimization suggestions
- [ ] Compare hierarchies (before/after deployment)
- [ ] Export to Jaeger/Zipkin format
- [ ] Real-time hierarchy streaming
- [ ] Hierarchy diffing (compare two requests)

---

## 📝 Notes

- Start with OpenTelemetry support (most standardized)
- Inference is best-effort; accuracy depends on log quality
- Performance critical - must stay fast for large logs
- CLI first, then web UI
- Documentation is crucial for adoption

---

**Last Updated**: 2024-12-20
**Next Review**: After Phase 1 completion
