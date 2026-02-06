# Logler 🔍

**Beautiful local log viewer with thread tracking and real-time updates**

[![PyPI version](https://img.shields.io/pypi/v/logler.svg?logo=pypi&logoColor=white)](https://pypi.org/project/logler/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/logler.svg?logo=pypi&logoColor=white)](https://pypi.org/project/logler/)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/logler.svg?logo=python&logoColor=white)](https://pypi.org/project/logler/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://img.shields.io/github/actions/workflow/status/gabu-quest/logler/pypi.yml?logo=github&label=build)](https://github.com/gabu-quest/logler/actions)
[![Rust](https://img.shields.io/badge/rust-%23000000.svg?logo=rust&logoColor=white)](https://www.rust-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-lightgrey)](https://pypi.org/project/logler/)
[![GitHub stars](https://img.shields.io/github/stars/gabu-quest/logler?style=social)](https://github.com/gabu-quest/logler)

A modern, feature-rich log viewer that makes debugging a pleasure. View logs in your terminal with beautiful colors, or use [logler-web](https://github.com/gabu-quest/logler-web) for a modern web interface.

## ✨ Features

- 🎨 **Beautiful Terminal Output** - Rich colors and formatting with thread visualization
- 🧵 **Thread Tracking** - Follow execution flow across log entries
- 🔗 **Correlation IDs** - Track requests across microservices
- 📊 **Distributed Tracing** - OpenTelemetry span/trace support
- 🔍 **Smart Filtering** - By level, thread, pattern, or correlation ID
- 📝 **Multi-Format Support** - JSON, plain text, syslog, and more
- 🎯 **Zero Config** - Works out of the box
- 🌐 **Web UI Available** - See [logler-web](https://github.com/gabu-quest/logler-web) for Vue3 + Naive-UI interface

## 🤖 NEW: LLM Investigation Engine

**Rust-powered log investigation designed for AI agents - the most LLM-friendly log tool available!**

### Core Features
- ⚡ **Blazing Fast** - Search 1GB files in <50ms with parallel processing
- 🔍 **Semantic Search** - Find errors by description, not just exact matches
- 🧵 **Thread Following** - Reconstruct request flows across distributed systems
- 🌳 **Hierarchy Visualization** - Tree and waterfall views of nested operations, bottleneck detection
- 💾 **SQL Queries** - DuckDB-powered custom analysis for deep investigation
- 📈 **Statistical Analysis** - Z-scores, percentiles, correlations, anomaly detection
- 🌐 **OpenTelemetry Export** - Export traces to Jaeger, Zipkin, or OTLP collectors
- 🌍 **Bilingual Docs** - Complete documentation in English and Japanese (日本語)

### 🚀 NEW: Advanced LLM Features

**Designed specifically for AI agents with limited context windows:**

- 📉 **Token-Efficient Output** - 44x token savings with summary/count/compact modes
- 🔀 **Compare & Diff** - Compare successful vs failed requests, before/after deployments
- 🌐 **Cross-Service Timeline** - Unified view across microservices for distributed debugging
- 📝 **Investigation Sessions** - Track progress, undo/redo, save/resume investigations
- 🎯 **Smart Sampling** - Representative sampling with multiple strategies (diverse, errors-focused, chronological)
- 📄 **Report Generation** - Auto-generate markdown/text/JSON reports from investigation
- 📊 **Numeric Metrics Extraction** - Extract numeric values from log fields and messages, compute stats (min/max/mean/p95/p99), z-score anomaly detection, time-series bucketing
- 🔎 **Format Auto-Detection** - Confidence-scored format detection across JSON/logfmt/syslog/plain text, Drain algorithm template mining
- 🔗 **Virtual Trace Correlation** - Define correlation rules in `.logler.toml` to link entries by shared field values or temporal proximity
- 🌐 **Cross-File Event Correlation** - Find related events across multiple log files using time windows and trigger patterns
- 🎨 **Custom Log Formats** - Define, test, and manage parsing formats via `.logler.toml` config with a built-in format library

### Public API Contract

Each code block carries a **Contract ID** (e.g., `[C02]`). The test suite in `tests/test_readme.py` executes these snippets against the documented public APIs. When this section changes, the tests must change with it — CI proves the README.

#### [C02] Token-efficient search
```python
import logler.investigate as investigate

errors = investigate.search(files=["app.log"], level="ERROR", output_format="summary")
# Returns aggregated stats instead of all entries - perfect for limited context windows
```

#### [C03] Compare threads
```python
import logler.investigate as investigate

diff = investigate.compare_threads(
    files=["app.log"],
    correlation_a="req-success-123",
    correlation_b="req-failed-456"
)
print(diff['summary'])  # Comparison of two request flows
```

#### [C04] Cross-service timeline
```python
import logler.investigate as investigate

timeline = investigate.cross_service_timeline(
    files={"api": ["api.log"], "db": ["db.log"], "cache": ["cache.log"]},
    correlation_id="req-12345"
)
# See request flow: API → DB → Cache with latency breakdown
```

#### [C05] Investigation sessions
```python
import logler.investigate as investigate

session = investigate.InvestigationSession(files=["app.log"], name="incident_2024")
session.search(level="ERROR")
session.add_note("Database connection pool exhausted")
report = session.generate_report(format="markdown")  # Auto-generate report
```

#### [C06] Smart sampling
```python
import logler.investigate as investigate

sample = investigate.smart_sample(
    files=["huge.log"],
    strategy="errors_focused",  # or "diverse", "representative", "chronological"
    sample_size=50
)
```

#### [C08] Thread hierarchy
```python
import logler.investigate as investigate

hierarchy = investigate.follow_thread_hierarchy(
    files=["app.log"],
    root_identifier="req-123",
    min_confidence=0.8  # Only show high-confidence relationships
)
# Automatic bottleneck detection
if hierarchy.get('bottleneck'):
    print(f"Bottleneck: {hierarchy['bottleneck']['node_id']} took {hierarchy['bottleneck']['duration_ms']}ms")
```

#### [C09] Hierarchy summary
```python
import logler.investigate as investigate

# Using hierarchy from [C08]
summary = investigate.get_hierarchy_summary(hierarchy)
print(summary)  # Shows tree structure, errors, bottlenecks
```

#### [C10] Tree visualization
```python
from logler.tree_formatter import print_tree, print_waterfall

# Using hierarchy from [C08]
print_tree(hierarchy, mode="detailed", show_duration=True)
print_waterfall(hierarchy, width=100)  # Waterfall timeline
```

**📚 Complete LLM documentation:**
- [LLM CLI Reference](docs/LLM_CLI_REFERENCE.md) - All 17 CLI commands for AI agents
- [Python API Guide](docs/LLM_README.md) - Library API and examples
- [API Reference](docs/LLM_INVESTIGATION_API.md) - All investigation functions
- [日本語ガイド](README.ja.md) - 完全なドキュメント
- [Examples](examples/) - Production incident investigations

## 🚀 Quick Start

### Installation

```bash
# Using pip
pip install logler

# Using uv (recommended)
uv pip install logler
```

### Usage

**View logs in terminal:**
```bash
logler view app.log                      # View entire file
logler view app.log -n 100               # Last 100 lines
logler view app.log -f                   # Follow in real-time
logler view app.log --level ERROR        # Filter by level
logler view app.log --grep "timeout"     # Search pattern
logler view app.log --thread worker-1    # Filter by thread
```

**Show statistics:**
```bash
logler stats app.log             # Show statistics
logler stats app.log --json      # JSON output
```

**Investigate logs with smart analysis:**
```bash
logler investigate app.log --errors               # Analyze errors
logler investigate app.log --thread worker-1      # Follow specific thread
logler investigate app.log --correlation req-123  # Follow correlation ID
logler investigate app.log --trace trace-abc123   # Follow distributed trace
logler investigate app.log --output summary       # Token-efficient output

# 🌳 NEW: Hierarchical Thread Visualization
logler investigate app.log --correlation req-123 --hierarchy         # Show thread hierarchy tree
logler investigate app.log --trace trace-abc123 --hierarchy --waterfall        # Show waterfall timeline
logler investigate app.log --correlation req-123 --hierarchy --flamegraph # Show flamegraph view
logler investigate app.log --hierarchy --show-error-flow             # Analyze error propagation
logler investigate app.log --thread worker-1 --hierarchy --max-depth 3   # Limit hierarchy depth
```

**LLM-first CLI (JSON output by default):**

Designed for AI agents - 17 commands with structured JSON output, no truncation.

```bash
# Assessment & Overview
logler llm triage app.log --last 1h      # Quick severity assessment
logler llm summarize app.log             # Concise summary with stats
logler llm schema app.log                # Infer log structure

# Discovery
logler llm ids app.log                   # Find all thread/correlation/trace IDs

# Search & Analysis (with filtering)
logler llm search app.log --level ERROR,WARN --tail 20           # Last 20 errors/warnings
logler llm search app.log --exclude-level DEBUG --service api    # Filter by service
logler llm search app.log --exclude-query "health" --max-bytes 4000  # Budget-controlled
logler llm sql "SELECT level, COUNT(*) FROM logs GROUP BY level" -f app.log

# Request Tracing
logler llm correlate req-123 --files "*.log"   # Follow correlation ID
logler llm hierarchy trace-xyz --files "*.log"  # Build hierarchy tree
logler llm bottleneck trace-xyz --files "*.log" # Find slow operations

# Comparison
logler llm compare req-fail req-success --files "*.log"  # Compare requests
logler llm diff app.log --baseline 1h                    # Before/after analysis

# Utilities
logler llm sample app.log --strategy errors_focused --size 50
logler llm context app.log 1523 --before 10 --after 10
logler llm export trace-xyz --format jaeger

# Metrics & Format Detection (NEW - M5/M6)
logler llm metrics -f "*.log"                                    # Extract numeric values with stats
logler llm metrics -f "*.log" --fields duration_ms,response_time # Specific fields
logler llm detect -f "*.log"                                     # Auto-detect log format
logler llm templates -f "*.log" --top 20                         # Drain template mining

# Custom Formats (NEW - M1)
logler llm format list                     # List configured formats
logler llm format test app.log my-format   # Test a format against a file
logler llm format save my-format           # Save format to config

# Correlations (NEW - M2/M3)
logler llm correlation list                                      # List configured rules
logler llm correlation run -f "*.log"                            # Run all correlation rules
logler llm correlation run -f "*.log" --group request-tracking   # Run specific group
logler llm correlate-events -f "*.log" --window 5s               # Cross-file event correlation
logler llm correlate-events -f "*.log" --trigger "ERROR"         # Trigger-based correlation
```

See **[LLM CLI Reference](docs/LLM_CLI_REFERENCE.md)** for complete documentation of all 17 commands.

### Visualization Modes

**Tree View** - Shows parent-child relationships:
```
🧵 api-gateway (req-001, 520ms)
├─ 🔹 auth-service (45ms)
│  ├─ 🔸 jwt-validate (5ms)
│  └─ 🔸 user-lookup (25ms)
├─ 🔹 product-service (450ms) ⚠️ SLOW
│  ├─ 🔸 inventory-check (340ms)
│  │  └─ 🔸 db-query (300ms) ⚠️
│  └─ 🔸 cache-update (45ms) ❌ ERROR
└─ 🔹 response-assembly (10ms)
```

**Waterfall View** (`--waterfall`) - Shows temporal overlap:
```
┌──────────────────────────────────────────────────────────────────────┐
│ Timeline: req-001 (520ms)                                            │
├──────────────────────────────────────────────────────────────────────┤
│ api-gateway          ████████████████████████████████████████  520ms │
│   ├─ auth-service    ████                                      45ms │
│   ├─ product-service      ████████████████████████████████    450ms │
│   │  ├─ inventory              ██████████████████████         340ms │
│   │  └─ cache-update                              ████❌        45ms │
│   └─ response                                          ██      10ms │
└──────────────────────────────────────────────────────────────────────┘
```

**Flamegraph View** (`--flamegraph`) - Shows time distribution:
```
┌────────────────────────────────────────────────────────────────────┐
│ api-gateway (520ms)                                                │
├───────────┬────────────────────────────────────────────────────────┤
│ auth (45) │ product-service (450ms)                         ⚠     │
│           ├─────────────────────────────┬──────────────────────────┤
│           │ inventory-check (340ms)     │ cache-update (45ms) ❌   │
└───────────┴─────────────────────────────┴──────────────────────────┘
```

**Error Flow** (`--show-error-flow`) - Traces error propagation:
```
🔍 Error Flow Analysis

Root Cause:
  ❌ cache-update failed at 10:00:00.450Z
  Error: Redis connection refused
  Path: api-gateway → product-service → cache-update

Impact: 3 nodes affected, request degraded
Recommendation: Check Redis connectivity
```

**Watch for new files:**
```bash
logler watch "*.log"             # Watch for new log files
logler watch "app-*.log" -d /var/log    # Specific directory
```

## 📸 Screenshots

### Terminal
Rich, colorful terminal output:
- 🌈 Color-coded log levels
- 🧵 Thread badges
- 🔗 Correlation ID tracking
- 📈 Thread timelines

### Web Interface
For a modern web UI, see [logler-web](https://github.com/gabu-quest/logler-web) - Vue3 + Naive-UI with real-time updates.

## 🎯 Examples

### Terminal Viewing

```bash
# Basic viewing
logler view app.log

# Follow with filters
logler view app.log -f --level ERROR --grep "database"

# Multiple files
logler view app.log error.log -n 50

# Beautiful thread view
logler view app.log --thread worker-1
```

### Statistics

```bash
# Human-readable stats
logler stats app.log

# JSON for scripting
logler stats app.log --json | jq '.by_level'
```

### Investigation & Analysis

```bash
# Analyze errors with context
logler investigate app.log --errors
# Shows error frequency, top error messages, time ranges

# Follow a specific thread or request
logler investigate app.log --thread worker-1
logler investigate app.log --correlation req-abc123
logler investigate app.log --trace trace-xyz789

# Build hierarchy tree with bottleneck detection
logler investigate app.log --correlation req-123 --hierarchy

# Token-efficient output for LLMs
logler investigate app.log --errors --output summary
# Returns aggregated statistics instead of full logs

# JSON output for automation
logler investigate app.log --errors --json
```

## 🎨 Log Format Support

Logler automatically detects and parses:

**JSON Logs:**
```json
{
  "timestamp": "2024-01-15T10:00:00Z",
  "level": "INFO",
  "message": "User logged in",
  "thread_id": "worker-1",
  "correlation_id": "req-123",
  "trace_id": "abc123",
  "span_id": "span-001"
}
```

**Plain Text:**
```
2024-01-15 10:00:00 INFO [worker-1] [req-123] User logged in
2024-01-15 10:00:01 ERROR [worker-2] Database timeout trace_id=abc123
```

**With Thread Tracking:**
```
2024-01-15 10:00:00 INFO [worker-1] Request started
2024-01-15 10:00:01 DEBUG [worker-1] Processing...
2024-01-15 10:00:02 INFO [worker-1] Request completed
```
Logler groups these together and shows the complete thread timeline!

### 🎯 Perfect Log Format for Maximum Features

To unlock **all** of logler's capabilities (especially multi-level thread hierarchy), use this format:

**JSON (Recommended):**
```json
{
  "timestamp": "2024-01-15T10:00:00.123Z",
  "level": "INFO",
  "message": "Processing user request",
  "thread_id": "worker-1",
  "correlation_id": "req-abc123",
  "trace_id": "trace-xyz789",
  "span_id": "span-001",
  "parent_span_id": "span-000"
}
```

**Field Guide:**

| Field | Purpose | Enables |
|-------|---------|---------|
| `timestamp` | When the event occurred (ISO 8601) | Timeline, duration analysis |
| `level` | Log level (DEBUG/INFO/WARN/ERROR/FATAL) | Filtering, error detection |
| `message` | Human-readable description | Search, filtering |
| `thread_id` | Thread/worker identifier | Thread grouping, timeline |
| `correlation_id` | Request ID across services | Cross-service tracing |
| `trace_id` | Distributed trace identifier | OpenTelemetry integration |
| `span_id` | Unique operation identifier | Hierarchy building |
| `parent_span_id` | Parent operation's span_id | **Multi-level hierarchy trees** |

**Why `parent_span_id` matters:**

Without it, logler infers hierarchy from naming patterns (`worker-1.task-a`) or temporal proximity. With explicit `parent_span_id`, you get:
- 100% accurate parent-child relationships
- Deep hierarchy trees (not just 1-2 levels)
- Precise bottleneck detection
- Accurate error propagation tracing

**Plain Text Alternative:**
```
2024-01-15T10:00:00.123Z INFO [worker-1] [req-abc123] [trace:xyz789] [span:001] [parent:000] Processing user request
```

Logler will parse bracketed fields automatically. Use consistent formatting across your application.

## 🧵 Thread Tracking

Logler automatically tracks threads and shows:
- 📊 Log count per thread
- ❌ Error count per thread
- ⏱️ Thread duration
- 🔗 Associated correlation IDs
- 📈 Thread timeline

**Example:**
```bash
logler view app.log --thread worker-1
```

Filter logs by thread to trace execution flow.

## 🔗 Correlation & Tracing

Track requests across services:

```bash
# Follow a specific correlation ID
logler investigate app.log --correlation req-12345

# Follow a distributed trace ID
logler investigate app.log --trace trace-xyz789

# View across multiple service logs
logler view app.log service.log --grep "req-12345"
```

## ⚙️ Configuration

Logler works with zero configuration, but you can customize behavior with a `.logler.toml` file in your log directory.

### Custom Log Formats (M1)

```toml
[formats.my-app]
pattern = '(?P<timestamp>\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+(?P<level>\w+)\s+\[(?P<thread_id>[\w-]+)\]\s+(?P<message>.*)'
timestamp_format = "%Y-%m-%dT%H:%M:%S%.fZ"
```

### Correlation Rules (M2)

```toml
[correlations.request-tracking]
rules = [
  { type = "field_match", source_field = "correlation_id", target_field = "correlation_id" },
  { type = "temporal", window = "5s", anchor_field = "trace_id" },
]
```

### CLI Options

```bash
# View options
logler view app.log --no-color    # Disable colors
logler view app.log -n 1000       # Show more lines
```

## 🛠️ Development

```bash
# Clone repository
git clone https://github.com/gabu-quest/logler.git
cd logler

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black logler
ruff check logler
```

## 📦 What's Included

- **logler** - Main CLI command
- **Rich Terminal UI** - Beautiful colored output
- **Thread Tracker** - Correlation and grouping
- **Smart Parser** - Multi-format support
- **File Watcher** - Monitor for new files
- **LLM Investigation Engine** - Rust-powered analysis for AI agents

For web UI, see [logler-web](https://github.com/gabu-quest/logler-web).

## 🤝 Contributing

Contributions welcome! Please feel free to submit a Pull Request.

## 📄 License

MIT License - see LICENSE file for details.

## 🙏 Acknowledgments

Built with:
- [Rich](https://github.com/Textualize/rich) - Beautiful terminal output
- [Click](https://click.palletsprojects.com/) - CLI framework
- [DuckDB](https://duckdb.org/) - SQL analytics
- [PyO3](https://pyo3.rs/) - Rust/Python bindings

## 💡 Pro Tips

1. **Use `--follow` mode** for real-time debugging
2. **Filter by thread** to trace execution flow
3. **Use `--hierarchy`** to visualize request flow with bottleneck detection
4. **Export stats as JSON** for automation
5. **Watch directories** for new log files

## 🎓 Interactive Tours

Learn logler hands-on with [marimo](https://marimo.io/) notebook tours. Each tour is self-contained with sample data -- no external files needed.

```bash
# Run any tour in your browser
uv run marimo edit examples/tours/tour_01_fundamentals.py
```

| Tour | Topic |
|------|-------|
| 01 | Fundamentals -- search, filter, output formats |
| 02 | Thread Tracking -- grouping, correlation IDs |
| 03 | Hierarchy -- tree views, waterfall, bottleneck detection |
| 04 | Investigation -- sessions, history, report generation |
| 05 | Pattern Detection -- find repeated log patterns, frequency analysis |
| 06 | Flamegraph -- performance visualization |
| 07 | Error Flow -- root cause analysis, propagation chains |
| 08 | Comparison -- diff hierarchies, compare threads |
| 09 | Tracing Exports -- Jaeger and Zipkin formats |
| 10 | Sampling -- smart sampling strategies |
| 11 | AI Insights -- LLM investigation workflow, triage to actions |
| 12 | Multi-File -- cross-service distributed tracing |
| 13 | Live Watching -- real-time tailing and streaming |
| 14 | Performance -- 10K+ entries, benchmarks |
| 16 | Metrics Extraction -- numeric values, stats, anomaly detection, time-series |
| 17 | Format Detection -- auto-detect formats, Drain template mining |

See the [examples README](examples/README.md) for the full learning path.

## 🎓 Examples

### Debug a specific request
```bash
# Find correlation ID
logler view app.log --grep "req-12345"

# Follow that request across services
logler view app.log service.log --grep "req-12345"
```

### Monitor errors in real-time
```bash
logler view app.log -f --level ERROR
```

### Analyze thread behavior
```bash
logler view app.log --thread worker-1
```

### Build request hierarchy
```bash
logler investigate app.log --correlation req-123 --hierarchy
# Visualize request flow with bottleneck detection
```

---

**Made with ❤️ for developers who love beautiful tools**

*For a web interface, check out [logler-web](https://github.com/gabu-quest/logler-web)*
