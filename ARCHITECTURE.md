# Logler Architecture

## Overview

Logler is a Rust-powered log investigation tool optimized for AI agents. It uses a three-tier architecture: Rust core engine, PyO3 bridge, and Python API/CLI.

```
┌──────────────────────────────────────────────────────────────────┐
│                        Python Layer                               │
│                                                                    │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐  │
│  │   cli.py (Human)    │  │    llm_cli.py (LLM Agent)       │  │
│  │                     │  │                                    │  │
│  │  - view             │  │  - 17 JSON commands                │  │
│  │  - stats            │  │  - Pagination, compact mode        │  │
│  │  - investigate      │  │  - Max-bytes truncation            │  │
│  │  - watch            │  │  - Consistent exit codes           │  │
│  └─────────┬───────────┘  └────────────┬─────────────────────┘  │
│            │                            │                          │
│  ┌─────────▼────────────────────────────▼─────────────────────┐  │
│  │              investigate.py (Python API)                     │  │
│  │                                                              │  │
│  │  - search(), follow_thread(), extract_ids()                  │  │
│  │  - follow_thread_hierarchy(), get_metadata()                 │  │
│  │  - cross_service_timeline(), smart_sample()                  │  │
│  │  - InvestigationSession (stateful analysis)                  │  │
│  └─────────────────────────┬────────────────────────────────┘  │
│                              │                                     │
│  ┌───────────────────────────▼────────────────────────────────┐  │
│  │              logler_rs (PyO3 Bridge)                        │  │
│  │                                                              │  │
│  │  PyInvestigator: load_files(), search(), follow_thread()     │  │
│  └───────────────────────────┬────────────────────────────────┘  │
└──────────────────────────────┼────────────────────────────────────┘
                               │ FFI
┌──────────────────────────────▼────────────────────────────────────┐
│                         Rust Core                                  │
│                    (crates/logler-core)                            │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   parser.rs   │  │   index.rs   │  │   investigate.rs     │  │
│  │               │  │              │  │                      │  │
│  │  - Auto-      │  │  - File      │  │  - Search            │  │
│  │    detect     │  │    indexing   │  │  - Thread follow     │  │
│  │  - JSON       │  │  - Line      │  │  - ID extraction     │  │
│  │  - Syslog     │  │    offsets   │  │  - Time filtering    │  │
│  │  - Logfmt     │  │  - Parallel  │  │  - Context lines     │  │
│  │  - Apache CLF │  │    loading   │  │                      │  │
│  │  - PlainText  │  │              │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                    │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐  │
│  │  hierarchy.rs │  │               types.rs                   │  │
│  │               │  │                                          │  │
│  │  - Tree build │  │  LogEntry, LogLevel, LogFormat           │  │
│  │  - duration_ms│  │  Thread/trace/correlation IDs            │  │
│  │  - Bottleneck │  │  Hierarchy nodes                         │  │
│  │  - Waterfall  │  │                                          │  │
│  └──────────────┘  └──────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

## Components

### Rust Core (`crates/logler-core`)

The performance engine. All parsing, indexing, and searching happens here.

**parser.rs** — Log format detection and parsing
- Auto-detects: JSON, Syslog (RFC 3164/5424 + BSD), logfmt, Apache CLF, plaintext
- Extracts: timestamp, level, message, thread_id, correlation_id, trace_id, span_id, service_name
- BSD syslog without `<priority>` uses pattern-based level inference
- Custom regex support via named capture groups

**index.rs** — File indexing with rayon parallel processing

**investigate.rs** — Search engine with multi-dimensional filtering
- Level, pattern, thread, correlation, trace, service filters
- Exclusion filters (exclude_level, exclude_pattern)
- Time range filtering
- Tail mode (last N by timestamp)
- Context lines around matches

**hierarchy.rs** — Thread/span hierarchy builder
- Explicit parent_span_id (OpenTelemetry)
- Naming pattern inference (worker-1.task-a)
- Temporal inference
- Duration from explicit `duration_ms` fields or timestamp calculation
- Bottleneck detection

### PyO3 Bridge (`crates/logler-py`)

Thin FFI layer exposing Rust functions to Python via PyO3/maturin.
The compiled `.so` lives in the `logler_rs` package.

### Python API (`src/logler/investigate.py`)

Wraps Rust calls with Python ergonomics. Adds:
- DuckDB SQL interface
- Investigation sessions
- Smart sampling strategies
- Cross-service timeline
- Report generation

### Human CLI (`src/logler/cli.py`)

Rich terminal output for human users: `view`, `stats`, `investigate`, `watch`.

### LLM CLI (`src/logler/llm_cli.py`)

17 JSON-output commands optimized for AI agents:
- Assessment: `triage`, `summarize`
- Search: `search`, `ids`, `schema`, `sample`
- Tracing: `correlate`, `hierarchy`, `bottleneck`, `compare`
- Analysis: `sql`, `verify-pattern`, `diff`, `context`
- Utilities: `emit`, `export`, `session`

Key features: `--count-only`, `--offset` pagination, `--compact` mode,
`--metadata-only`, `--max-bytes` truncation, relative `--after`/`--before`.

## Data Flow

### Search Query
```
CLI args → llm_cli.py → investigate.py → logler_rs (PyO3) → Rust search
                                                                │
                                                          Parse all files
                                                          Apply filters
                                                          Return JSON
                                                                │
CLI JSON ← llm_cli.py ← investigate.py ← logler_rs ←──────────┘
```

### Hierarchy Build
```
identifier → investigate.py → logler_rs → Rust hierarchy builder
                                              │
                                        Load files, find entries
                                        Build parent-child tree
                                        Calculate durations
                                        Find bottleneck
                                              │
JSON tree ← investigate.py ← logler_rs ←─────┘
```

## Performance

- **Search**: <50ms for 1GB files (~20 GB/s throughput)
- **Thread follow**: <20ms for 1GB files
- **Hierarchy build**: <100ms for 1GB files
- **Parallel indexing**: Uses rayon for multi-core file loading

## Build & Test

```bash
cargo build --release --all          # Build Rust
uv sync --all-groups                  # Install Python deps
cargo test --workspace                # 26 Rust tests
uv run pytest                         # 680+ Python tests
```

After Rust changes, copy the `.so` manually:
```bash
cp target/release/liblogler_rs.so \
   .venv/lib/python3.12/site-packages/logler_rs/logler_rs.cpython-312-x86_64-linux-gnu.so
```

## Key Dependencies

**Rust**: chrono, serde, regex, rayon (parallel), pyo3, uuid
**Python**: click, rich, duckdb, pydantic, watchdog
