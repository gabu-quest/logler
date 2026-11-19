# Logler Performance Guide

## Overview

Logler is built with Rust for maximum performance. This guide explains performance characteristics and optimization strategies for LLM agents working with large log files.

## Measured Performance

Medians from the [benchmark report](benchmarks/REPORT.md)
(19 scenarios, logler 1.3.1, Python 3.12, Rust backend, 8 cores):

| Operation | Measured | Scale |
|-----------|----------|-------|
| Search (level filter) | **5.6ms** / **8.9ms** / **40ms** | 1K / 10K / 50K entries |
| Search (combined filters) | **0.9ms** / **7.5ms** / **19ms** | 1K / 10K / 50K entries |
| Follow thread | **0.36ms** / **8.0ms** / **145ms** | 1K / 10K / 50K entries |
| Cross-service timeline | **3.3ms** / **5.5ms** / **10.6ms** | 2 / 3 / 5 services |
| Error flow analysis | **0.14ms** / **0.81ms** / **2.3ms** | small / medium / large hierarchy |
| Smart sampling | **67ms** / **157ms** / **622ms** | 1K / 10K / 50K entries |
| Token savings (count vs full) | **2540x** | 202 bytes against 513,018 for the same query |

## Architecture

The Rust core parses and indexes; Python adds the API, the command line and SQL. The picture
of the layers is in [ARCHITECTURE.md](../ARCHITECTURE.md). What matters for speed:

- **A file is read once, in file order**, and its lines are parsed on every core (Rayon).
  The index keeps every parsed entry in memory.
- **The module-level functions share a cache of parsed files.** `investigate.search()`,
  `follow_thread()` and the rest keep up to 10 sets of files; a set is parsed again only
  when one of its files, or the `.logler/formats.yaml` that applies to it, has changed.
- **SQL is DuckDB, in Python.** The table is built on the first SQL call, not when the
  files are loaded, and is kept until the files are loaded again.

## Performance Characteristics

### 1. File Loading and Search

The first call on a set of files parses them; the table under Measured Performance is that
cost. A later call on the same unchanged files reuses the parsed index. Combined filters
(level + query) can be faster than level-only when the query narrows results early.

### 2. Search Performance

**By indexed field** (thread_id, correlation_id, trace_id, level):
```python
# O(1) hash lookup + O(n) result collection
results = investigate.search(
    files=["app.log"],
    level="ERROR"  # Uses level_index
)
```

**Full-text search**:
```python
# O(n) scan through matching entries
results = investigate.search(
    files=["app.log"],
    query="database timeout"  # Scans all entries
)
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
```

Once the files are parsed, the cost follows the number of entries for that thread, not the
size of the file.

### 4. Pattern Detection

**Computational complexity**:
```python
# O(n × m) where n = errors, m = unique patterns
patterns = investigate.find_patterns(
    files=["app.log"],
    min_occurrences=2
)
```

**Optimization strategies**:
- Increase `min_occurrences` to reduce noise
- Filter by time window first
- Use SQL for statistical pattern detection

### 5. SQL Queries

**In-memory database** (default):
```python
investigator = Investigator()
investigator.load_files(["app.log"])  # Builds the index; DuckDB is not touched yet

# Errors per minute, and the average gap between two errors.
# The first SQL call builds the DuckDB table in memory.
results = investigator.sql_query("""
    SELECT minute, COUNT(*) AS error_count, AVG(gap_ms) AS avg_gap_ms
    FROM (
        SELECT strftime(timestamp, '%H:%M') AS minute,
               date_diff('millisecond', LAG(timestamp) OVER (ORDER BY timestamp), timestamp) AS gap_ms
        FROM logs
        WHERE level = 'ERROR'
    )
    GROUP BY minute
    ORDER BY minute
""")
```

**Disk-backed database** (for large datasets):
```python
investigator = Investigator(sql_db_path="/tmp/investigation.duckdb")
investigator.load_files(["app.log"])

# Same API — queries work identically; the table is written to that file
results = investigator.sql_query("SELECT level, COUNT(*) FROM logs GROUP BY level")
```

Use `sql_db_path` when the SQL table would not fit in memory: DuckDB then keeps the
table in that file. The SQL engine is built by the first SQL call and reused by later
ones, until `load_files()` is called again.

## Optimization Strategies for LLM Agents

### 1. Progressive Investigation

**Don't load everything at once!**

```python
# ❌ Bad: Load all 100 files immediately
investigator.load_files(glob.glob("logs/*.log"))  # Slow!

# ✅ Good: Start with metadata
metadata = investigate.get_metadata(glob.glob("logs/*.log"))

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

# Without a limit, search returns at most 10,000 results (the default cap).
# limit=0 removes the cap; use it only when you want every match.
all_errors = investigate.search(
    files=["app.log"],
    level="ERROR",
    limit=0
)
```

`count_only=True` returns only the number of matches, and `offset` pages through them.

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

1. **Metadata only**: `investigate.get_metadata(files)` returns counts and ranges per
   file, not entries.

2. **Indexed**: an `Investigator`, and the cache behind the module-level functions, hold
   every parsed entry of the loaded files in memory. This is the large cost: plan for it
   to grow with the number of entries.

3. **SQL in memory**: the first SQL call copies the entries into a DuckDB table, a second
   copy beside the index.

4. **SQL on disk**: with `Investigator(sql_db_path="/tmp/inv.duckdb")` that table is
   written to the file instead.

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
            limit=batch_size,
            offset=offset
        )

        if not results['results']:
            break

        # Process this batch
        for result in results['results']:
            yield result

        offset += batch_size
```

## Benchmarks

The full benchmark suite measures 19 scenarios across 7 suites (search, hierarchy,
correlation, output, sampling, memory, db_source). Run it yourself:

```bash
uv pip install "matplotlib>=3.8"
uv run python -m benchmarks run --scale small -v
uv run python -m benchmarks plot
```

The run writes to `benchmarks/results/`, which is not tracked. The published report: [benchmarks/REPORT.md](benchmarks/REPORT.md)

### Comparison with Traditional Tools

grep and ripgrep search bytes; logler searches structured log entries with thread/correlation
awareness. Direct comparisons aren't meaningful — they solve different problems. Use grep for
string matching, use logler when you need thread tracking, hierarchy building, cross-service
timelines, or structured investigation.

See the [full benchmark report](benchmarks/REPORT.md) for measured numbers across 19 scenarios.

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
