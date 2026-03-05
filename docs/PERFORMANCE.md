# Logler Performance Guide

## Overview

Logler is built with Rust for maximum performance. This guide explains performance characteristics and optimization strategies for LLM agents working with large log files.

## Measured Performance

Numbers from the [benchmark suite](../benchmarks/results/REPORT.md)
(14 scenarios, 3 iterations, Python 3.12, Rust backend, 8 cores):

| Operation | Measured | Scale |
|-----------|----------|-------|
| Search (level filter) | **7ms** / **39ms** / **694ms** | 1K / 10K / 50K entries |
| Search (combined filters) | **4ms** / **25ms** / **173ms** | 1K / 10K / 50K entries |
| Follow thread | **2.6ms** / **28ms** / **259ms** | 1K / 10K / 50K entries |
| Cross-service timeline | **5ms** / **7ms** / **13ms** | 2 / 3 / 5 services |
| Error flow analysis | **0.15ms** / **0.8ms** / **1.7ms** | 1K / 5K / 10K entries |
| Smart sampling | **64ms** / **778ms** / **9.1s** | 1K / 10K / 50K entries |
| Token savings (count vs full) | **2540x** | 100 ERRORs, 50K entries |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Python Layer                         │
│  logler.investigate.* (convenience functions)           │
│  logler.helpers.* (shortcuts)                           │
└─────────────────────┬───────────────────────────────────┘
                      │ PyO3 FFI (minimal overhead)
┌─────────────────────▼───────────────────────────────────┐
│                    Rust Core                            │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Parser     │  │   Indexer    │  │ Investigator │ │
│  │              │  │              │  │              │ │
│  │ • JSON       │  │ • Thread IDs │  │ • Search     │ │
│  │ • Plain text │  │ • Trace IDs  │  │ • Timeline   │ │
│  │ • Regex      │  │ • Levels     │  │ • Patterns   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │         SQL Engine (optional)                    │  │
│  │         • DuckDB for custom queries              │  │
│  │         • Z-score anomaly detection              │  │
│  │         • Correlation matrices                   │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                      │
                      │ Memory-mapped I/O
┌─────────────────────▼───────────────────────────────────┐
│                  Log Files                              │
│  • Lazy loading (only accessed regions)                 │
│  • Parallel parsing with Rayon                          │
│  • Zero-copy when possible                              │
└─────────────────────────────────────────────────────────┘
```

## Performance Characteristics

### 1. File Loading and Search

Measured on generated JSON-lines log files (benchmark suite, small scale):

| Entries | Search (level) | Search (combined) | Follow thread |
|---------|---------------|-------------------|---------------|
| 1,000   | 7ms           | 4ms               | 2.6ms         |
| 10,000  | 39ms          | 25ms              | 28ms          |
| 50,000  | 694ms         | 173ms             | 259ms         |

Note: logler re-parses files on each call (no persistent index). Combined filters
(level + query) can be faster than level-only when the query narrows results early.

### 2. Search Performance

**By indexed field** (thread_id, correlation_id, trace_id, level):
```python
# O(1) hash lookup + O(n) result collection
results = investigate.search(
    files=["app.log"],
    level="ERROR"  # Uses level_index
)
# Typical: 10-30ms for 1GB file
```

**Full-text search**:
```python
# O(n) scan through matching entries
results = investigate.search(
    files=["app.log"],
    query="database timeout"  # Scans all entries
)
# Typical: 50-200ms for 1GB file
```

**Optimization**: Use indexed fields when possible!

### 3. Thread Following

**Single thread/correlation**:
```python
# O(1) index lookup + O(k) where k = entries for that thread
timeline = investigate.follow_thread(
    files=["app.log"],
    correlation_id="req-12345"
)
# Typical: 10-50ms even for 1GB files
```

**Performance factors**:
- Number of entries for that thread (not total file size)
- Typical request: 5-50 log entries = sub-millisecond

### 4. Pattern Detection

**Computational complexity**:
```python
# O(n × m) where n = errors, m = unique patterns
patterns = investigate.find_patterns(
    files=["app.log"],
    min_occurrences=2
)
# Typical: 200-500ms for 100K errors
```

**Optimization strategies**:
- Increase `min_occurrences` to reduce noise
- Filter by time window first
- Use SQL for statistical pattern detection

### 5. SQL Queries

**In-memory database** (default):
```python
investigator = Investigator()
investigator.load_files(["app.log"])  # Loads into DuckDB in-memory

# Complex aggregations
results = investigator.sql_query("""
    SELECT
        strftime('%H:%M', timestamp) as minute,
        COUNT(*) as error_count,
        AVG((julianday(timestamp) - julianday(LAG(timestamp) OVER (ORDER BY timestamp))) * 86400000) as avg_gap_ms
    FROM logs
    WHERE level = 'ERROR'
    GROUP BY minute
""")
# Typical: 300-800ms for 1M rows
```

**Disk-backed database** (for large datasets):
```python
investigator = Investigator(sql_db_path="/tmp/investigation.duckdb")
investigator.load_files(["app.log"])  # DuckDB spills to disk

# Same API — queries work identically
results = investigator.sql_query("SELECT level, COUNT(*) FROM logs GROUP BY level")
```

Use `sql_db_path` when datasets exceed available RAM. DuckDB's disk-backed mode
uses memory-mapped I/O for speed but spills to disk instead of holding everything
in memory. The SQL engine is built once and cached across queries (invalidated on
`load_files()`).

**Memory usage**: ~2-3x the size of log data when in-memory; disk-backed reduces
this to working set size

## Optimization Strategies for LLM Agents

### 1. Progressive Investigation

**Don't load everything at once!**

```python
# ❌ Bad: Load all 100 files immediately
investigator.load_files(glob.glob("logs/*.log"))  # Slow!

# ✅ Good: Start with metadata
metadata = investigate.get_metadata(["logs/*.log"])

# Then load only relevant files
problem_files = [m['path'] for m in metadata if m['log_levels'].get('ERROR', 0) > 10]
investigator.load_files(problem_files)
```

### 2. Use Indexed Fields

**Leverage the hash indices:**

```python
# ✅ Fast: Uses correlation_index
timeline = investigate.follow_thread(
    files=["app.log"],
    correlation_id="req-12345"  # O(1) lookup
)

# ✅ Fast: Uses level_index
errors = investigate.search(
    files=["app.log"],
    level="ERROR"  # O(1) lookup
)

# ⚠️ Slower: Full-text search
errors = investigate.search(
    files=["app.log"],
    query="connection timeout"  # O(n) scan
)
```

### 3. Limit Result Sets

**Don't retrieve more than you need:**

```python
# ✅ Good: Limit results
top_errors = investigate.search(
    files=["app.log"],
    level="ERROR",
    limit=100  # Only get first 100
)

# ❌ Bad: Unlimited results
all_errors = investigate.search(
    files=["app.log"],
    level="ERROR"  # Could return millions!
)
```

### 4. Parallel Processing

**Search multiple files in parallel:**

```python
from concurrent.futures import ThreadPoolExecutor

def search_file(file):
    return investigate.search(files=[file], level="ERROR")

with ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(search_file, log_files))
```

Rust's internal parallelism (Rayon) handles per-file parallelism automatically.

### 5. Use Helpers for Common Patterns

**Pre-optimized workflows:**

```python
from logler import helpers

# Single function combines multiple optimized operations
summary = helpers.quick_summary(["app.log"])
# - Loads metadata (fast)
# - Counts by level (indexed)
# - Finds top patterns (smart sampling)

# Trace complete request with minimal overhead
flow = helpers.trace_request(["app.log"], "req-12345")
# - Uses correlation_index (O(1))
# - Enriches with context
# - Returns formatted timeline
```

## Memory Management

### Memory Usage Patterns

1. **Metadata only** (~1% of file size):
```python
metadata = investigate.get_metadata(files)  # ~10MB for 1GB file
```

2. **Indexed** (~10-20% of file size):
```python
investigator = Investigator()
investigator.load_files(files)  # ~200MB for 1GB file
```

3. **SQL loaded in-memory** (~200-300% of file size):
```python
investigator.load_files(files)  # Parsed into DuckDB in-memory
# ~2-3GB for 1GB file (structured representation)
```

4. **SQL loaded disk-backed** (bounded by working set):
```python
investigator = Investigator(sql_db_path="/tmp/inv.duckdb")
investigator.load_files(files)  # DuckDB spills to disk
# RSS stays bounded; disk usage ~2-3x file size
```

### Memory Optimization

**Stream large result sets:**

```python
# Instead of loading all results into memory
# Process in batches

def process_errors_in_batches(files, batch_size=1000):
    offset = 0
    while True:
        results = investigate.search(
            files=files,
            level="ERROR",
            limit=batch_size
        )

        if not results['results']:
            break

        # Process this batch
        for result in results['results']:
            yield result

        offset += batch_size
```

## Benchmarks

The full benchmark suite measures 14 scenarios across 5 suites (search, hierarchy,
correlation, output, sampling). Run it yourself:

```bash
uv pip install "matplotlib>=3.8"
uv run python -m benchmarks run --scale small -v
uv run python -m benchmarks plot
```

Results: [benchmarks/results/REPORT.md](../benchmarks/results/REPORT.md)

### Comparison with Traditional Tools

grep and ripgrep search bytes; logler searches structured log entries with thread/correlation
awareness. Direct comparisons aren't meaningful — they solve different problems. Use grep for
string matching, use logler when you need thread tracking, hierarchy building, cross-service
timelines, or structured investigation.

See the [full benchmark report](../benchmarks/results/REPORT.md) for measured numbers across 14 scenarios.

## Performance Testing

### Microbenchmarks

Create your own performance tests:

```python
import time
from logler import investigate

def benchmark_search(files, iterations=10):
    times = []
    for _ in range(iterations):
        start = time.time()
        investigate.search(files=files, level="ERROR", limit=100)
        times.append((time.time() - start) * 1000)

    print(f"Average: {sum(times)/len(times):.2f}ms")
    print(f"Min: {min(times):.2f}ms")
    print(f"Max: {max(times):.2f}ms")

benchmark_search(["examples/logs/production_incident.log"])
```

### Load Testing

Test with synthetic large logs:

```python
import logler.investigate as investigate
import time

# Generate large log file
def generate_test_log(lines=1_000_000, output="test_large.log"):
    import json
    from datetime import datetime, timedelta

    start_time = datetime.now()
    with open(output, 'w') as f:
        for i in range(lines):
            entry = {
                "timestamp": (start_time + timedelta(seconds=i)).isoformat(),
                "level": "ERROR" if i % 100 == 0 else "INFO",
                "thread_id": f"worker-{i % 20}",
                "correlation_id": f"req-{i // 10}",
                "message": f"Processing request {i}"
            }
            f.write(json.dumps(entry) + "\n")

# Benchmark
generate_test_log(1_000_000)

start = time.time()
inv = investigate.Investigator()
inv.load_files(["test_large.log"])
index_time = time.time() - start

start = time.time()
results = investigate.search(files=["test_large.log"], level="ERROR")
search_time = time.time() - start

print(f"Indexed 1M lines in {index_time:.2f}s")
print(f"Found {results['total_matches']} errors in {search_time*1000:.2f}ms")
```

## Tips for LLM Agents

### 1. Start Broad, Then Narrow

```python
# Step 1: Get overview (fast)
metadata = investigate.get_metadata(files)

# Step 2: Find problem area (indexed)
errors = investigate.search(files=files, level="ERROR", limit=10)

# Step 3: Deep dive (targeted)
if errors['results']:
    first_error = errors['results'][0]['entry']
    timeline = investigate.follow_thread(
        files=files,
        correlation_id=first_error.get('correlation_id')
    )
```

### 2. Cache Investigation Results

```python
# Don't re-run expensive operations
class CachedInvestigator:
    def __init__(self):
        self.inv = investigate.Investigator()
        self._metadata_cache = {}
        self._pattern_cache = {}

    def get_metadata(self, files):
        key = tuple(sorted(files))
        if key not in self._metadata_cache:
            self._metadata_cache[key] = investigate.get_metadata(files)
        return self._metadata_cache[key]
```

### 3. Use Timeouts for Large Operations

```python
import signal
from contextlib import contextmanager

@contextmanager
def timeout(seconds):
    def timeout_handler(signum, frame):
        raise TimeoutError()

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

# Use with expensive operations
try:
    with timeout(5):
        patterns = investigate.find_patterns(large_files, min_occurrences=2)
except TimeoutError:
    print("Pattern detection took too long, increasing min_occurrences")
    patterns = investigate.find_patterns(large_files, min_occurrences=10)
```

### 4. Monitor Memory Usage

```python
import psutil
import os

def check_memory():
    process = psutil.Process(os.getpid())
    mb = process.memory_info().rss / 1024 / 1024
    return f"{mb:.1f} MB"

print(f"Before load: {check_memory()}")
investigator.load_files(files)
print(f"After load: {check_memory()}")
```

## Future Optimizations

- [ ] Incremental indexing (watch mode)
- [ ] Compressed index format
- [ ] Distributed processing for multi-GB files
- [ ] GPU acceleration for pattern matching
- [ ] Streaming SQL results
- [ ] Index persistence (save/load indices)

## Questions?

See [LLM_README.md](LLM_README.md) for usage examples or [examples/](../examples/) for complete workflows.
