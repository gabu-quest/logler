# Logler LLM-First CLI Implementation Plan

**Date:** 2024-12-23
**Status:** Planning
**Goal:** Create a suite of CLI commands optimized for LLM agents as the primary users

---

## Executive Summary

Add a `logler llm` command group with machine-optimized commands that:
- Output structured JSON by default (no `--json` flag needed)
- Never truncate output - let the LLM decide what to filter
- Provide full metadata (line numbers, file paths, parse confidence)
- Use meaningful exit codes for chaining
- Support streaming via JSONL for large datasets

---

## Architecture

### New Files

```
src/logler/
├── llm_cli.py          # NEW: LLM command group and all subcommands
├── llm_output.py       # NEW: Structured output formatters
├── llm_session.py      # NEW: Stateful session management
└── cli.py              # MODIFY: Add `llm` subcommand group
```

### Design Principles

1. **JSON-First**: All output is JSON by default
2. **No Truncation**: Full data, always
3. **Deterministic**: Same input = same output structure
4. **Atomic Operations**: Each command does ONE thing well
5. **Rich Metadata**: Include everything an LLM needs to reason
6. **Meaningful Exit Codes**:
   - `0` = Success with results
   - `1` = Success but no results found
   - `2` = Error (invalid input, file not found, etc.)

---

## Command Specifications

### 1. `logler llm schema <files>`

**Purpose**: Infer the structure/schema of log files. Helps LLM understand what fields are available.

```bash
logler llm schema app.log worker.log
```

**Output**:
```json
{
  "files_analyzed": 2,
  "total_entries": 15234,
  "schema": {
    "timestamp": {"present": 0.98, "formats": ["ISO8601", "Unix"]},
    "level": {"present": 1.0, "values": ["DEBUG", "INFO", "WARN", "ERROR"]},
    "message": {"present": 1.0},
    "thread_id": {"present": 0.85, "patterns": ["worker-\\d+", "main"]},
    "correlation_id": {"present": 0.42, "patterns": ["req-[a-f0-9]+"]},
    "trace_id": {"present": 0.15},
    "span_id": {"present": 0.15},
    "custom_fields": ["user_id", "duration_ms", "service"]
  },
  "detected_formats": {
    "Json": 0.75,
    "PlainText": 0.20,
    "Logfmt": 0.05
  },
  "time_range": {
    "earliest": "2024-01-15T00:00:00Z",
    "latest": "2024-01-15T23:59:59Z",
    "duration_seconds": 86399
  }
}
```

**Options**:
- `--sample-size N` - Number of entries to analyze (default: 1000)
- `--full` - Analyze all entries (slow for large files)

---

### 2. `logler llm search <files>`

**Purpose**: Search logs with full results, no truncation.

```bash
logler llm search app.log --level ERROR --query "timeout"
```

**Output**:
```json
{
  "query": {
    "level": "ERROR",
    "pattern": "timeout",
    "files": ["app.log"]
  },
  "summary": {
    "total_matches": 47,
    "unique_messages": 12,
    "time_span_seconds": 3600
  },
  "results": [
    {
      "file": "app.log",
      "line_number": 1523,
      "timestamp": "2024-01-15T10:23:45.123Z",
      "level": "ERROR",
      "message": "Database timeout after 30000ms",
      "thread_id": "worker-3",
      "correlation_id": "req-abc123",
      "raw": "2024-01-15T10:23:45.123Z ERROR [worker-3] Database timeout after 30000ms",
      "parse_confidence": 0.95
    }
  ],
  "aggregations": {
    "by_thread": {"worker-3": 23, "worker-1": 15, "worker-2": 9},
    "by_hour": {"10": 30, "11": 12, "12": 5}
  }
}
```

**Options**:
- `--level LEVEL` - Filter by log level
- `--query PATTERN` - Regex pattern to match
- `--thread THREAD_ID` - Filter by thread
- `--correlation ID` - Filter by correlation ID
- `--after TIMESTAMP` - Only entries after this time
- `--before TIMESTAMP` - Only entries before this time
- `--limit N` - Limit results (default: unlimited)
- `--context N` - Include N context lines (default: 0)
- `--include-raw` - Include raw log line (default: true)

---

### 3. `logler llm sample <files>`

**Purpose**: Get a statistically representative sample for initial analysis.

```bash
logler llm sample app.log --strategy diverse --size 50
```

**Output**:
```json
{
  "population": {
    "total_entries": 150000,
    "file": "app.log"
  },
  "sample": {
    "size": 50,
    "strategy": "diverse",
    "coverage": {
      "levels": {"ERROR": 5, "WARN": 10, "INFO": 30, "DEBUG": 5},
      "threads": 8,
      "time_span_percent": 95
    }
  },
  "entries": [
    {
      "line_number": 42,
      "timestamp": "...",
      "level": "ERROR",
      "message": "...",
      "selection_reason": "error_representative"
    }
  ]
}
```

**Options**:
- `--strategy` - Sampling strategy:
  - `random` - Pure random sample
  - `diverse` - Cover all levels, threads, time ranges
  - `errors_focused` - Prioritize errors and warnings
  - `head` - First N entries
  - `tail` - Last N entries
  - `edges` - First and last + boundaries
- `--size N` - Sample size (default: 100)

---

### 4. `logler llm triage <files>`

**Purpose**: Quick severity assessment for incident response.

```bash
logler llm triage /var/log/app/*.log --last 1h
```

**Output**:
```json
{
  "assessment": {
    "severity": "high",
    "confidence": 0.87,
    "summary": "Database connection failures causing cascading errors"
  },
  "metrics": {
    "error_rate": 0.23,
    "error_count": 1523,
    "warn_count": 3201,
    "total_entries": 45000,
    "time_range": "2024-01-15T10:00:00Z to 2024-01-15T11:00:00Z"
  },
  "top_issues": [
    {
      "pattern": "Connection pool exhausted",
      "count": 892,
      "severity": "high",
      "first_seen": "2024-01-15T10:15:23Z",
      "affected_threads": ["worker-1", "worker-2", "worker-3"]
    }
  ],
  "affected_services": ["api-gateway", "user-service", "order-service"],
  "suggested_actions": [
    {
      "action": "investigate_correlation",
      "target": "req-abc123",
      "reason": "First error in cascade"
    },
    {
      "action": "check_thread",
      "target": "worker-1",
      "reason": "Highest error concentration"
    }
  ],
  "timeline": {
    "error_onset": "2024-01-15T10:15:23Z",
    "peak_errors": "2024-01-15T10:32:00Z",
    "pattern": "sudden_spike"
  }
}
```

**Options**:
- `--last DURATION` - Analyze last N minutes/hours (e.g., `30m`, `2h`)
- `--after TIMESTAMP` - Start time
- `--before TIMESTAMP` - End time

---

### 5. `logler llm correlate <identifier>`

**Purpose**: Trace a request/correlation ID across files and services.

```bash
logler llm correlate req-abc123 --files "*.log"
```

**Output**:
```json
{
  "identifier": "req-abc123",
  "identifier_type": "correlation_id",
  "trace": {
    "total_entries": 23,
    "services": ["api-gateway", "user-service", "order-service"],
    "duration_ms": 1523,
    "outcome": "error"
  },
  "timeline": [
    {
      "sequence": 1,
      "timestamp": "2024-01-15T10:23:45.100Z",
      "file": "api-gateway.log",
      "line_number": 5234,
      "service": "api-gateway",
      "level": "INFO",
      "message": "Incoming request: GET /api/orders",
      "thread_id": "gw-1",
      "latency_from_start_ms": 0
    },
    {
      "sequence": 2,
      "timestamp": "2024-01-15T10:23:45.150Z",
      "file": "user-service.log",
      "service": "user-service",
      "level": "INFO",
      "message": "Validating user token",
      "latency_from_start_ms": 50
    }
  ],
  "error_point": {
    "sequence": 15,
    "timestamp": "2024-01-15T10:23:46.500Z",
    "service": "order-service",
    "message": "Database timeout",
    "latency_from_start_ms": 1400
  }
}
```

**Options**:
- `--files GLOB` - Files to search
- `--type TYPE` - Identifier type (`correlation_id`, `trace_id`, `thread_id`)
- `--window DURATION` - Time window to search (default: 1h)

---

### 6. `logler llm hierarchy <identifier>`

**Purpose**: Build full parent-child hierarchy tree as structured data.

```bash
logler llm hierarchy trace-xyz789 --files "*.log"
```

**Output**:
```json
{
  "root": "trace-xyz789",
  "tree": {
    "id": "span-001",
    "name": "api-gateway",
    "start": "2024-01-15T10:23:45.100Z",
    "end": "2024-01-15T10:23:46.623Z",
    "duration_ms": 1523,
    "status": "error",
    "children": [
      {
        "id": "span-002",
        "name": "user-service.validate",
        "start": "2024-01-15T10:23:45.150Z",
        "duration_ms": 45,
        "status": "ok",
        "children": []
      },
      {
        "id": "span-003",
        "name": "order-service.fetch",
        "duration_ms": 1400,
        "status": "error",
        "error_message": "Database timeout",
        "children": [
          {
            "id": "span-004",
            "name": "db.query",
            "duration_ms": 30000,
            "status": "timeout"
          }
        ]
      }
    ]
  },
  "summary": {
    "total_spans": 4,
    "max_depth": 3,
    "bottleneck": {
      "span_id": "span-004",
      "name": "db.query",
      "duration_ms": 30000,
      "percent_of_total": 95.2
    },
    "error_path": ["span-001", "span-003", "span-004"]
  }
}
```

**Options**:
- `--files GLOB` - Files to search
- `--max-depth N` - Maximum hierarchy depth
- `--min-confidence FLOAT` - Minimum confidence for hierarchy detection

---

### 7. `logler llm join <file1> <file2>`

**Purpose**: Cross-file correlation with join semantics.

```bash
logler llm join api.log worker.log --on correlation_id --window 30s
```

**Output**:
```json
{
  "join": {
    "left": "api.log",
    "right": "worker.log",
    "on": "correlation_id",
    "window_seconds": 30
  },
  "statistics": {
    "left_total": 5000,
    "right_total": 8000,
    "matched": 3200,
    "left_only": 1800,
    "right_only": 4800
  },
  "matched_pairs": [
    {
      "correlation_id": "req-abc123",
      "left": {
        "file": "api.log",
        "line_number": 100,
        "timestamp": "2024-01-15T10:00:00Z",
        "message": "Request received"
      },
      "right": {
        "file": "worker.log",
        "line_number": 500,
        "timestamp": "2024-01-15T10:00:00.050Z",
        "message": "Processing request"
      },
      "latency_ms": 50
    }
  ]
}
```

**Options**:
- `--on FIELD` - Field to join on
- `--window DURATION` - Time window for matching
- `--limit N` - Limit matched pairs returned

---

### 8. `logler llm verify-pattern <files>`

**Purpose**: Test a hypothesis about log patterns programmatically.

```bash
logler llm verify-pattern app.log \
  --pattern "timeout after (\d+)ms" \
  --extract-groups
```

**Output**:
```json
{
  "pattern": "timeout after (\\d+)ms",
  "verified": true,
  "statistics": {
    "total_matches": 156,
    "total_entries": 50000,
    "match_rate": 0.00312,
    "first_match": "2024-01-15T10:15:00Z",
    "last_match": "2024-01-15T11:45:00Z"
  },
  "extracted_groups": {
    "group_1": {
      "name": "timeout_ms",
      "values": {
        "30000": 89,
        "5000": 42,
        "10000": 25
      },
      "min": 5000,
      "max": 30000,
      "mean": 21234.5
    }
  },
  "sample_matches": [
    {
      "line_number": 1523,
      "raw": "Database timeout after 30000ms",
      "groups": ["30000"]
    }
  ],
  "distribution": {
    "by_hour": {"10": 45, "11": 111},
    "by_thread": {"worker-1": 80, "worker-2": 50, "worker-3": 26}
  }
}
```

**Options**:
- `--pattern REGEX` - Pattern to verify
- `--extract-groups` - Extract and analyze capture groups
- `--hypothesis TEXT` - Natural language hypothesis (for report)

---

### 9. `logler llm diff <files>`

**Purpose**: Compare log characteristics between time periods.

```bash
logler llm diff app.log \
  --before-start "2024-01-15T09:00:00Z" \
  --before-end "2024-01-15T10:00:00Z" \
  --after-start "2024-01-15T10:00:00Z" \
  --after-end "2024-01-15T11:00:00Z"
```

**Output**:
```json
{
  "comparison": {
    "before": {
      "start": "2024-01-15T09:00:00Z",
      "end": "2024-01-15T10:00:00Z",
      "total_entries": 12000
    },
    "after": {
      "start": "2024-01-15T10:00:00Z",
      "end": "2024-01-15T11:00:00Z",
      "total_entries": 18000
    }
  },
  "changes": {
    "volume_change_percent": 50.0,
    "error_rate_before": 0.02,
    "error_rate_after": 0.25,
    "error_rate_change": "+1150%"
  },
  "new_patterns": [
    {
      "pattern": "Connection pool exhausted",
      "count_after": 892,
      "count_before": 0,
      "severity": "high"
    }
  ],
  "disappeared_patterns": [],
  "changed_patterns": [
    {
      "pattern": "Request completed",
      "count_before": 5000,
      "count_after": 2000,
      "change_percent": -60
    }
  ]
}
```

**Options**:
- `--before-start/--before-end` - "Before" time period
- `--after-start/--after-end` - "After" time period
- `--baseline DURATION` - Use last N as baseline (e.g., `--baseline 1h`)

---

### 10. `logler llm emit <files>`

**Purpose**: Stream parsed entries as JSONL for processing.

```bash
logler llm emit app.log --level ERROR | head -100
```

**Output** (JSONL - one JSON object per line):
```jsonl
{"line":1523,"ts":"2024-01-15T10:23:45Z","level":"ERROR","msg":"Timeout","thread":"w1"}
{"line":1524,"ts":"2024-01-15T10:23:46Z","level":"ERROR","msg":"Retry failed","thread":"w1"}
```

**Options**:
- `--level LEVEL` - Filter by level
- `--query PATTERN` - Filter by pattern
- `--fields FIELDS` - Comma-separated fields to include
- `--compact` - Minimal JSON (short keys)

---

### 11. `logler llm session` (subgroup)

**Purpose**: Stateful investigation sessions for complex analyses.

#### `logler llm session create`
```bash
logler llm session create --files "*.log" --name "incident-2024-01-15"
```

**Output**:
```json
{
  "session_id": "sess_abc123",
  "name": "incident-2024-01-15",
  "created_at": "2024-01-15T12:00:00Z",
  "files": ["api.log", "worker.log"],
  "status": "active"
}
```

#### `logler llm session query <session_id>`
```bash
logler llm session query sess_abc123 --level ERROR --limit 100
```

#### `logler llm session note <session_id>`
```bash
logler llm session note sess_abc123 --text "Root cause: DB connection pool"
```

#### `logler llm session conclude <session_id>`
```bash
logler llm session conclude sess_abc123 \
  --summary "Database connection pool exhaustion" \
  --root-cause "Max connections reached under load" \
  --confidence 0.9
```

**Output**:
```json
{
  "session_id": "sess_abc123",
  "conclusion": {
    "summary": "Database connection pool exhaustion",
    "root_cause": "Max connections reached under load",
    "confidence": 0.9,
    "concluded_at": "2024-01-15T12:30:00Z"
  },
  "investigation_log": [
    {"timestamp": "...", "action": "search", "params": {...}, "results_count": 47},
    {"timestamp": "...", "action": "note", "text": "..."}
  ]
}
```

---

## Implementation Order

### Phase 1: Foundation (Core Module)
1. Create `llm_cli.py` with Click command group
2. Create `llm_output.py` with JSON output helpers
3. Implement `schema` command
4. Implement `search` command
5. Implement `emit` command (JSONL streaming)

### Phase 2: Analysis Commands
6. Implement `sample` command
7. Implement `triage` command
8. Implement `verify-pattern` command
9. Implement `diff` command

### Phase 3: Correlation Commands
10. Implement `correlate` command
11. Implement `hierarchy` command
12. Implement `join` command

### Phase 4: Session Management
13. Create `llm_session.py` for state management
14. Implement `session create`
15. Implement `session query`
16. Implement `session note`
17. Implement `session conclude`

### Phase 5: Integration
18. Wire `llm` group into main CLI
19. Add comprehensive tests
20. Documentation and examples

---

## Testing Strategy

### Unit Tests
- Each command gets its own test file
- Test JSON output structure
- Test exit codes
- Test edge cases (empty files, no matches, etc.)

### Integration Tests
- Test command chaining with pipes
- Test with example log files
- Test session persistence

### LLM-Specific Tests
- Verify JSON is parseable by common LLM frameworks
- Test with various Claude tool use scenarios
- Verify no truncation occurs

---

## Example LLM Workflow

```python
# Hypothetical Claude tool use
tools = [
    {"name": "run_command", "input": {"cmd": "logler llm triage /var/log/app/*.log --last 1h"}}
]

# Claude receives:
{
  "assessment": {"severity": "high", ...},
  "suggested_actions": [
    {"action": "investigate_correlation", "target": "req-abc123"}
  ]
}

# Claude follows up:
tools = [
    {"name": "run_command", "input": {"cmd": "logler llm correlate req-abc123 --files '/var/log/*.log'"}}
]

# Full correlation chain returned, Claude can reason about it
```

---

## Success Criteria

1. All commands output valid JSON
2. No output truncation without explicit `--limit`
3. Exit codes are meaningful and documented
4. Commands complete in reasonable time for large files
5. An LLM can use these commands to investigate incidents autonomously
6. Output structures are stable and documented

---

## Open Questions

1. **Session Storage**: File-based (JSON) or SQLite?
   - Recommendation: JSON files in `~/.logler/sessions/`

2. **Streaming for Large Results**: When to switch from JSON to JSONL?
   - Recommendation: Add `--stream` flag that outputs JSONL

3. **Configuration**: Support config file for defaults?
   - Recommendation: Yes, `~/.logler/config.json` or `LOGLER_*` env vars

---

## Appendix: Exit Code Reference

| Code | Meaning | Example |
|------|---------|---------|
| 0 | Success with results | Search found matches |
| 1 | Success but no results | Search found nothing |
| 2 | User error | Invalid arguments, file not found |
| 3 | Internal error | Unexpected exception |

---

**Document Version**: 1.0
**Author**: Claude
**Ready for Implementation**: Yes
