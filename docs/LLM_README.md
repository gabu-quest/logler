# 🤖 Logler for LLM Agents

**High-performance log investigation powered by Rust, designed for LLM agents**

## 🎯 What This Is

Logler now includes a **Rust-powered investigation engine** specifically designed for LLM agents like Claude to efficiently investigate logs. Think of it as giving an AI detective superpowers to analyze logs at lightning speed.

## ⚡ Key Features

- **🚀 Fast**: Rust backend that parses on every core ([measured numbers](benchmarks/REPORT.md))
- **🔍 Search**: Filter by text, level, thread, correlation ID, service and time
- **🧵 Thread Following**: Reconstruct request flows across distributed systems
- **🌳 Hierarchy Visualization**: Tree and waterfall views with bottleneck detection
- **📈 Statistical Analysis**: Get insights about error rates, response times, anomalies
- **🌐 OpenTelemetry Export**: Export traces to Jaeger, Zipkin, or OTLP collectors
- **🎨 Beautiful Output**: Rich terminal output and JSON for programmatic access
- **🔌 Easy Integration**: Simple Python API designed for LLM function calling

## 🚀 Quick Start for LLM Agents

### Installation

```bash
# Install logler with Rust backend
pip install logler

# Or build from source with maturin
cd logler
maturin develop --release
```

### Basic Usage (Python)

```python
import logler.investigate as investigate

# Search for errors
results = investigate.search(
    files=["app.log"],
    query="database timeout",
    level="ERROR",
    limit=10
)

print(f"Found {results['total_matches']} errors")
print(f"Search took {results['search_time_ms']}ms")

for result in results['results']:
    print(f"Line {result['entry']['line_number']}: {result['entry']['message']}")
```

### Advanced Usage (Persistent Index)

```python
from logler.investigate import Investigator

# Create investigator and load files
investigator = Investigator()
investigator.load_files(["app.log", "api.log"])

# Perform multiple operations
results = investigator.search(query="error", limit=10)
metadata = investigator.get_metadata()

# Follow a specific request
timeline = investigator.follow_thread(correlation_id="req-001")

# Build hierarchy with bottleneck detection
hierarchy = investigator.build_hierarchy("req-001")
```

## 🛠️ Investigation Tools

### 1. `search()` - Find log entries

```python
results = investigate.search(
    files=["app.log"],
    query="database connection failed",
    level="ERROR,WARN",             # Comma-separated levels
    exclude_level="DEBUG",          # Exclude verbose entries
    exclude_query="health",         # Exclude health checks
    thread_id="worker-1,worker-2",  # Multiple threads (OR)
    correlation_id="req-001",       # Filter by correlation ID
    service_name="api-gateway",     # Filter by service
    limit=100,
    tail=20,                        # Last 20 by timestamp
    time_start="2024-01-15T10:00:00Z",  # Time range
    time_end="2024-01-15T11:00:00Z",
    context_lines=3,                # Include 3 lines before/after
    fields=["timestamp", "level", "message"],  # Project fields
)
```

`query` and `exclude_query` are each one regex, matched without regard to letter case against
the whole line as written in the file (a JSON line: its keys and other fields too) and against
the message read from it. A pattern that is not a regex raises `ValueError`. Use `a|b` to ask
for either of two words.

**Output:**
```json
{
  "results": [
    {
      "entry": {
        "file": "app.log",
        "line_number": 42,
        "timestamp": "2024-01-15T10:05:23Z",
        "level": "ERROR",
        "message": "Database connection timeout after 5s",
        "thread_id": "worker-1",
        "correlation_id": "req-001"
      },
      "context_before": [...],
      "context_after": [...],
      "relevance_score": 1.0
    }
  ],
  "total_matches": 247,
  "search_time_ms": 12
}
```

### 2. `follow_thread()` - Reconstruct request flow

```python
timeline = investigate.follow_thread(
    files=["app.log"],
    thread_id="worker-1",          # Follow by thread
    correlation_id="req-001",      # Or by correlation ID
    trace_id="abc123"              # Or by trace ID
)
```

**Output:**
```json
{
  "entries": [
    {"timestamp": "...", "level": "INFO", "message": "Processing request"},
    {"timestamp": "...", "level": "ERROR", "message": "Database timeout"},
    {"timestamp": "...", "level": "INFO", "message": "Retrying..."}
  ],
  "total_entries": 8,
  "duration_ms": 1523,
  "unique_spans": ["span-001", "span-002"]
}
```

### 3. `get_metadata()` - File information

```python
metadata = investigate.get_metadata(files=["app.log"])
```

**Output:**
```json
[
  {
    "path": "app.log",
    "size_bytes": 10485760,
    "lines": 52341,
    "format": "Json",
    "time_range": {
      "start": "2024-01-15T00:00:00Z",
      "end": "2024-01-15T23:59:59Z"
    },
    "unique_threads": 8,
    "unique_correlation_ids": 1234,
    "log_levels": {"INFO": 40000, "ERROR": 10000, "WARN": 2341}
  }
]
```

### 4. `get_context()` - Context around a line

```python
context = investigate.get_context(
    file="app.log",
    line_number=42,
    lines_before=10,
    lines_after=10
)
```

### 5. `extract_ids()` - Discover IDs and services

```python
ids = investigate.extract_ids(
    files=["app.log"],
    time_start="2024-01-15T10:00:00Z",  # Optional time range
    time_end="2024-01-15T11:00:00Z",
)
```

**Output:**
```json
{
  "thread_ids": [
    {"id": "worker-1", "count": 1234, "first_seen": "...", "last_seen": "..."}
  ],
  "correlation_ids": [
    {"id": "req-abc123", "count": 8}
  ],
  "trace_ids": [],
  "services": [
    {"id": "api-gateway", "count": 2000}
  ],
  "total_entries": 5000,
  "time_range": {"start": "...", "end": "..."}
}
```

## 📊 Example Investigation Workflow

Here's how an LLM agent might investigate a production issue:

```python
import logler.investigate as investigate

# Step 1: Get overview
metadata = investigate.get_metadata(files=["app.log"])
print(f"Analyzing {metadata[0]['lines']} log entries")
print(f"Time range: {metadata[0]['time_range']['start']} to {metadata[0]['time_range']['end']}")
print(f"Error count: {metadata[0]['log_levels']['ERROR']}")

# Step 2: Find errors
errors = investigate.search(
    files=["app.log"],
    level="ERROR",
    limit=100
)
print(f"\nFound {errors['total_matches']} errors in {errors['search_time_ms']}ms")

# Step 3: Investigate specific error
first_error = errors['results'][0]['entry']
print(f"\nInvestigating error at line {first_error['line_number']}")

# Follow the request that caused it
if first_error['correlation_id']:
    timeline = investigate.follow_thread(
        files=["app.log"],
        correlation_id=first_error['correlation_id']
    )
    print(f"Request had {timeline['total_entries']} log entries over {timeline['duration_ms']}ms")

    # Show timeline
    for entry in timeline['entries']:
        print(f"  {entry['timestamp']} [{entry['level']}] {entry['message']}")

# Step 5: Get context
context = investigate.get_context(
    file="app.log",
    line_number=first_error['line_number'],
    lines_before=5,
    lines_after=5
)
print(f"\nContext before error:")
for entry in context['context_before']:
    print(f"  {entry['message']}")
```

## 🏗️ Architecture

```
┌─────────────────────────────────────┐
│         Python Layer                │
│  (logler/investigate.py)            │
│  - Simple API for LLM agents        │
│  - JSON serialization               │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│      PyO3 Bindings                  │
│  (crates/logler-py)                 │
│  - Python ↔ Rust bridge             │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│     Rust Core Engine                │
│  (crates/logler-core)               │
│  - Fast log parsing                 │
│  - In-memory indexing               │
│  - Parallel processing (Rayon)      │
└─────────────────────────────────────┘
```

## ⚡ Performance

The measured numbers, with the machine they were measured on, are in the
[benchmark report](benchmarks/REPORT.md); [PERFORMANCE.md](PERFORMANCE.md) says what costs
time and memory. Files of 1 GB and more are not benchmarked.

## 🎨 Supported Log Formats

- **JSON**: Structured logs with automatic field extraction
- **Plain text**: Pattern-based parsing for timestamps, levels, threads
- **Syslog**: RFC 3164 and RFC 5424
- **logfmt** and **Apache common log format**
- **Custom**: a regex with named groups in `.logler/formats.yaml`, applied to the files it names

## 🔍 What Makes This LLM-Friendly?

1. **Fast responses**: Results in milliseconds, not seconds
2. **Structured output**: All results are JSON for easy parsing
3. **Order**: Results come in time order; `relevance_score` is 1.0 on every result
4. **Context included**: Get surrounding log lines automatically
5. **Hierarchy visualization**: Tree views with bottleneck detection
6. **Statistics**: Get aggregate insights for better understanding
7. **Thread following**: Reconstruct complex request flows easily

## 📚 Example: Claude Investigating Logs

**User**: "Can you check what caused the errors in app.log?"

**Claude**:
```python
import logler.investigate as investigate

# Get overview
metadata = investigate.get_metadata(["app.log"])
# Found 52,341 entries, 10,234 errors

# Search for database errors
results = investigate.search(
    files=["app.log"],
    query="database",
    level="ERROR",
    limit=10
)
# Found 45 database errors in 12ms

# Investigate first occurrence
first_error = results['results'][0]['entry']
timeline = investigate.follow_thread(
    files=["app.log"],
    correlation_id=first_error['correlation_id']
)
# Request started normally, then timeouts began at 10:05:23

# Analysis: The database started timing out at 10:05:23. Looking at the
# timeline, the application attempted 3 retries before failing. This pattern
# repeated 45 times, suggesting the database server was unreachable.
```

## 🚧 Future Enhancements

- [ ] MCP (Model Context Protocol) server for Claude Desktop integration
- [ ] WebSocket streaming for real-time log following
- [ ] Custom parser plugins
- [ ] Visualization API

## 📖 API Documentation

The Python API and its tested contracts: [API.md](API.md). Every `logler llm` command: [LLM_CLI_REFERENCE.md](LLM_CLI_REFERENCE.md).

## 🤝 Contributing

The Rust core is designed to be extended. To add new investigation tools:

1. Add the function to `crates/logler-core/src/investigate.rs`
2. Expose it via PyO3 in `crates/logler-py/src/lib.rs`
3. Add Python wrapper in `src/logler/investigate.py`
4. Update documentation

## 📄 License

MIT License - see LICENSE file

---

**Built with 🦀 Rust for speed, designed for 🤖 AI agents**
