# Logler LLM Investigation API

**Making log investigation fast, easy, and LLM-friendly**

## 🎯 Overview

Logler provides a high-performance Rust-powered investigation API designed specifically for LLM agents. The API enables semantic search, pattern detection, timeline reconstruction, and anomaly detection across large log files.

## 🚀 Quick Start for LLM Agents

### Via MCP (Model Context Protocol)
```bash
# Claude Desktop can connect directly to logler as an MCP server
logler mcp-server --socket /tmp/logler.sock
```

### Via Python Function Calling
```python
from logler import investigate

# Search for errors
results = investigate.search(
    files=["app.log"],
    query="database timeout",
    level="ERROR",
    time_range="last 1 hour"
)

# Follow a thread
timeline = investigate.follow_thread(
    files=["app.log"],
    thread_id="worker-1",
    correlation_id="req-001"
)
```

## 🛠️ Investigation Tools

### 1. `search_logs` - Semantic Search
Search logs with flexible filters and ranking.

**Input Schema:**
```json
{
  "files": ["app.log", "api.log"],
  "query": "database connection failed",
  "filters": {
    "level": ["ERROR", "FATAL"],
    "time_range": {
      "start": "2024-01-15T10:00:00Z",
      "end": "2024-01-15T11:00:00Z"
    },
    "thread_id": "worker-*",
    "has_correlation_id": true
  },
  "limit": 100,
  "context_lines": 3
}
```

**Output Schema:**
```json
{
  "results": [
    {
      "file": "app.log",
      "line_number": 42,
      "timestamp": "2024-01-15T10:05:23Z",
      "level": "ERROR",
      "thread_id": "worker-1",
      "correlation_id": "req-001",
      "message": "Database connection timeout after 5s",
      "context_before": ["...", "...", "..."],
      "context_after": ["...", "...", "..."],
      "relevance_score": 0.95
    }
  ],
  "total_matches": 247,
  "search_time_ms": 12
}
```

**Use Cases:**
- Find all errors matching a pattern
- Search for specific error messages
- Identify issues in a time window

---

### 2. `follow_thread` - Thread/Trace Following
Get all log entries for a specific thread or correlation ID.

**Input Schema:**
```json
{
  "files": ["app.log"],
  "thread_id": "worker-1",
  "correlation_id": "req-001",
  "trace_id": "abc123",
  "sort": "chronological"
}
```

**Output Schema:**
```json
{
  "entries": [
    {
      "file": "app.log",
      "line_number": 10,
      "timestamp": "2024-01-15T10:00:00Z",
      "level": "INFO",
      "message": "Processing request",
      "span_id": "span-001"
    },
    {
      "file": "app.log",
      "line_number": 15,
      "timestamp": "2024-01-15T10:00:01Z",
      "level": "ERROR",
      "message": "Database timeout",
      "span_id": "span-002"
    }
  ],
  "total_entries": 8,
  "duration_ms": 1523,
  "unique_spans": ["span-001", "span-002", "span-003"]
}
```

**Use Cases:**
- Reconstruct request flow
- Debug distributed transactions
- Follow execution across services

---

### 3. `get_context` - Context Extraction
Get surrounding log entries for a specific line.

**Input Schema:**
```json
{
  "file": "app.log",
  "line_number": 42,
  "lines_before": 10,
  "lines_after": 10,
  "include_related_threads": true
}
```

**Output Schema:**
```json
{
  "target": {
    "line_number": 42,
    "timestamp": "2024-01-15T10:05:23Z",
    "level": "ERROR",
    "message": "Database connection timeout"
  },
  "context_before": [...],
  "context_after": [...],
  "related_threads": [
    {
      "thread_id": "worker-2",
      "entries": [...]
    }
  ]
}
```

**Use Cases:**
- Understand what led to an error
- See the aftermath of an event
- Find related activity

---

### 4. `analyze_timeline` - Timeline Reconstruction
Reconstruct chronological timeline with grouping and analysis.

**Input Schema:**
```json
{
  "files": ["app.log", "api.log"],
  "time_range": {
    "start": "2024-01-15T10:00:00Z",
    "end": "2024-01-15T10:05:00Z"
  },
  "group_by": "thread_id",
  "include_statistics": true
}
```

**Output Schema:**
```json
{
  "timeline": [
    {
      "timestamp": "2024-01-15T10:00:00Z",
      "events": [
        {"thread": "worker-1", "level": "INFO", "message": "..."},
        {"thread": "worker-2", "level": "INFO", "message": "..."}
      ]
    }
  ],
  "statistics": {
    "total_entries": 523,
    "by_level": {"INFO": 400, "ERROR": 100, "WARN": 23},
    "by_thread": {"worker-1": 200, "worker-2": 323},
    "errors_per_minute": [10, 15, 20, 18, 12]
  },
  "anomalies": [
    {
      "timestamp": "2024-01-15T10:02:00Z",
      "description": "Error rate spike: 20 errors/min (avg: 10)"
    }
  ]
}
```

**Use Cases:**
- Understand system behavior over time
- Identify when issues started
- Detect error spikes

---

### 5. `find_patterns` - Pattern Detection
Detect repeated patterns, error cascades, and anomalies.

**Input Schema:**
```json
{
  "files": ["app.log"],
  "pattern_types": ["repeated_errors", "cascading_failures", "periodic_events"],
  "min_occurrences": 3,
  "time_window_seconds": 60
}
```

**Output Schema:**
```json
{
  "patterns": [
    {
      "type": "repeated_error",
      "pattern": "Database connection timeout",
      "occurrences": 15,
      "first_seen": "2024-01-15T10:00:00Z",
      "last_seen": "2024-01-15T10:05:00Z",
      "affected_threads": ["worker-1", "worker-2"],
      "examples": [...]
    },
    {
      "type": "cascading_failure",
      "trigger": "Database timeout in worker-1",
      "cascade": [
        {"timestamp": "...", "message": "Connection pool exhausted"},
        {"timestamp": "...", "message": "Request queue full"},
        {"timestamp": "...", "message": "Health check failed"}
      ]
    }
  ]
}
```

**Use Cases:**
- Find root causes
- Detect cascading failures
- Identify recurring issues

---

### 6. `get_statistics` - Statistical Analysis
Aggregate and analyze log data.

**Input Schema:**
```json
{
  "files": ["app.log"],
  "metrics": ["error_count", "response_time", "throughput"],
  "group_by": ["level", "thread_id"],
  "time_bucket": "1 minute",
  "filters": {
    "level": ["ERROR", "WARN"]
  }
}
```

**Output Schema:**
```json
{
  "statistics": {
    "error_count": {
      "total": 523,
      "by_level": {"ERROR": 400, "WARN": 123},
      "by_thread": {"worker-1": 200, "worker-2": 323},
      "time_series": [
        {"timestamp": "2024-01-15T10:00:00Z", "count": 10},
        {"timestamp": "2024-01-15T10:01:00Z", "count": 15}
      ]
    },
    "response_time": {
      "p50": 245,
      "p95": 1200,
      "p99": 4500,
      "max": 8000
    }
  },
  "insights": [
    "Error rate increased 200% at 10:02:00",
    "Thread worker-2 has 2x more errors than worker-1"
  ]
}
```

**Use Cases:**
- Generate reports
- Track metrics over time
- Identify performance issues

---

### 7. `analyze_errors` - Error Analysis
Group and analyze error messages.

**Input Schema:**
```json
{
  "files": ["app.log"],
  "time_range": {
    "start": "2024-01-15T10:00:00Z",
    "end": "2024-01-15T11:00:00Z"
  },
  "group_by_similarity": true,
  "include_stack_traces": true
}
```

**Output Schema:**
```json
{
  "error_groups": [
    {
      "signature": "Database connection timeout",
      "count": 45,
      "first_seen": "2024-01-15T10:00:00Z",
      "last_seen": "2024-01-15T10:30:00Z",
      "affected_files": ["app.log"],
      "affected_threads": ["worker-1", "worker-2", "worker-3"],
      "examples": [...],
      "potential_cause": "Database server unreachable"
    }
  ],
  "unique_errors": 12,
  "total_errors": 523
}
```

**Use Cases:**
- Group similar errors
- Find most common issues
- Prioritize fixes

---

### 8. `detect_anomalies` - Anomaly Detection
Statistical anomaly detection using baselines.

**Input Schema:**
```json
{
  "files": ["app.log"],
  "metrics": ["error_rate", "log_volume"],
  "baseline_window": "1 hour",
  "sensitivity": 2.0,
  "alert_threshold": 3.0
}
```

**Output Schema:**
```json
{
  "anomalies": [
    {
      "timestamp": "2024-01-15T10:15:00Z",
      "metric": "error_rate",
      "value": 45,
      "baseline": 10,
      "deviation": 3.5,
      "severity": "high",
      "description": "Error rate is 3.5 standard deviations above baseline"
    }
  ],
  "baseline_stats": {
    "error_rate": {"mean": 10, "stddev": 3.2}
  }
}
```

**Use Cases:**
- Detect unusual behavior
- Alert on spikes
- Find performance regressions

---

### 9. `get_metadata` - File Metadata
Get information about log files.

**Input Schema:**
```json
{
  "files": ["app.log"]
}
```

**Output Schema:**
```json
{
  "files": [
    {
      "path": "app.log",
      "size_bytes": 10485760,
      "lines": 52341,
      "format": "json",
      "time_range": {
        "start": "2024-01-15T00:00:00Z",
        "end": "2024-01-15T23:59:59Z"
      },
      "available_fields": ["timestamp", "level", "thread_id", "message"],
      "unique_threads": 8,
      "unique_correlation_ids": 1234,
      "log_levels": {"INFO": 40000, "ERROR": 10000, "WARN": 2341}
    }
  ]
}
```

**Use Cases:**
- Understand log structure
- Validate file format
- Check data availability

---

## 🏗️ Architecture

### Rust Core (`logler-core`)
- High-performance log parsing and indexing
- Memory-mapped file I/O for large files
- Parallel processing with Rayon
- Optional DuckDB backend for SQL queries
- Zero-copy deserialization with Serde

### PyO3 Bindings (`logler`)
- Python wrapper around Rust core
- Exposes all investigation tools as Python functions
- Async support with `tokio` and `asyncio`

### MCP Server (`logler-mcp`)
- Implements Model Context Protocol
- Exposes tools via JSON-RPC
- Compatible with Claude Desktop, Continue.dev, etc.
- WebSocket and HTTP transports

## 📊 Performance Targets

- **Search**: <50ms for 1GB file, <500ms for 10GB file
- **Follow thread**: <20ms for typical request (100 entries)
- **Statistics**: <100ms for 1M entries
- **Pattern detection**: <200ms for 1GB file
- **Memory usage**: <100MB base + <2GB for 10GB file indexing

## 🔧 Implementation Notes

### Indexing Strategy
1. First pass: Build in-memory index (line offsets, timestamps, threads)
2. Optional: Store index in `.logler-index` file for reuse
3. Use memory-mapped I/O for file access
4. Parallel processing with Rayon for multi-core utilization

### Error Handling
- All tools return `Result<T, LoglerError>`
- Clear error messages for LLM interpretation
- Graceful degradation for malformed logs

### Streaming Support
- Tools support streaming results for large result sets
- Python generators for memory efficiency
- MCP server streams results via WebSocket

## 📚 Example Investigation Workflow

```python
from logler import investigate

# Step 1: Get overview
metadata = investigate.get_metadata(files=["app.log"])
print(f"Analyzing {metadata['lines']} log entries")

# Step 2: Find errors
errors = investigate.search(
    files=["app.log"],
    filters={"level": ["ERROR", "FATAL"]},
    limit=100
)
print(f"Found {errors['total_matches']} errors")

# Step 3: Analyze error patterns
patterns = investigate.find_patterns(
    files=["app.log"],
    pattern_types=["repeated_errors"]
)
print(f"Top error: {patterns['patterns'][0]['pattern']}")

# Step 4: Follow problematic request
timeline = investigate.follow_thread(
    files=["app.log"],
    correlation_id=errors['results'][0]['correlation_id']
)
print(f"Request had {len(timeline['entries'])} log entries")

# Step 5: Get context
context = investigate.get_context(
    file="app.log",
    line_number=timeline['entries'][0]['line_number'],
    lines_before=10,
    lines_after=10
)
print("Context around first error:")
for entry in context['context_before']:
    print(f"  {entry['message']}")
```

## 🚀 Getting Started

### For LLM Agents (Python)
```bash
pip install logler
```

```python
from logler import investigate

results = investigate.search(
    files=["app.log"],
    query="error",
    limit=10
)
```

### For Claude Desktop (MCP)
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "logler": {
      "command": "logler",
      "args": ["mcp-server"],
      "env": {}
    }
  }
}
```

### For API Integration
```bash
logler serve --enable-api --port 8000
```

```bash
curl -X POST http://localhost:8000/api/investigate/search \
  -H "Content-Type: application/json" \
  -d '{"files": ["app.log"], "query": "error", "limit": 10}'
```

## 📖 Documentation

- **API Reference**: Full documentation for all investigation tools
- **Examples**: Common investigation scenarios
- **Performance Guide**: Optimization tips for large files
- **MCP Integration**: Using logler with Claude Desktop
- **Python SDK**: Complete Python API documentation

---

**Built with Rust 🦀 for speed, designed for LLM agents 🤖**
