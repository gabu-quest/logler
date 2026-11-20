# LLM CLI Reference

**Command-line interface optimized for AI agents - structured JSON output, no truncation**

## Quick Start

```bash
# First command - assess what you're dealing with
logler llm triage app.log

# Get a quick summary
logler llm summarize app.log

# Search for specific errors
logler llm search app.log --level ERROR --query "timeout"
```

## Decision Tree: Which Command?

| Goal | Command |
|------|---------|
| "What's happening?" | `triage`, `summarize` |
| "Find specific entries" | `search`, `sql` |
| "Discover IDs/services" | `ids` |
| "Follow a request" | `correlate`, `hierarchy` |
| "Compare two things" | `compare`, `diff` |
| "Performance issue" | `bottleneck`, `hierarchy` |
| "Export for tools" | `export`, `emit` |
| "Understand log structure" | `schema`, `sample` |
| "Track investigation" | `session create/query/conclude` |
| "Test a hypothesis" | `verify-pattern` |
| "Get context" | `context` |

## Exit Codes

All commands use consistent exit codes for automation:

| Code | Meaning |
|------|---------|
| 0 | Success with results |
| 1 | Success but no results found |
| 2 | User error (invalid arguments, a file that is missing or cannot be read, a line number the file has no entry for, a formats file that cannot be used, a `--query` or `--exclude-query` that is not a regex) |
| 3 | Internal error |

An error is a JSON object `{"error": "<text>", "code": <exit code>}`. When the error is a file the command could not open, read or write, the object also has a `file` key with that file's name, and `error` is `<file>: <reason>`:

```json
{"error": "/var/log/app.log: Permission denied", "code": 2, "file": "/var/log/app.log"}
```

An error that names no file has no `file` key.

---

## Command Reference

### triage

**Quick severity assessment for incident response.**

The first command to run when investigating an issue. Provides a severity level, the error counts and suggested actions. Every count is over every line in the time range, however many there are.

```bash
logler llm triage app.log
logler llm triage /var/log/app/*.log --last 1h
logler llm triage app.log --pretty
```

**Options:**
- `--last DURATION` - Analyze last N duration (e.g., `30m`, `2h`, `1d`)
- `--after TIMESTAMP` - Start timestamp (ISO8601)
- `--before TIMESTAMP` - End timestamp (ISO8601)
- `--service NAME` - Filter by service name (comma-separated)
- `--max-bytes N` - Maximum output size in bytes (truncates results to fit)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "assessment": {
    "severity": "high",
    "confidence": 0.9,
    "summary": "Error rate: 20.0%, 5 errors in 25 entries"
  },
  "metrics": {
    "error_rate": 0.2,
    "error_count": 5,
    "total_entries": 25,
    "log_levels": {"INFO": 14, "WARN": 6, "ERROR": 4, "FATAL": 1}
  },
  "suggested_actions": [
    {"action": "investigate", "reason": "High error rate detected - investigate most common errors"},
    {"action": "search_errors", "reason": "Run: logler llm search --level ERROR to find error details"}
  ]
}
```

---

### search

**Find log entries matching criteria. No truncation - full results always.**

```bash
logler llm search app.log --level ERROR
logler llm search app.log --query "timeout" --level ERROR,WARN
logler llm search app.log --thread worker-1 --limit 50
logler llm search app.log --correlation req-123
logler llm search app.log --last 30m --level WARN
logler llm search app.log --exclude-level DEBUG --tail 20
logler llm search app.log --service api-gateway --fields timestamp,level,message

# Token optimization
logler llm search app.log --count-only                 # Just the count
logler llm search app.log --metadata-only              # Aggregations only
logler llm search app.log --compact --limit 50         # Short field names
logler llm search app.log --offset 50 --limit 25       # Pagination (page 3)
logler llm search app.log --after=-1h --before=-30m    # Relative time window
```

**Options:**
- `--level LEVEL` - Filter by log level (comma-separated: `ERROR,WARN`)
- `--exclude-level LEVEL` - Exclude log levels (comma-separated: `DEBUG,INFO`)
- `--query PATTERN` - A regex; a line is a result when it matches (see **Patterns** below)
- `--exclude-query PATTERN` - A regex; a line it matches is left out
- `--thread ID` - Filter by thread ID (comma-separated for multiple)
- `--correlation ID` - Filter by correlation ID (comma-separated for multiple)
- `--trace ID` - Filter by trace ID
- `--service NAME` - Filter by service name (comma-separated)
- `--after TIME` - Only entries after this time (ISO8601 or relative: `-1h`, `-30m`)
- `--before TIME` - Only entries before this time (ISO8601 or relative: `-1h`, `-30m`)
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--limit N` / `--head N` - Limit number of results (the first N in time order)
- `--tail N` - Return last N entries by timestamp
- `--offset N` - Skip first N results (for pagination, use with `--limit`)
- `--count-only` - Return only match count, no results array
- `--compact` - Use short field names (`ln`/`ts`/`lv`/`msg`/`src`/`th`/`cid`/`trc`/`sid`/`svc`)
- `--metadata-only` - Return aggregations only, no results array
- `--fields LIST` - Comma-separated fields to include in output (e.g., `timestamp,level,message`)
- `--context N` - Include N entries before and after each match (a blank line is no entry)
- `--max-bytes N` - Maximum output size in bytes (truncates results to fit)
- `--include-raw/--no-raw` - Include raw log line (default: yes)
- `--aggregate/--no-aggregate` - Include aggregations (default: yes)
- `--pretty` - Pretty-print JSON output

**Patterns:** `--query` and `--exclude-query` are each one regex, matched without regard to letter case (a `(?-i)` at the start of the pattern turns that off), against the whole line as it is written in the file and against the message read from it. On a JSON line the first includes the keys and every field, not the message alone: `--query "A-17"` finds a line whose `order` field is `A-17`, and `--query "level"` matches every JSON line. There is no word fallback: `--query "connection timeout"` finds only lines that hold that text, and `--query "timeout|refused"` asks for either. The message is read as well because a JSON line may spell it differently: a quote is written `\"`, and many loggers write `ä` as `\u00e4`. `--query 'said "no"'` and `--query "ärger"` find such a message; in a field beside the message the text is found as it is written (`\\u00e4rger`). `^` and `$` hold at the ends of the line and at the ends of the message. A pattern that is not a regex is exit 2 with the pattern and the reason, for both flags in `search` and `emit`; an empty `--query` is no filter. Every result of a query has `relevance_score` 1.0 and results come in time order, as they do without a query. `search` reads patterns with Rust's regex engine, `emit` with Python's `re`; they differ in that look-behind, look-ahead and back-references exist only in Python's, so only `emit` accepts them, and `emit` refuses a pattern longer than 1000 characters.

**Pagination Pattern:**
```bash
# Page 1: first 25 results
logler llm search app.log --limit 25 --offset 0
# Page 2: results 26-50
logler llm search app.log --limit 25 --offset 25
# Check has_more in summary to know if more pages exist
```

**Output:**
```json
{
  "query": {
    "files": ["app.log"],
    "level": "ERROR",
    "pattern": "timeout",
    "thread": null,
    "correlation": null
  },
  "summary": {
    "total_matches": 15,
    "returned": 15,
    "files_searched": 1,
    "offset": 0,
    "has_more": false
  },
  "results": [
    {
      "file": "app.log",
      "line_number": 1523,
      "timestamp": "2024-01-15T10:05:23Z",
      "level": "ERROR",
      "message": "Database connection timeout after 30s",
      "thread_id": "worker-1",
      "correlation_id": "req-123",
      "raw": "2024-01-15T10:05:23Z ERROR [worker-1] Database connection timeout after 30s"
    }
  ],
  "aggregations": {
    "by_level": {"ERROR": 15},
    "by_thread": {"worker-1": 8, "worker-2": 7}
  }
}
```

---

### ids

**Discover all unique IDs (threads, correlations, traces, services) in log files.**

Useful for understanding what's in a log file before querying. Returns counts and time ranges for each ID.

```bash
logler llm ids app.log
logler llm ids app.log --last 1h --type thread
logler llm ids /var/log/*.log --pretty
```

**Options:**
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--after TIMESTAMP` - Only entries after this timestamp (ISO8601)
- `--before TIMESTAMP` - Only entries before this timestamp (ISO8601)
- `--type TYPE` - Filter to specific ID type: `thread`, `correlation`, `trace`, `service`, `all` (default)
- `--limit N` - Limit number of IDs per category
- `--max-bytes N` - Maximum output size in bytes
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "thread_ids": [
    {"id": "worker-1", "count": 1234, "first_seen": "2024-01-15T10:00:00Z", "last_seen": "2024-01-15T11:00:00Z"},
    {"id": "worker-2", "count": 987}
  ],
  "correlation_ids": [
    {"id": "req-abc123", "count": 8}
  ],
  "trace_ids": [],
  "services": [
    {"id": "api-gateway", "count": 2000},
    {"id": "user-service", "count": 1500}
  ],
  "total_entries": 5000,
  "time_range": {
    "start": "2024-01-15T10:00:00Z",
    "end": "2024-01-15T11:00:00Z"
  }
}
```

---

### summarize

**Generate a concise summary of log contents.**

Perfect for getting a quick overview before diving deeper.

```bash
logler llm summarize app.log
logler llm summarize app.log --focus errors --last 1h
logler llm summarize app.log --focus warnings --service api-gateway
logler llm summarize *.log --pretty
```

**Options:**
- `--focus FOCUS` - What to focus on: `errors` (default), `all`, `warnings`
- `--service NAME` - Filter by service name (comma-separated)
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--after TIME` - Only entries after this time (ISO8601 or relative: `-1h`, `-30m`)
- `--before TIME` - Only entries before this time (ISO8601 or relative: `-1h`, `-30m`)
- `--max-bytes N` - Maximum output size in bytes (truncates results to fit)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "summary": "1234 entries, 45 errors (3 unique), 12 warnings. Top error: \"Database timeout\" (42x)",
  "stats": {
    "total_entries": 1234,
    "by_level": {"INFO": 1000, "ERROR": 45, "WARN": 12, "DEBUG": 177},
    "unique_correlation_ids": 89,
    "time_range": {
      "start": "2024-01-15T00:00:00Z",
      "end": "2024-01-15T23:59:59Z"
    }
  },
  "errors": [
    {
      "line": 1523,
      "message": "Database timeout after 30s",
      "correlation_id": "req-123"
    }
  ],
  "warnings": [],
  "unique_error_messages": {
    "Database timeout after 30s": 42,
    "Connection refused": 3
  }
}
```

---

### correlate

**Trace a request/correlation ID across files and services.**

Builds a complete timeline of all log entries matching the identifier.

```bash
logler llm correlate req-abc123 --files "*.log"
logler llm correlate trace-xyz789 --type trace_id
logler llm correlate worker-1 --type thread_id --last 2h
```

**Options:**
- `IDENTIFIER` - The ID to trace (required, positional)
- `--files PATTERN` - Files to search (supports globs)
- `--type TYPE` - Identifier type: `auto` (default), `correlation_id`, `trace_id`, `thread_id`
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--after TIME` - Only entries after this time (ISO8601 or relative: `-1h`)
- `--before TIME` - Only entries before this time (ISO8601 or relative: `-30m`)
- `--max-bytes N` - Maximum output size in bytes (truncates results to fit)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "identifier": "req-abc123",
  "identifier_type": "correlation_id",
  "trace": {
    "total_entries": 8,
    "services": ["api-gateway", "user-service", "database"],
    "duration_ms": 1523,
    "outcome": "error"
  },
  "timeline": [
    {
      "sequence": 1,
      "timestamp": "2024-01-15T10:05:20Z",
      "file": "api.log",
      "line_number": 100,
      "level": "INFO",
      "message": "Request received: POST /api/checkout",
      "service": "api-gateway"
    },
    {
      "sequence": 2,
      "timestamp": "2024-01-15T10:05:21Z",
      "level": "INFO",
      "message": "Validating user session"
    }
  ],
  "error_point": {
    "sequence": 5,
    "timestamp": "2024-01-15T10:05:23Z",
    "level": "ERROR",
    "message": "Database timeout"
  }
}
```

---

### hierarchy

**Build full parent-child hierarchy tree as structured data.**

Detects thread/span relationships using explicit parent_span_id, naming patterns, or temporal inference.

```bash
logler llm hierarchy trace-xyz789 --files "*.log"
logler llm hierarchy req-123 --max-depth 5
logler llm hierarchy span-001 --min-confidence 0.8
```

**Options:**
- `IDENTIFIER` - Root identifier (trace/correlation/span ID)
- `--files PATTERN` - Files to search (supports globs)
- `--max-depth N` - Maximum hierarchy depth
- `--min-confidence FLOAT` - Minimum confidence for relationships (0.0-1.0)
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--after TIME` - Only entries after this time (ISO8601 or relative: `-1h`)
- `--before TIME` - Only entries before this time (ISO8601 or relative: `-30m`)
- `--max-bytes N` - Maximum output size in bytes (truncates results to fit)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "roots": [
    {
      "id": "span-gw-1",
      "node_type": "Span",
      "name": "Incoming request: GET /api/v1/user/12345/orders",
      "parent_id": null,
      "children": [
        {
          "id": "span-user-1",
          "node_type": "Span",
          "name": "Received request for user 12345",
          "parent_id": "span-gw-1",
          "children": [],
          "entry_ids": ["8469ba9f-6f26-489e-a1ce-68c1d77f4292"],
          "start_time": "2024-01-15T10:00:00.120Z",
          "end_time": "2024-01-15T10:00:00.120Z",
          "duration_ms": 0,
          "entry_count": 1,
          "error_count": 0,
          "level_counts": {"INFO": 1},
          "depth": 1,
          "confidence": 1.0,
          "relationship_evidence": ["explicit_parent_span_id"]
        }
      ],
      "entry_ids": ["94ac72f9-4e2a-4356-bb34-df0286ab7bb1", "2bc4dc6b-14f2-4f3c-84c4-a43ab96d433a"],
      "start_time": "2024-01-15T10:00:00.100Z",
      "end_time": "2024-01-15T10:00:00.295Z",
      "duration_ms": 195,
      "entry_count": 2,
      "error_count": 0,
      "level_counts": {"INFO": 2},
      "depth": 0,
      "confidence": 0.8,
      "relationship_evidence": ["naming_pattern", "temporal_proximity"]
    }
  ],
  "total_nodes": 2,
  "max_depth": 1,
  "total_duration_ms": 195,
  "concurrent_count": 1,
  "bottleneck": {
    "node_id": "span-gw-1",
    "node_name": "Incoming request: GET /api/v1/user/12345/orders",
    "duration_ms": 195,
    "percentage": 100.0,
    "depth": 0
  },
  "error_nodes": [],
  "detection_method": "Mixed",
  "detection_methods": ["ExplicitParentId", "NamingPattern"]
}
```

The example is shortened to two nodes. `id` is the span ID (or the thread ID of a node that has
no span). `entry_count`, `error_count` and `level_counts` count the node's own log lines, each
line once. Sibling nodes come in order of start time. `entry_ids` are internal IDs that change
from run to run.

---

### bottleneck

**Analyze performance bottlenecks for a trace/correlation ID.**

Identifies the slowest operations and shows where time is spent.

```bash
logler llm bottleneck trace-abc123 --files "*.log"
logler llm bottleneck req-001 --top-n 5 --threshold-ms 50
```

**Options:**
- `IDENTIFIER` - Trace or correlation ID
- `--files PATTERN` - Files to search (supports globs)
- `--threshold-ms N` - Minimum duration to consider (default: 100ms)
- `--top-n N` - Number of top bottlenecks to return (default: 10)
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--after TIME` - Only entries after this time (ISO8601 or relative: `-1h`)
- `--before TIME` - Only entries before this time (ISO8601 or relative: `-30m`)
- `--max-bytes N` - Maximum output size in bytes (truncates results to fit)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "identifier": "trace-abc123",
  "total_duration_ms": 520,
  "total_nodes": 8,
  "analysis": {
    "threshold_ms": 100,
    "nodes_above_threshold": 3
  },
  "bottlenecks": [
    {
      "node_id": "db-query",
      "name": "SELECT * FROM orders",
      "duration_ms": 340,
      "percentage": 65.4,
      "depth": 3,
      "path": ["api-gateway", "product-service", "inventory-check", "db-query"]
    },
    {
      "node_id": "inventory-check",
      "name": "CheckInventory",
      "duration_ms": 380,
      "percentage": 73.1,
      "depth": 2
    }
  ],
  "hierarchy_bottleneck": {
    "node_id": "db-query",
    "duration_ms": 340
  }
}
```

---

### compare

**Compare two requests/traces side by side.**

Shows differences between requests - useful for comparing failed vs successful requests.

```bash
logler llm compare req-001 req-003 --files "*.log"
logler llm compare trace-success trace-failed --pretty
```

**Options:**
- `ID1` - First request/trace ID
- `ID2` - Second request/trace ID
- `--files PATTERN` - Files to search (supports globs)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "comparison": {
    "request1": {
      "id": "req-001",
      "found": true,
      "entry_count": 8,
      "duration_ms": 520,
      "outcome": "success",
      "levels": {"INFO": 6, "DEBUG": 2},
      "errors": [],
      "steps": ["Request received", "Auth validated", "Processing..."]
    },
    "request2": {
      "id": "req-003",
      "found": true,
      "entry_count": 12,
      "duration_ms": 2841,
      "outcome": "error",
      "levels": {"INFO": 8, "ERROR": 3, "WARN": 1},
      "errors": [
        {"message": "Database timeout", "line_number": 1523}
      ]
    }
  },
  "differences": [
    {
      "type": "duration",
      "description": "req-001 took -2321ms compared to req-003",
      "value1": 520,
      "value2": 2841
    },
    {
      "type": "outcome",
      "description": "req-001 success, req-003 error",
      "value1": "success",
      "value2": "error"
    },
    {
      "type": "divergence",
      "description": "Requests diverge at step 4",
      "detail": {
        "step": 4,
        "request1": "Query completed",
        "request2": "Database timeout"
      }
    }
  ],
  "summary": "req-001: success, req-003: error",
  "recommendation": "Investigate error in req-003: Database timeout"
}
```

---

### diff

**Compare log characteristics between time periods.**

Useful for understanding what changed before/after an incident or deployment.

```bash
logler llm diff app.log --baseline 1h
logler llm diff app.log --before-start "2024-01-15T09:00:00Z" --before-end "2024-01-15T10:00:00Z" --after-start "2024-01-15T10:00:00Z" --after-end "2024-01-15T11:00:00Z"
```

**Options:**
- `--baseline DURATION` - Use last N as baseline (e.g., `1h`)
- `--before-start TIMESTAMP` - Before period start (ISO8601)
- `--before-end TIMESTAMP` - Before period end (ISO8601)
- `--after-start TIMESTAMP` - After period start (ISO8601)
- `--after-end TIMESTAMP` - After period end (ISO8601)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "comparison": {
    "before": {
      "start": "2024-01-15T09:00:00Z",
      "end": "2024-01-15T10:00:00Z",
      "total": 1200,
      "error_count": 5,
      "error_rate": 0.0042,
      "by_level": {"INFO": 1150, "ERROR": 5, "WARN": 45}
    },
    "after": {
      "start": "2024-01-15T10:00:00Z",
      "end": "2024-01-15T11:00:00Z",
      "total": 1500,
      "error_count": 150,
      "error_rate": 0.1,
      "by_level": {"INFO": 1200, "ERROR": 150, "WARN": 150}
    }
  },
  "changes": {
    "volume_change_percent": 25.0,
    "error_rate_before": 0.0042,
    "error_rate_after": 0.1,
    "error_rate_change": "+2281%"
  }
}
```

---

### sql

**Execute SQL queries on log files using DuckDB.**

Powerful analytics on logs using familiar SQL syntax.

```bash
# Count by level
logler llm sql "SELECT level, COUNT(*) FROM logs GROUP BY level" -f app.log

# Top error messages
logler llm sql "SELECT message, COUNT(*) as cnt FROM logs WHERE level='ERROR' GROUP BY message ORDER BY cnt DESC LIMIT 10" -f "*.log"

# Complex analysis with CTEs
logler llm sql "
  WITH error_threads AS (
    SELECT DISTINCT thread_id FROM logs WHERE level = 'ERROR'
  )
  SELECT l.* FROM logs l
  JOIN error_threads e ON l.thread_id = e.thread_id
  ORDER BY l.timestamp
" -f "*.log"

# Query from stdin
echo "SELECT * FROM logs LIMIT 5" | logler llm sql --stdin -f app.log
```

**Options:**
- `QUERY` - SQL query (optional if using --stdin)
- `--files/-f PATTERN` - Files to load (supports globs)
- `--stdin` - Read SQL query from stdin
- `--pretty` - Pretty-print JSON output

**Table Schema:**
| Column | Type | Description |
|--------|------|-------------|
| `file` | VARCHAR | Source file path |
| `line_number` | INTEGER | Line number in file |
| `timestamp` | TIMESTAMP | Entry time (empty when the line has none) |
| `level` | VARCHAR | Log level (INFO, ERROR, etc.) |
| `message` | VARCHAR | Log message |
| `thread_id` | VARCHAR | Thread identifier |
| `correlation_id` | VARCHAR | Request correlation ID |
| `trace_id` | VARCHAR | Distributed trace ID |
| `span_id` | VARCHAR | Span ID |
| `raw` | VARCHAR | Raw log line |

`logler llm sql "DESCRIBE logs" -f app.log` lists the columns of the build you have.

**Output:**
```json
{
  "query": "SELECT level, COUNT(*) as count FROM logs GROUP BY level",
  "files": ["app.log"],
  "total_entries": 1234,
  "columns": ["level", "count"],
  "row_count": 4,
  "results": [
    {"level": "INFO", "count": 1000},
    {"level": "ERROR", "count": 150},
    {"level": "WARN", "count": 84}
  ]
}
```

---

### schema

**Infer the structure/schema of log files.**

Analyzes logs to determine available fields, formats, and data patterns.

```bash
logler llm schema app.log
logler llm schema "*.log" --sample-size 5000
logler llm schema app.log --full
```

**Options:**
- `--sample-size N` - Number of entries to analyze (default: 1000)
- `--full` - Analyze all entries (slow for large files)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "files_analyzed": 1,
  "files": ["app.log"],
  "total_entries": 1000,
  "sample_size": 1000,
  "schema": {
    "timestamp": {"present": 1.0},
    "level": {"present": 1.0, "values": ["INFO", "ERROR", "WARN", "DEBUG"]},
    "message": {"present": 1.0},
    "thread_id": {"present": 0.95, "patterns": ["worker-\\d+"]},
    "correlation_id": {"present": 0.85, "patterns": ["req-[a-z0-9]+"]}
  },
  "detected_formats": {"Json": 1.0},
  "custom_fields": ["component", "error_code", "user_id"],
  "time_range": {
    "earliest": "2024-01-15T00:00:00Z",
    "latest": "2024-01-15T23:59:59Z"
  }
}
```

---

### sample

**Get a statistically representative sample of log entries.**

```bash
logler llm sample app.log --strategy errors_focused --size 50
logler llm sample app.log --strategy diverse --size 100
logler llm sample app.log --strategy head --size 20
```

**Options:**
- `--strategy STRATEGY` - Sampling strategy:
  - `random` - Pure random sample
  - `diverse` (default) - Cover all levels, threads, time ranges
  - `errors_focused` - Prioritize errors and warnings
  - `head` - First N entries
  - `tail` - Last N entries
  - `edges` - Boundaries and transitions
- `--size N` - Sample size (default: 100)
- `--level LEVEL` - Filter by log level (comma-separated: `ERROR,WARN`)
- `--exclude-level LEVEL` - Exclude log levels (comma-separated)
- `--service NAME` - Filter by service name (comma-separated)
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--after TIMESTAMP` - Only entries after this timestamp (ISO8601)
- `--before TIMESTAMP` - Only entries before this timestamp (ISO8601)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "population": {
    "total_entries": 50000,
    "files": ["app.log"]
  },
  "sample": {
    "size": 50,
    "strategy": "errors_focused"
  },
  "entries": [
    {
      "line_number": 1523,
      "timestamp": "2024-01-15T10:05:23Z",
      "level": "ERROR",
      "message": "Database timeout",
      "thread_id": "worker-1"
    }
  ]
}
```

---

### verify-pattern

**Test a hypothesis about log patterns programmatically.**

```bash
logler llm verify-pattern app.log --pattern "timeout after (\d+)ms" --extract-groups
logler llm verify-pattern app.log --pattern "user_id=(\w+)" --hypothesis "User IDs follow alphanumeric pattern"
```

**Options:**
- `--pattern REGEX` - Regex pattern to verify (required)
- `--extract-groups` - Extract and analyze capture groups
- `--hypothesis TEXT` - Natural language hypothesis (for documentation)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "pattern": "timeout after (\\d+)ms",
  "hypothesis": "Timeouts exceed 30 seconds",
  "verified": true,
  "statistics": {
    "total_matches": 45,
    "total_entries": 1234,
    "match_rate": 0.036,
    "first_match": "2024-01-15T10:05:23Z",
    "last_match": "2024-01-15T10:45:00Z"
  },
  "sample_matches": [
    {
      "file": "app.log",
      "line_number": 1523,
      "raw": "Database timeout after 30000ms",
      "groups": ["30000"]
    }
  ],
  "extracted_groups": {
    "group_1": {
      "values": {"30000": 42, "5000": 3},
      "unique_count": 2,
      "min": 5000,
      "max": 30000,
      "mean": 28333.33
    }
  },
  "distribution": {
    "by_thread": {"worker-1": 20, "worker-2": 25}
  }
}
```

---

### context

**Get context lines around a specific log entry.**

```bash
logler llm context app.log 1523
logler llm context app.log 1523 --before 20 --after 10
```

**Options:**
- `FILE` - Log file path
- `LINE` - Line number
- `--before/-B N` - Entries before (default: 10)
- `--after/-A N` - Entries after (default: 10)

Context is counted in entries: a blank line is no entry and takes no place in it.
- `--pretty` - Pretty-print JSON output

A line number the file has no entry for (0, a negative number, past the end, an empty file)
is exit code 2: `{"error": "app.log: no entry at line 9999", "code": 2}`.

**Output:**
```json
{
  "file": "app.log",
  "line_number": 1523,
  "context_lines": {"before": 10, "after": 10},
  "target": {
    "timestamp": "2024-01-15T10:05:23Z",
    "level": "ERROR",
    "message": "Database timeout",
    "thread_id": "worker-1"
  },
  "context_before": [
    {"line_number": 1513, "level": "INFO", "message": "Starting query..."}
  ],
  "context_after": [
    {"line_number": 1524, "level": "WARN", "message": "Retrying connection..."}
  ]
}
```

---

### emit

**Stream parsed entries as JSONL for processing.**

Outputs one JSON object per line, suitable for piping to other tools.

```bash
logler llm emit app.log --level ERROR | head -100
logler llm emit app.log --query "timeout" --compact
logler llm emit app.log --fields "timestamp,level,message"
logler llm emit app.log --level ERROR,WARN --last 1h --limit 50
logler llm emit app.log --exclude-level DEBUG --exclude-query "health"
```

**Options:**
- `--level LEVEL` - Filter by level (comma-separated: `ERROR,WARN`)
- `--exclude-level LEVEL` - Exclude log levels (comma-separated)
- `--query PATTERN` - A regex a line must match, read as in `search` (**Patterns** above)
- `--exclude-query PATTERN` - A regex; a line it matches is left out
- `--service NAME` - Filter by service name (comma-separated)
- `--fields LIST` - Comma-separated fields to include
- `--compact` - Minimal JSON (short keys: `ln`, `ts`, `lv`, `msg`, `th`)
- `--limit N` - Maximum number of entries to output
- `--tail N` - Output last N entries by timestamp
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--after TIMESTAMP` - Only entries after this timestamp (ISO8601)
- `--before TIMESTAMP` - Only entries before this timestamp (ISO8601)

**Output (one per line):**
```json
{"file":"app.log","line_number":1523,"timestamp":"2024-01-15T10:05:23Z","level":"ERROR","message":"Database timeout","thread_id":"worker-1"}
```

When nothing matches, `emit` prints nothing and exits 1.

---

### export

**Export traces to Jaeger/Zipkin/OTLP format.**

Converts log-based traces to standard distributed tracing formats.

```bash
logler llm export trace-abc123 --files "*.log" --format jaeger
logler llm export trace-abc123 --format zipkin
logler llm export trace-abc123 --format otlp
```

**Options:**
- `IDENTIFIER` - Trace or correlation ID
- `--files PATTERN` - Files to search (supports globs)
- `--format FORMAT` - Export format: `jaeger` (default), `zipkin`, `otlp`
- `--pretty` - Pretty-print JSON output

`export` is what `export_to_jaeger`, `export_to_zipkin` or `export_to_otlp` returns for the
trace (`logler.export`); the command adds `identifier`, `format` and `span_count`.

- **Span ids** are the log's own `span_id` when it is 16 hexadecimal characters (in lower
  case) and not all zeros; any other id, and a node with no span id, gets a 16-hex id made with SHA-256, the
  same in every run. No two spans share an id.
- **The trace id** is `IDENTIFIER` when it is 32 hexadecimal characters and not all zeros,
  else made from it the same way.
- **The service** of a span is its hierarchy node's `service` (the `service_name` of the
  node's first entry that has one), else `logler-export`.
  Jaeger: one process per service, named by each span's `processID`. Zipkin:
  `localEndpoint`. OTLP: one `resourceSpans` entry per service.

**Output (jaeger format):**
```json
{
  "identifier": "trace-abc123",
  "format": "jaeger",
  "span_count": 2,
  "export": {
    "data": [{
      "traceID": "f77fa5b72c92206389a61d9faea3c4b3",
      "spans": [
        {"traceID": "f77fa5b72c92206389a61d9faea3c4b3", "spanID": "a1b2c3d4e5f60718",
         "operationName": "GET /orders", "references": [],
         "startTime": 1794650460000000, "duration": 1500000,
         "tags": [{"key": "node_type", "type": "string", "value": "Span"}, ...],
         "logs": [], "processID": "p1", "warnings": []},
        {"traceID": "f77fa5b72c92206389a61d9faea3c4b3", "spanID": "1122334455667788",
         "operationName": "charge card",
         "references": [{"refType": "CHILD_OF", "traceID": "f77fa5b72c92206389a61d9faea3c4b3",
                         "spanID": "a1b2c3d4e5f60718"}],
         "startTime": 1794650460250000, "duration": 250000,
         "tags": [...], "logs": [], "processID": "p2", "warnings": []}
      ],
      "processes": {
        "p1": {"serviceName": "gateway", "tags": [{"key": "exported_by", "type": "string", "value": "logler"}]},
        "p2": {"serviceName": "billing", "tags": [{"key": "exported_by", "type": "string", "value": "logler"}]}
      },
      "warnings": []
    }]
  }
}
```

**Output (otlp format), `export` only:**
```json
{
  "resourceSpans": [
    {
      "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "gateway"}}]},
      "scopeSpans": [{"scope": {"name": "logler"}, "spans": [
        {"traceId": "f77fa5b72c92206389a61d9faea3c4b3", "spanId": "a1b2c3d4e5f60718",
         "name": "GET /orders",
         "startTimeUnixNano": "1794650460000000000", "endTimeUnixNano": "1794650461500000000",
         "attributes": [{"key": "node_type", "value": {"stringValue": "Span"}},
                        {"key": "entry_count", "value": {"intValue": "1"}},
                        {"key": "error_count", "value": {"intValue": "0"}}]}
      ]}]
    },
    {
      "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "billing"}}]},
      "scopeSpans": [{"scope": {"name": "logler"}, "spans": [
        {"traceId": "f77fa5b72c92206389a61d9faea3c4b3", "spanId": "1122334455667788",
         "parentSpanId": "a1b2c3d4e5f60718", "name": "charge card", "...": "..."}
      ]}]
    }
  ]
}
```

A root span has no `parentSpanId`; a span with errors has `"status": {"code": 2}`.

---

### session

**Stateful investigation sessions for complex analyses.**

Sessions track investigation steps and can be saved/resumed.

#### session create

```bash
logler llm session create --files "app.log" --name "incident-2024-01"
```

**Options:**
- `--files/-f PATTERN` - Files to include (required)
- `--name TEXT` - Session name
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "session_id": "sess_abc123def456",
  "name": "incident-2024-01",
  "created_at": "2024-01-15T10:00:00Z",
  "files": ["app.log"],
  "status": "active",
  "session_file": "/home/user/.logler/sessions/sess_abc123def456.json"
}
```

#### session list

```bash
logler llm session list
```

#### session query

```bash
logler llm session query sess_abc123 --level ERROR --limit 10
```

#### session note

```bash
logler llm session note sess_abc123 --text "Found database timeout at 10:05"
```

#### session conclude

```bash
logler llm session conclude sess_abc123 --summary "Root cause: DB connection pool exhausted" --root-cause "Connection pool size too small" --confidence 0.9
```

---

## Common Workflows

### Incident Response

```bash
# 1. Quick assessment
logler llm triage /var/log/app/*.log --last 1h

# 2. Get detailed errors
logler llm search app.log --level ERROR --last 1h --limit 20

# 3. Follow the first error's request
logler llm correlate req-123 --files "*.log"

# 4. Compare with a successful request
logler llm compare req-123 req-001 --files "*.log"
```

### Performance Investigation

```bash
# 1. Find the slow trace
logler llm sql "SELECT correlation_id, COUNT(*) as entries FROM logs GROUP BY correlation_id ORDER BY entries DESC LIMIT 5" -f app.log

# 2. Build hierarchy
logler llm hierarchy trace-slow --files "*.log"

# 3. Find bottlenecks
logler llm bottleneck trace-slow --files "*.log" --top-n 3
```

### Before/After Deployment

```bash
# Compare error rates
logler llm diff app.log --baseline 1h

# Look for new error patterns
logler llm verify-pattern app.log --pattern "NewFeature.*error"
```

### Understanding Unknown Logs

```bash
# 1. Infer schema
logler llm schema unknown.log

# 2. Get representative sample
logler llm sample unknown.log --strategy diverse --size 50

# 3. Quick summary
logler llm summarize unknown.log
```

---

## Tips for AI Agents

1. **Start with `triage`** - It gives severity, metrics, and next steps
2. **Use `ids` to discover** - Find all thread IDs, correlation IDs, and services before querying
3. **Use `--pretty` during development** - Easier to read, but remove for production
4. **Chain commands using exit codes** - Exit 0 = results found, 1 = no results
5. **Use `--tail` for recent entries** - `--tail 10` gives the last 10 entries by timestamp
6. **Use `--exclude-level` to reduce noise** - `--exclude-level DEBUG` removes verbose entries
7. **Use `--max-bytes` to control output size** - Prevent overwhelming LLM context windows
8. **Use `--count-only` first** - Estimate scope before fetching full results
9. **Use `--offset` for pagination** - `--offset 50 --limit 25` = page 3
10. **Use `--compact` to save tokens** - Short field names save ~15-20% output size
11. **Use `--metadata-only` for aggregations** - Get level/service distributions without entries
12. **Use `sql` for complex aggregations** - Full DuckDB SQL power
13. **Use `session` for multi-step investigations** - Track what you've already checked
14. **`compare` is powerful** - Compare good vs bad requests to find differences
15. **`emit` for streaming** - Process large files line by line
16. **Relative time in `--after`/`--before`** - `--after=-1h --before=-30m` for recent windows
