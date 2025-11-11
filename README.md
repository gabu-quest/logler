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

**Rust-powered log investigation designed for AI agents!**

- ⚡ **Blazing Fast** - Search 1GB files in <50ms with parallel processing
- 🔍 **Semantic Search** - Find errors by description, not just exact matches
- 🧵 **Thread Following** - Reconstruct request flows across distributed systems
- 📊 **Pattern Detection** - Automatically find repeated errors and cascading failures
- 💾 **SQL Queries** - DuckDB-powered custom analysis for deep investigation
- 📈 **Statistical Analysis** - Z-scores, percentiles, correlations, anomaly detection
- 🌍 **Bilingual Docs** - Complete documentation in English and Japanese (日本語)

```python
# For LLM agents like Claude
import logler.investigate as investigate

# Quick triage
results = investigate.search(files=["app.log"], query="error", level="ERROR")
patterns = investigate.find_patterns(files=["app.log"])
timeline = investigate.follow_thread(files=["app.log"], correlation_id="req-001")

# Deep analysis with SQL
from logler.investigate import Investigator
investigator = Investigator()
investigator.load_files(["app.log"])
anomalies = investigator.sql_query("""
    SELECT timestamp, COUNT(*) as errors
    FROM logs WHERE level = 'ERROR'
    GROUP BY strftime('%M', timestamp)
    HAVING errors > (SELECT AVG(errors) FROM ...)
""")
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
git clone https://github.com/yourusername/logler.git
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
