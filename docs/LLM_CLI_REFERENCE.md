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
| 2 | User error (invalid args, file not found) |
| 3 | Internal error |

---

## Command Reference

### triage

**Quick severity assessment for incident response.**

The first command to run when investigating an issue. Provides severity level, top issues, and suggested actions.

```bash
logler llm triage app.log
logler llm triage /var/log/app/*.log --last 1h
logler llm triage app.log --pretty
```

**Options:**
- `--last DURATION` - Analyze last N duration (e.g., `30m`, `2h`, `1d`)
- `--after TIMESTAMP` - Start timestamp (ISO8601)
- `--before TIMESTAMP` - End timestamp (ISO8601)
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "assessment": {
    "severity": "high",
    "confidence": 0.9,
    "summary": "Error rate: 12.3%, 5 issues detected"
  },
  "metrics": {
    "error_rate": 0.123,
    "error_count": 45,
    "total_entries": 366,
    "log_levels": {"INFO": 280, "ERROR": 45, "WARN": 41}
  },
  "top_issues": [
    {
      "type": "error_spike",
      "severity": "high",
      "description": "Error rate exceeded 10%",
      "count": 45
    }
  ],
  "suggested_actions": [
    {"action": "investigate", "reason": "Check database connectivity"}
  ],
  "next_steps": ["logler llm search app.log --level ERROR --limit 10"]
}
```

---

### search

**Find log entries matching criteria. No truncation - full results always.**

```bash
logler llm search app.log --level ERROR
logler llm search app.log --query "timeout" --level ERROR
logler llm search app.log --thread worker-1 --limit 50
logler llm search app.log --correlation req-123
logler llm search app.log --last 30m --level WARN
```

**Options:**
- `--level LEVEL` - Filter by log level (ERROR, WARN, INFO, DEBUG)
- `--query PATTERN` - Regex pattern to match in message
- `--thread ID` - Filter by thread ID
- `--correlation ID` - Filter by correlation ID
- `--after TIMESTAMP` - Only entries after this timestamp (ISO8601)
- `--before TIMESTAMP` - Only entries before this timestamp (ISO8601)
- `--last DURATION` - Only entries in last N duration (e.g., `30m`, `2h`)
- `--limit N` - Limit number of results
- `--context N` - Include N context lines around each match
- `--include-raw/--no-raw` - Include raw log line (default: yes)
- `--aggregate/--no-aggregate` - Include aggregations (default: yes)
- `--pretty` - Pretty-print JSON output

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
    "files_searched": 1
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

### summarize

**Generate a concise summary of log contents.**

Perfect for getting a quick overview before diving deeper.

```bash
logler llm summarize app.log
logler llm summarize app.log --focus errors
logler llm summarize app.log --focus warnings
logler llm summarize *.log --pretty
```

**Options:**
- `--focus FOCUS` - What to focus on: `errors` (default), `all`, `warnings`
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
logler llm correlate worker-1 --type thread_id --window 2h
```

**Options:**
- `IDENTIFIER` - The ID to trace (required, positional)
- `--files PATTERN` - Files to search (supports globs)
- `--type TYPE` - Identifier type: `auto` (default), `correlation_id`, `trace_id`, `thread_id`
- `--window DURATION` - Time window to search (default: `1h`)
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
- `--pretty` - Pretty-print JSON output

**Output:**
```json
{
  "roots": [
    {
      "id": "api-gateway",
      "name": "HTTP POST /checkout",
      "span_id": "span-001",
      "depth": 0,
      "duration_ms": 520,
      "entry_count": 3,
      "error_count": 0,
      "children": [
        {
          "id": "auth-service",
          "name": "ValidateToken",
          "depth": 1,
          "duration_ms": 45,
          "children": []
        },
        {
          "id": "product-service",
          "name": "CheckInventory",
          "depth": 1,
          "duration_ms": 450,
          "error_count": 1,
          "children": []
        }
      ]
    }
  ],
  "total_duration_ms": 520,
  "total_nodes": 5,
  "max_depth": 2,
  "bottleneck": {
    "node_id": "product-service",
    "duration_ms": 450,
    "percentage": 86.5
  }
}
```

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
| `line_number` | INTEGER | Line number in file |
| `timestamp` | VARCHAR | ISO8601 timestamp |
| `level` | VARCHAR | Log level (INFO, ERROR, etc.) |
| `message` | VARCHAR | Log message |
| `thread_id` | VARCHAR | Thread identifier |
| `correlation_id` | VARCHAR | Request correlation ID |
| `trace_id` | VARCHAR | Distributed trace ID |
| `span_id` | VARCHAR | Span ID |
| `file` | VARCHAR | Source file path |
| `raw` | VARCHAR | Raw log line |

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
  "detected_formats": {"json": 1.0},
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
    "strategy": "errors_focused",
    "coverage": {
      "levels": {"ERROR": 30, "WARN": 15, "INFO": 5}
    }
  },
  "entries": [
    {
      "line_number": 1523,
      "timestamp": "2024-01-15T10:05:23Z",
      "level": "ERROR",
      "message": "Database timeout",
      "thread_id": "worker-1",
      "selection_reason": "error_entry"
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
- `--before/-B N` - Lines before (default: 10)
- `--after/-A N` - Lines after (default: 10)
- `--pretty` - Pretty-print JSON output

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
```

**Options:**
- `--level LEVEL` - Filter by level
- `--query PATTERN` - Filter by pattern
- `--fields LIST` - Comma-separated fields to include
- `--compact` - Minimal JSON (short keys: `ln`, `ts`, `lv`, `msg`, `th`)

**Output (one per line):**
```json
{"file":"app.log","line_number":1523,"timestamp":"2024-01-15T10:05:23Z","level":"ERROR","message":"Database timeout","thread_id":"worker-1"}
```

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

**Output (jaeger format):**
```json
{
  "identifier": "trace-abc123",
  "format": "jaeger",
  "span_count": 5,
  "export": {
    "data": [{
      "traceID": "abc12300000000000000000000000000",
      "spans": [...],
      "processes": {...}
    }]
  }
}
```

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
2. **Use `--pretty` during development** - Easier to read, but remove for production
3. **Chain commands using exit codes** - Exit 0 = results found, 1 = no results
4. **Use `sql` for complex aggregations** - Full DuckDB SQL power
5. **Use `session` for multi-step investigations** - Track what you've already checked
6. **`compare` is powerful** - Compare good vs bad requests to find differences
7. **`emit` for streaming** - Process large files line by line
