# Logler Architecture

## Overview

Logler is a Rust-powered log investigation tool optimized for AI agents. It uses a three-tier architecture: Rust core engine, PyO3 bridge, and Python API/CLI.

```
┌──────────────────────────────────────────────────────────────────┐
│                        Python Layer                               │
│                                                                    │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐  │
│  │   cli.py (Human)    │  │    llm_cli/ (LLM Agent)         │  │
│  │                     │  │                                    │  │
│  │  - view             │  │  - 30 JSON commands                │  │
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

The module-level functions (`search()`, `follow_thread()`, `extract_ids()` and the rest) share
a cache of parsed files (`cache.py`): up to 10 sets of files are kept, and a set is parsed
again when one of its files, or the `.logler/formats.yaml` that applies to it, has changed.
So a second call on the same files does not parse them again. An `Investigator` holds its
own index for as long as it lives.

### Human CLI (`src/logler/cli.py`)

Rich terminal output for human users: `view`, `stats`, `investigate`, `watch`.

### LLM CLI (`src/logler/llm_cli/`)

A package of 30 JSON-output commands optimized for AI agents:
- Assessment: `triage`, `summarize`, `schema`
- Search: `search`, `ids`, `sample`, `sql`
- Tracing: `correlate`, `hierarchy`, `bottleneck`, `context`, `export`
- Comparison: `compare`, `diff`
- Sessions: `session create`, `list`, `query`, `note`, `conclude`
- Formats: `detect`, `templates`, `format list`, `test`, `validate`
- Correlation: `correlation list`, `run`, `correlate-events`
- Metrics and checks: `metrics`, `verify-pattern`, `emit`

Key features: `--count-only`, `--offset` pagination, `--compact` mode,
`--metadata-only`, `--max-bytes` truncation, relative `--after`/`--before`.

## Data Flow

### Search Query
```
CLI args → llm_cli/   → investigate.py → logler_rs (PyO3) → Rust search
                                                                │
                                                          Parse all files
                                                          Apply filters
                                                          Return JSON
                                                                │
CLI JSON ← llm_cli/   ← investigate.py ← logler_rs ←──────────┘
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

The measured numbers, with the machine they were measured on, are in
[docs/benchmarks/REPORT.md](docs/benchmarks/REPORT.md). Files of 1 GB and more are not
benchmarked.

Indexing uses rayon to parse on every core.

## Memory and Limits

- **The index holds all entries in memory.** The Rust backend (`PyInvestigator`) parses entire files into an in-memory index. At 600K+ entries, `load_files()` alone uses ~800 MB. Mitigations: `Investigator(sql_db_path=...)` for disk-backed DuckDB, engine caching to avoid redundant rebuilds, and two-phase search (filter and score with lightweight ~40-byte candidates, materialize only the final N results), which keeps `search()` from amplifying the index cost. A `DEFAULT_MAX_RESULTS` (10K) safety cap prevents unbounded queries; `limit=0` removes it. `count_only=True` skips materialization entirely, and `offset` pages without re-materializing skipped entries. Deferred: Rust-side loading that indexes file offsets without holding all entries in memory.
- **comparison.py.** `compare_time_periods()` pushes time windows to Rust via `time_start`/`time_end` instead of materialising all entries. The `cross_service_timeline()` fallback (no correlation or trace ID) is capped at `_DEFAULT_TIMELINE_LIMIT` (10K). `_analyze_thread()` computes duration from `min()`/`max()` timestamps, so unsorted input does not skew it.
- **One SQL loader.** `sql.py`'s `SqlEngine.load_entries()` serves `llm sql` and `Investigator.sql_query()`: rows are staged to a temporary CSV and bulk-loaded with DuckDB's `read_csv`, a chunk at a time, and the CSV is removed when the load ends or fails. `Investigator._get_sql_engine()` feeds it from the Rust index with `get_entries_page(offset, limit)` in pages of 10,000, on the first SQL call; the engine is kept until `load_files()` is called again.
- **BSD syslog without a `<priority>` prefix** has no parsed timestamp, so time filters cannot select those entries. Its level is inferred from the message (auth failures are ERROR, out of memory is FATAL, and so on).

## Build & Test

```bash
uv sync --extra dev                   # Build the extension, install the Python deps and dev tools
cargo test --workspace                # Rust tests
uv run pytest                         # Python tests
```

`uv sync` builds the Rust extension with maturin and puts it at
`src/logler_rs/logler_rs.abi3.so`, one file for every supported Python version. It does not
build again when only Rust sources change. After a Rust change:

```bash
uv sync --extra dev --reinstall-package logler
```

## Key Dependencies

**Rust**: chrono, serde, regex, rayon (parallel), pyo3, uuid
**Python**: click, rich, duckdb, pydantic, watchdog
