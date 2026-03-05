<p align="center">
  <img src="assets/logler-logo.png" width="200" alt="logler">
</p>

<h3 align="center">Rust-powered log investigation for humans and AI agents</h3>

<p align="center">
  <a href="https://pypi.org/project/logler/"><img src="https://img.shields.io/pypi/v/logler.svg?logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://pypi.org/project/logler/"><img src="https://img.shields.io/pypi/pyversions/logler.svg?logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT"></a>
  <a href="https://github.com/gabu-quest/logler/actions"><img src="https://img.shields.io/github/actions/workflow/status/gabu-quest/logler/ci.yml?logo=github&label=CI" alt="CI"></a>
</p>
<p align="center">
  <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/rust-%23000000.svg?logo=rust&logoColor=white" alt="Rust"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://github.com/gabu-quest/logler"><img src="https://img.shields.io/github/stars/gabu-quest/logler?style=social" alt="Stars"></a>
</p>

<p align="center">
  English | <a href="README.ja.md">日本語</a>
</p>

---

**Point at log files. Get structured answers.**

Logler sits between `grep` (finds strings, no structure) and ELK/Datadog (requires infrastructure). It's a local-first investigation engine that understands threads, correlations, traces, and hierarchies -- no servers, no setup, no infrastructure.

Built for AI agents: 25 JSON CLI commands purpose-built for LLM consumption. Also works great for humans.

## Install

```bash
pip install logler
```

Python 3.9+. Pre-built wheels include the Rust backend -- no compiler needed.

## Quick Start

**Python API:**

```python
from logler.investigate import search, follow_thread_hierarchy

# Find errors
results = search(files=["app.log"], level="ERROR", limit=5)
for entry in results["results"]:
    print(f"[{entry['entry']['level']}] {entry['entry']['message']}")

# Trace a request through services
hierarchy = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
```

**CLI (JSON output for agents):**

```bash
logler llm search app.log --level ERROR --tail 5
logler llm hierarchy app.log --root req-123
logler llm triage app.log            # quick incident assessment
```

**CLI (human-readable):**

```bash
logler view app.log --level ERROR    # rich terminal output
logler stats app.log                 # log file summary
```

## What It Does

```
                    app.log ─────┐
                    api.log ─────┤
                    db.log  ─────┤
                    cache.log ───┘
                         │
                    ┌────▼────┐
                    │  logler │  Rust parser + Python investigation
                    └────┬────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   Thread Hierarchy   Error Flow    Cross-Service
   req-001 (520ms)    Root Cause:   Timeline
   ├─ auth (45ms)     Redis conn    [api] req start
   ├─ product (450ms) refused       [db]  query
   │  └─ db (300ms)   Path: api →   [cache] miss
   └─ response (10ms) product →     [api] respond
                       cache
```

### Investigation Capabilities

| Capability | What It Does |
|-----------|-------------|
| **Search** | Filter by level, time, thread, pattern. Pagination, count-only mode. |
| **Thread Hierarchy** | Build request trees from span/parent_span fields. Bottleneck detection. |
| **Error Flow** | Trace error propagation: root cause, impact path, affected nodes. |
| **Cross-Service Timeline** | Reconstruct a request's journey across microservices. |
| **Comparison** | Diff two threads or time periods side-by-side. |
| **Smart Sampling** | Representative samples from large files (stratified, time-weighted). |
| **Metrics** | Extract numeric values, compute stats (min/max/p95/p99), z-score anomalies. |
| **Format Detection** | Auto-detect log formats. Drain algorithm template mining. |
| **Correlation** | Match events across files by field values or time windows. |
| **Sessions** | Stateful investigations with undo/redo and report generation. |

### Supported Formats

JSON (recommended), syslog (RFC 3164/5424, BSD), logfmt, Apache CLF, plain text. Auto-detected -- no configuration needed.

## Performance

Real numbers from the [benchmark suite](benchmarks/results/v3/REPORT.md)
(19 scenarios, deterministic data, Python 3.12, Rust backend):

| Operation | Speed | Context |
|-----------|-------|---------|
| Search throughput | **1.27M entries/sec** | Level filter, 50K entries |
| Hierarchy building | **349ms** | 50K entries (was 86s before optimization) |
| Follow thread | **0.36ms** | Correlation lookup, 1K entries |
| Cross-service timeline | **10.6ms** | 5 services, shared correlation |
| Error flow analysis | **0.14ms** | Small hierarchy |
| Token savings | **2540x** | count vs full output format |

Three optimization rounds drove hierarchy building from 86 seconds to 349ms (246x speedup) and reduced memory usage for database operations from 85 MB to 1 MB (83x reduction).

Full report with 19 charts: [benchmarks/results/v3/REPORT.md](benchmarks/results/v3/REPORT.md)

## Showcase

### Thread Hierarchy

```python
from logler.investigate import follow_thread_hierarchy

hierarchy = follow_thread_hierarchy(
    files=["app.log"],
    root_identifier="req-123",
    min_confidence=0.8,
)
```

```
api-gateway (req-001, 520ms)
├─ auth-service (45ms)
│  ├─ jwt-validate (5ms)
│  └─ user-lookup (25ms)
├─ product-service (450ms) SLOW
│  ├─ inventory-check (340ms)
│  │  └─ db-query (300ms)
│  └─ cache-update (45ms) ERROR
└─ response-assembly (10ms)
```

### Error Flow Analysis

```python
from logler.investigate import analyze_error_flow

error_flow = analyze_error_flow(files=["app.log"], root_identifier="req-123")
```

```
Root Cause:
  cache-update failed at 10:00:00.450Z
  Error: Redis connection refused
  Path: api-gateway -> product-service -> cache-update

Impact: 3 nodes affected, request degraded
Recommendation: Check Redis connectivity
```

### Cross-Service Timeline

```python
from logler.investigate import cross_service_timeline

timeline = cross_service_timeline(
    files={"api": ["api.log"], "db": ["db.log"], "cache": ["cache.log"]},
    correlation_id="req-12345",
)
for event in timeline["timeline"]:
    print(f"[{event['service']}] {event['entry']['message']}")
```

### Visualization Modes

**Tree** -- parent-child relationships | **Waterfall** -- temporal overlap | **Flamegraph** -- time distribution

```
Waterfall: req-001 (520ms)
api-gateway          ████████████████████████████████████████  520ms
  ├─ auth-service    ████                                      45ms
  ├─ product-service      ████████████████████████████████    450ms
  │  ├─ inventory              ██████████████████████         340ms
  │  └─ cache-update                              ████ ERR     45ms
  └─ response                                          ██      10ms
```

## LLM CLI

25 commands organized by workflow. All output structured JSON.

| Category | Commands |
|----------|----------|
| **Triage** | `triage`, `summarize`, `schema` |
| **Search** | `search`, `ids`, `sample`, `sql` |
| **Tracing** | `correlate`, `hierarchy`, `bottleneck`, `context`, `export` |
| **Comparison** | `compare`, `diff` |
| **Sessions** | `session create/list/query/note/conclude` |
| **Formats** | `format list/test/validate` |
| **Correlation** | `correlation list/run`, `correlate-events` |
| **Metrics** | `metrics`, `detect`, `templates`, `verify-pattern`, `emit` |

All file-based commands accept `--db path/to/sqler.db` to search [sqler](https://github.com/gabu-quest/sqler) databases directly.

Full reference: [docs/LLM_CLI_REFERENCE.md](docs/LLM_CLI_REFERENCE.md)

## Interactive Tours

17 hands-on [marimo](https://marimo.io) notebooks. Each is self-contained with sample data.

**[Launch in browser](https://gabu-quest.github.io/logler/)** (no install needed)

| Tour | Topics |
|------|--------|
| [01. Fundamentals](https://gabu-quest.github.io/logler/tour_01_fundamentals.html) | Search, filter, output formats |
| [02. Thread Tracking](https://gabu-quest.github.io/logler/tour_02_thread_tracking.html) | Grouping, correlation IDs |
| [03. Hierarchy](https://gabu-quest.github.io/logler/tour_03_hierarchy.html) | Tree views, waterfall, bottleneck |

<details>
<summary>All 17 tours</summary>

| Tour | Topics |
|------|--------|
| 01. Fundamentals | Search, filter, output formats |
| 02. Thread Tracking | Grouping, correlation IDs |
| 03. Hierarchy | Tree views, waterfall, bottleneck |
| 04. Investigation | Sessions, history, report generation |
| 05. Pattern Detection | Repeated patterns, frequency analysis |
| 06. Flamegraph | Performance visualization |
| 07. Error Flow | Root cause analysis, propagation chains |
| 08. Comparison | Diff hierarchies, compare threads |
| 09. Tracing Exports | Jaeger and Zipkin formats |
| 10. Sampling | Smart sampling strategies |
| 11. AI Insights | LLM investigation workflow |
| 12. Multi-File | Cross-service distributed tracing |
| 13. Live Watching | Real-time tailing, streaming |
| 14. Performance | 10K+ entries, benchmarks |
| 15. Filtering | Field filtering, complex queries |
| 16. Metrics | Numeric values, stats, anomaly detection |
| 17. Format Detection | Auto-detect formats, Drain template mining |

</details>

Run locally: `uv run marimo edit examples/tours/tour_01_fundamentals.py`

## When to Use Logler

**Good fit:**
- Debugging production incidents from log files
- AI agent log investigation (LLM-first JSON CLI)
- Cross-service distributed tracing (local files)
- Quick triage of large log files without infrastructure

**Consider alternatives:**
- Need log aggregation/storage: ELK, Loki, Datadog
- Need real-time alerting: Prometheus + Alertmanager
- Only need text search: ripgrep

## Documentation

| Resource | Description |
|----------|-------------|
| [API Reference](docs/API.md) | Contract-tested API (C02--C10) |
| [LLM CLI Reference](docs/LLM_CLI_REFERENCE.md) | 25 commands with flags |
| [Python API Guide](docs/LLM_README.md) | Library usage and examples |
| [Investigation API](docs/LLM_INVESTIGATION_API.md) | All investigation functions |
| [Interactive Tours](https://gabu-quest.github.io/logler/) | 17 marimo notebooks |
| [Benchmarks](benchmarks/results/v3/REPORT.md) | 19 scenarios with charts |
| [Web UI](https://github.com/gabu-quest/logler-web) | Vue3 + Naive-UI interface |

## Development

```bash
cargo build --release --all    # Build Rust backend
uv sync --all-groups           # Install Python deps
uv run pytest                  # 1250+ Python tests
cargo test --workspace         # 42 Rust tests
```

## License

MIT -- see [LICENSE](LICENSE) for details.
