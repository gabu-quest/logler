# v3 Memory Safety: The Journey

## The Problem

logler's Investigator holds all parsed log entries in an in-memory index. At 600K+ entries, `load_files()` alone uses ~800 MB. Three code paths amplified this baseline cost by accumulating additional data structures on top of the already-large index.

## Three Fixes, One Story

### Fix 1: Two-Phase Search (Rust)

**Before:** `search()` materialized every match result into a full Python dict. A broad query (level=INFO, ~60% of corpus) at 100K entries would create 60K Python dicts on top of the index.

**After:** Phase 1 filters+scores using lightweight `MatchCandidate` structs (~40 bytes each). Phase 2 materializes only the final N results (default limit=100). The search working set dropped from O(matches) to O(limit).

**Commit:** `1d8e46a`

### Fix 2: Streaming db_to_jsonl Per-Table

**Before:** `db_to_jsonl` collected all tables' entries into a single list, sorted them cross-table, then wrote to JSONL. At 100K rows across multiple tables, the full sorted list sat in memory.

**After:** Each table streams independently to the JSONL output file. No cross-table sort needed — entries are contiguous per table, internally ordered by `_id`.

**Commit:** `a758fd7`

### Fix 3: `_read_sqler_table` Generator

**Before:** `_read_sqler_table` used `fetchmany(1000)` for batched reading, but accumulated ALL converted entries into a Python list before returning. The streaming was a lie — 100K rows = 100K dicts in memory before a single byte hit disk.

**After:** Converted to a generator (`yield`). Each entry is written to the temp file immediately after conversion. Peak memory is proportional to one batch (~1000 entries), not the full table.

**Commit:** `004ada9`

## The Measurement Bug

Our first attempt at proving these fixes worked used `resource.getrusage(RUSAGE_SELF).ru_maxrss` — the peak RSS for the entire process lifetime. Once pytest imports set the high-water mark (~1 GB), subsequent operations that stayed below it reported **0 KB "allocated."** We almost shipped this as proof that streaming worked.

The fix: `tracemalloc`, Python's built-in heap allocation tracker. It measures actual allocations during the measured call, not process-level RSS.

**Lesson learned and documented in CLAUDE.md** so it never happens again.

**Commit:** `c6c63d0`

## The Numbers (Measured, Not Estimated)

### db_to_jsonl Peak Memory (tracemalloc)

| Scale | Before (list) | After (generator) | Reduction |
|-------|--------------|-------------------|-----------|
| 10,000 rows | 8,874 KB (8.7 MB) | 1,030 KB (1.0 MB) | **8.6x** |
| 50,000 rows | 42,708 KB (41.7 MB) | 1,026 KB (1.0 MB) | **41.6x** |
| 100,000 rows | 85,067 KB (83.1 MB) | 1,030 KB (1.0 MB) | **82.6x** |

Before: scales linearly at ~850 bytes/row.
After: flat at ~1 MB regardless of table size.

### Search Peak Memory (tracemalloc, current only)

| Scale | Peak Allocation |
|-------|----------------|
| 10,000 entries | 1,661 KB (1.6 MB) |
| 50,000 entries | 1,658 KB (1.6 MB) |
| 100,000 entries | 1,653 KB (1.6 MB) |

Flat. The two-phase search keeps Python-side allocation constant regardless of corpus size.

### DB Source Pipeline Memory (tracemalloc, current only)

| Scale | Peak Allocation |
|-------|----------------|
| 10,000 rows | 807 KB |
| 50,000 rows | 822 KB |
| 100,000 rows | 822 KB |

Sub-megabyte and flat. The generator streams entries to disk one batch at a time.

## The Second Measurement Bug: tracemalloc's Blind Spot

We caught the `ru_maxrss` bug. Switched to `tracemalloc`. Felt good about ourselves. Then we asked: "will this survive scrutiny?"

We ran both measurements side-by-side on a 100K-entry search:

```
tracemalloc (Python heap only):
  peak:    16,703 KB (16.3 MB)

VmRSS (whole process, incl. Rust):
  before:  103,760 KB (101 MB)
  after:   327,248 KB (320 MB)
  delta:   223,488 KB (218 MB)
```

tracemalloc says 16 MB. The process actually grew **218 MB**. The difference is Rust memory — `PyInvestigator` parses the entire file into an in-memory index, and tracemalloc is completely blind to it.

Our "search stays flat at 1.6 MB" claim was technically accurate — for the Python wrapper. But the actual search loaded 100K entries into a Rust index that consumed 218 MB. It's like measuring how much fuel the dashboard uses and claiming the car is fuel-efficient.

### What's honest and what's not

| Claim | Honest? | Why |
|-------|---------|-----|
| db_to_jsonl: 85 MB -> 1 MB | **Yes** | Pure Python pipeline, tracemalloc sees everything |
| Search Python heap flat at 1.6 MB | **Technically yes** | But misleading — Rust index is 218 MB, invisible to tracemalloc |
| "103x reduction" | **Only for db_to_jsonl** | Not the overall system memory |

### The fix: measure both

Report tracemalloc (Python heap) AND VmRSS (total process memory including Rust) side by side. Be transparent about where memory goes. That's actually a more interesting story — it shows exactly what the real bottleneck is (the Rust in-memory index, a known limitation with a deferred fix for lazy/paginated loading).

### Lessons learned

1. `ru_maxrss` is useless for benchmarks (monotonic high-water mark)
2. `tracemalloc` is great for Python but blind to Rust/C allocations
3. Always ask "what can't my measurement tool see?" before publishing
4. Partial truth that looks like full truth is worse than no data at all

## How We Measured the Baseline

1. Created a git worktree at commit `a84c7d7` (pre-fix code)
2. Copied the venv (including Rust .so) from the current branch
3. Ran a standalone `memory_profiler.py` script using tracemalloc
4. The old Python code (`_read_sqler_table` with list accumulation) ran against the same seeded data (seed=42)
5. Compared apples-to-apples: same machine, same data, same measurement method

## The Chart

`benchmarks/results/v3/charts/memory_before_after.png`

Red dashed line (before) climbs from 8.7 MB to 83 MB. Green solid line (after) is flat at 1 MB. Dark theme, Okabe-Ito colorblind-safe palette.

## Benchmark Infrastructure

- 19 scenarios across 7 suites
- Deterministic data generation (seeded RNG, seed=42)
- Precision timing with warmup + percentile stats (median, p95, p99)
- Memory via tracemalloc (not ru_maxrss)
- Standalone memory profiler for worktree-based before/after comparison
- Comparison report generator with confidence classifications
- Dark theme charts with colorblind-safe Okabe-Ito palette (SVG + PNG)

## Timeline

1. Two-phase search (Rust engine fix)
2. Streaming db_to_jsonl per-table (cross-table sort elimination)
3. v3 benchmarks (5 new scenarios, 34 tests)
4. `_read_sqler_table` generator refactor
5. Measurement bug #1 caught (ru_maxrss reports 0 KB — switched to tracemalloc)
6. Worktree baseline + before/after chart generation
7. Full v3 report (19 charts)
8. Measurement bug #2 caught (tracemalloc blind to Rust heap — 1.6 MB vs 218 MB actual)
9. Fix: dual measurement (tracemalloc + VmRSS) for honest full-picture reporting

## Future Directions

The dual measurement tells us exactly where the memory goes. Now what?

### The real bottleneck: Rust in-memory index

At 100K entries, `search()` Python heap is 1.6 MB. Process RSS grows 192 MB. The gap is the `PyInvestigator` index — it parses entire files into memory at `load_files()` time. The search itself is cheap; building the index is not.

Three approaches to fix this, in order of increasing ambition:

**1. Lazy file-offset indexing (medium effort)**
Instead of parsing every entry into memory, do a first pass that records file offsets and minimal metadata (timestamp, level, line number). Full entries are materialized only when needed — during result rendering, not during filtering. This is how grep works: it doesn't load files into memory, it streams through them. The Rust `PyInvestigator` could index byte offsets via `memchr` and parse on demand.

**2. Memory-mapped backing (medium effort)**
Replace the in-memory `Vec<Entry>` with an mmap'd file. The OS pages entries in and out as needed. Peak RSS stays bounded by physical memory, not corpus size. Downside: serialization format design, platform differences in mmap behavior.

**3. Subprocess isolation for measurement (low effort, high honesty)**
VmRSS is cumulative within a process — once the index is built, it doesn't shrink even after the `Investigator` is dropped (RSS is a high-water mark within a process lifetime, though not across processes like `ru_maxrss`). For truly isolated measurement, spawn the measured operation in a subprocess and read *its* peak VmRSS. This won't fix the memory usage, but it would give perfectly accurate per-operation numbers without interference from prior measurements in the same process.

### What we'd measure next

| Question | How to measure |
|----------|---------------|
| How much memory is the index vs the search? | VmRSS after `load_files()` minus VmRSS before — isolate index cost |
| Does the engine cache leak memory? | VmRSS over repeated searches with cache enabled — should plateau |
| What's the per-entry index cost in Rust? | VmRSS delta / entry count at multiple scales — should be linear |
| Can we bound RSS at a target? | Lazy loading with configurable page size, measure RSS ceiling |

### The honest summary

We fixed what we could fix in Python (streaming db_to_jsonl: 83 MB → 1 MB). We fixed what we could fix in Rust search (two-phase: O(matches) → O(limit) working set). The remaining bottleneck — the in-memory index — is a Rust architectural decision that requires a Rust refactor to address. We know exactly how big it is (192 MB at 100K, ~1.9 KB/entry), we know where it is, and we know what the fix looks like. It's deferred, not hidden.

## Branch History

```
main -> fix/investigator-memory-oom -> feat/v3-benchmarks
```

Linear stacked branches. Each builds on the previous.
