# Logler 🔍

**Beautiful local log viewer with thread tracking and real-time updates**

[![PyPI version](https://badge.fury.io/py/logler.svg)](https://badge.fury.io/py/logler)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

A modern, feature-rich log viewer that makes debugging a pleasure. View logs in your terminal with beautiful colors or start a web interface with WebSocket support for real-time updates.

## ✨ Features

- 🎨 **Beautiful Terminal Output** - Rich colors and formatting with thread visualization
- 🌐 **Gorgeous Web UI** - Modern interface with file picker and live updates
- 🧵 **Thread Tracking** - Follow execution flow across log entries
- 🔗 **Correlation IDs** - Track requests across microservices
- 📊 **Distributed Tracing** - OpenTelemetry span/trace support
- ⚡ **Real-time Streaming** - WebSocket support for live log following
- 🔍 **Smart Filtering** - By level, thread, pattern, or correlation ID
- 📝 **Multi-Format Support** - JSON, plain text, syslog, and more
- 📂 **File Picker** - Browse and select log files from the UI
- 🎯 **Zero Config** - Works out of the box

## 🤖 NEW: LLM Investigation Engine

**Rust-powered log investigation designed for AI agents - the most LLM-friendly log tool available!**

### Core Features
- ⚡ **Blazing Fast** - Search 1GB files in <50ms with parallel processing
- 🔍 **Semantic Search** - Find errors by description, not just exact matches
- 🧵 **Thread Following** - Reconstruct request flows across distributed systems
- 🌳 **Hierarchy Visualization** - Tree and waterfall views of nested operations, bottleneck detection
- 📊 **Pattern Detection** - Automatically find repeated errors and cascading failures
- 💾 **SQL Queries** - DuckDB-powered custom analysis for deep investigation
- 📈 **Statistical Analysis** - Z-scores, percentiles, correlations, anomaly detection
- 🌍 **Bilingual Docs** - Complete documentation in English and Japanese (日本語)

### 🚀 NEW: Advanced LLM Features

**Designed specifically for AI agents with limited context windows:**

- 💡 **Auto Insights** - `analyze_with_insights()` automatically detects patterns, errors, and suggests next steps
- 📉 **Token-Efficient Output** - 44x token savings with summary/count/compact modes
- 🔀 **Compare & Diff** - Compare successful vs failed requests, before/after deployments
- 🌐 **Cross-Service Timeline** - Unified view across microservices for distributed debugging
- 📝 **Investigation Sessions** - Track progress, undo/redo, save/resume investigations
- 🎯 **Smart Sampling** - Representative sampling with multiple strategies (diverse, errors-focused, chronological)
- 📄 **Report Generation** - Auto-generate markdown/text/JSON reports from investigation
- 🤔 **Explain Feature** - Plain English explanations of cryptic errors with next steps
- 💬 **Contextual Suggestions** - AI suggests what to investigate next based on findings

```python
import logler.investigate as investigate

# 🎯 One-line auto investigation with insights
result = investigate.analyze_with_insights(files=["app.log"])
print(result['insights'])  # Automatic pattern detection, error analysis, suggestions

# 📉 Token-efficient search (44x smaller output)
errors = investigate.search(files=["app.log"], level="ERROR", output_format="summary")
# Returns aggregated stats instead of all entries - perfect for limited context windows

# 🔀 Compare successful vs failed requests
diff = investigate.compare_threads(
    files=["app.log"],
    correlation_a="req-success-123",
    correlation_b="req-failed-456"
)
print(diff['summary'])  # "Thread B took 2341ms longer and had 5 errors (cache miss, timeout)"

# 🌐 Cross-service distributed tracing
timeline = investigate.cross_service_timeline(
    files={"api": ["api.log"], "db": ["db.log"], "cache": ["cache.log"]},
    correlation_id="req-12345"
)
# See request flow: API → DB → Cache with latency breakdown

# 📝 Track investigation with sessions
session = investigate.InvestigationSession(files=["app.log"], name="incident_2024")
session.search(level="ERROR")
session.find_patterns()
session.add_note("Database connection pool exhausted")
report = session.generate_report(format="markdown")  # Auto-generate report

# 🎯 Smart sampling (representative sample of huge logs)
sample = investigate.smart_sample(
    files=["huge.log"],
    strategy="errors_focused",  # or "diverse", "representative", "chronological"
    sample_size=50
)

# 🤔 Explain cryptic errors in plain English
explanation = investigate.explain(error_message="Connection pool exhausted", context="production")
print(explanation)  # Common causes, next steps, production-specific advice

# 🌳 Hierarchical thread visualization (NEW!)
hierarchy = investigate.follow_thread_hierarchy(
    files=["app.log"],
    root_identifier="req-123",
    min_confidence=0.8  # Only show high-confidence relationships
)

# Automatic bottleneck detection
if hierarchy['bottleneck']:
    print(f"Bottleneck: {hierarchy['bottleneck']['node_id']} took {hierarchy['bottleneck']['duration_ms']}ms")

# Get summary
summary = investigate.get_hierarchy_summary(hierarchy)
print(summary)  # Shows tree structure, errors, bottlenecks

# Visualize in CLI
from tree_formatter import print_tree, print_waterfall
print_tree(hierarchy, mode="detailed", show_duration=True)
print_waterfall(hierarchy, width=100)  # Waterfall timeline showing parallel operations
```

**📚 Complete LLM documentation:**
- [English Guide](docs/LLM_README.md) - Complete API and examples
- [日本語ガイド](README.ja.md) - 完全なドキュメント
- [API Reference](docs/LLM_INVESTIGATION_API.md) - All investigation tools
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

**Start the web interface:**
```bash
logler serve                    # Start with file picker
logler serve app.log            # Open specific file
logler serve *.log              # Open multiple files
logler serve --open             # Auto-open browser
```

### Security and path restrictions

- The legacy Python web UI now enforces a **log root** to avoid accidental exposure of arbitrary files. Set `LOGLER_ROOT` to
  the directory you want to browse (defaults to the current working directory). Requests outside that root are rejected.
- For production or remote access, place the service behind authentication/reverse proxies; the built-in UI is intended for
  local or trusted environments only.

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
logler investigate app.log --auto-insights        # Auto-detect issues
logler investigate app.log --errors               # Analyze errors
logler investigate app.log --patterns             # Find repeated patterns
logler investigate app.log --thread worker-1      # Follow specific thread
logler investigate app.log --correlation req-123  # Follow correlation ID
logler investigate app.log --output summary       # Token-efficient output

# 🌳 NEW: Hierarchical Thread Visualization
logler investigate app.log --correlation req-123 --hierarchy         # Show thread hierarchy tree
logler investigate app.log --trace trace-abc123 --hierarchy --waterfall  # Show waterfall timeline
logler investigate app.log --correlation req-123 --hierarchy --flamegraph # Show flamegraph view
logler investigate app.log --hierarchy --show-error-flow             # Analyze error propagation
logler investigate app.log --thread worker-1 --hierarchy --max-depth 3   # Limit hierarchy depth
```

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

### Web Interface
Beautiful, modern web UI with file picker and real-time updates:
- 📁 Browse and select log files
- 🎨 Syntax-highlighted logs
- 🧵 Thread visualization
- 📊 Live statistics
- 🔄 Real-time following with WebSocket

### Terminal
Rich, colorful terminal output:
- 🌈 Color-coded log levels
- 🧵 Thread badges
- 🔗 Correlation ID tracking
- 📈 Thread timelines

## 🎯 Examples

### Web Interface

```bash
# Start server and auto-open browser
logler serve --open

# Start with specific files
logler serve /var/log/app.log /var/log/error.log

# Custom host/port
logler serve --host 0.0.0.0 --port 9000
```

Then open your browser to `http://localhost:8000` and:
1. Click "📁 Open File" to browse log files
2. Filter by level, search, or thread
3. Click "🔄 Follow" for real-time streaming
4. View thread timelines and statistics

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
# Auto-detect issues with insights
logler investigate app.log --auto-insights
# Output: Automatic error analysis, pattern detection, actionable suggestions

# Analyze errors with context
logler investigate app.log --errors
# Shows error frequency, top error messages, time ranges

# Find repeated patterns
logler investigate app.log --patterns --min-occurrences 5
# Identifies logs that repeat 5+ times

# Follow a specific thread or request
logler investigate app.log --thread worker-1
logler investigate app.log --correlation req-abc123

# Token-efficient output for LLMs
logler investigate app.log --auto-insights --output summary
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
| `message` | Human-readable description | Search, pattern detection |
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
logler view app.log
```
Shows threads in sidebar with:
- Thread ID badge
- Number of logs
- Error count (if any)

Click any thread to filter logs!

## 🔗 Correlation & Tracing

Track requests across services:

```bash
# Logs with correlation IDs are automatically linked
logler view app.log
```

In the web UI:
- See correlation IDs in log entries
- Filter by correlation ID
- View complete request flow
- Track distributed traces

## ⚙️ Configuration

Logler works with zero configuration, but you can customize:

```bash
# Server options
logler serve --host 0.0.0.0 --port 8000

# View options
logler view app.log --no-color    # Disable colors
logler view app.log -n 1000        # Show more lines
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
- **FastAPI Web Server** - Modern web interface
- **WebSocket Support** - Real-time log streaming
- **Thread Tracker** - Correlation and grouping
- **Smart Parser** - Multi-format support
- **File Watcher** - Monitor for new files

## 🤝 Contributing

Contributions welcome! Please feel free to submit a Pull Request.

## 📄 License

MIT License - see LICENSE file for details.

## 🙏 Acknowledgments

Built with:
- [Rich](https://github.com/Textualize/rich) - Beautiful terminal output
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [HTMX](https://htmx.org/) - Dynamic web UI
- [TailwindCSS](https://tailwindcss.com/) - Styling
- [Alpine.js](https://alpinejs.dev/) - Reactive components

## 💡 Pro Tips

1. **Use `--follow` mode** for real-time debugging
2. **Filter by thread** to trace execution flow
3. **Use the web UI** for complex log analysis
4. **Export stats as JSON** for automation
5. **Watch directories** for new log files

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

### Beautiful web dashboard
```bash
logler serve app.log --open
# Then explore threads, traces, and statistics!
```

---

**Made with ❤️ for developers who love beautiful tools**
