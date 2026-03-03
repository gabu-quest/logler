# Logler

Rust-powered log viewer optimized for AI agents. Three-tier architecture:
Rust core -> PyO3 bridge -> Python API/CLI.

## Active Roadmaps
- [Sqler Bridge](./ROADMAP.md) — current milestone: M-2 (complete)

## Architecture

```
crates/logler-core/src/     — Rust engine (parser, index, investigate, hierarchy)
crates/logler-py/src/lib.rs — PyO3 FFI bridge
src/logler/investigate.py   — Python API re-export facade (wraps submodules)
src/logler/llm_cli/         — LLM CLI package (JSON output, 8 submodules)
src/logler/cli.py            — Human CLI (view, stats, investigate)
```

### Python Modules

| Module | Purpose |
|--------|---------|
| `investigate.py` | Re-export facade + Investigator class + M5/M6 wrappers |
| `_search_core.py` | Core search, follow, context, patterns, metadata (Rust FFI) |
| `hierarchy.py` | Thread hierarchy, error flow, bottleneck analysis, correlation chains |
| `comparison.py` | Thread/period comparison, cross-service timeline |
| `sampling.py` | Smart sampling strategies |
| `session.py` | InvestigationSession class (stateful investigations) |
| `export.py` | Jaeger/Zipkin trace export |
| `types.py` | TypedDict definitions for all return shapes |
| `llm_cli/` | Click CLI package (8 submodules, see below) |
| `cli.py` | Human CLI (rich terminal output) |
| `config.py` | `.logler.toml` config loader (Pydantic v2 models) |
| `correlator.py` | Virtual trace correlation engine (field match + temporal) |
| `event_correlator.py` | Cross-file event correlation (time windows + triggers) |
| `metrics.py` | Numeric value extraction, stats, z-score anomaly detection |
| `format_detector.py` | Format auto-detection + Drain template mining |
| `builtin_formats.py` | Built-in format library (syslog, logfmt, CLF, etc.) |
| `models.py` | Pydantic v2 data models |
| `tree_formatter.py` | Tree and waterfall rendering |
| `sql.py` | DuckDB-powered SQL queries |
| `tracker.py` | Thread/correlation tracking |
| `parser.py` | Log format parsing |
| `safe_regex.py` | Regex compilation with safety limits |
| `cache.py` | LRU caching |
| `helpers.py` | Shared utilities |
| `watcher.py` | File watcher (watchdog) |
| `terminal.py` | Rich terminal rendering |
| `bootstrap.py` | Package initialization |

### LLM CLI Package (`llm_cli/`)

| Submodule | Commands |
|-----------|----------|
| `_core.py` | Shared: exit codes, `_output_json`, `_error_json`, `_expand_globs`, `time_filter_options` |
| `_search.py` | schema, search, ids, sample, triage, summarize, sql |
| `_trace.py` | correlate, hierarchy, bottleneck, context, export |
| `_compare.py` | compare, diff |
| `_session.py` | session group (create, list, query, note, conclude) |
| `_format.py` | format group (list, test, validate) |
| `_correlation.py` | correlation group (list, run), correlate-events |
| `_metrics.py` | verify-pattern, emit, metrics, detect, templates |

### Public API Contract (logler-web imports)

These 13+ functions are imported by logler-web's FastAPI backend:

```python
from logler.investigate import (
    search, extract_ids, follow_thread, get_context, find_patterns,
    get_metadata, follow_thread_hierarchy, get_hierarchy_summary,
    analyze_error_flow, cross_service_timeline, compare_threads,
    smart_sample, extract_metrics, detect_formats, mine_log_templates,
)
```

All return TypedDict-documented dicts. See `types.py` for shapes.

### Module Split Architecture

```
investigate.py (facade)
  ├── _search_core.py     ← foundation, zero circular imports
  ├── hierarchy.py         ← imports from _search_core
  ├── comparison.py        ← imports from _search_core
  ├── sampling.py          ← imports from _search_core
  ├── session.py           ← imports from investigate (facade)
  └── export.py            ← standalone
```

**Key rule:** `_search_core.py` has zero logler submodule imports (only `.safe_regex` and conditional `logler_rs`). All other modules import from `_search_core` — never the reverse.

## Philosophy: Not a SQL Wrapper

Logler's value is in its **own algorithms** — Rust parsing/indexing, Python correlation engines,
sampling strategies, metrics extraction, format detection. DuckDB/SQL is an optional power-user
escape hatch (`sql.py`), not the foundation.

**SQL passthrough is OK** where it genuinely makes sense (ad-hoc queries, aggregations DuckDB
is built for). Don't reinvent the wheel. But the library's core paths (search, hierarchy,
correlation, metrics, sampling) must use logler's own engines.

**Tests and tours MUST test the library, not DuckDB.** Every test exercises logler's public API
(`search()`, `follow_thread()`, `extract_metrics()`, etc.). Testing SQL passthrough would be
testing DuckDB, not logler. Tours demonstrate logler's capabilities, not SQL syntax.

## Build

```bash
cargo build --release --all
uv sync --all-groups
```

### Stale .so gotcha

After Rust changes, `maturin develop` may not update the extension.
Manual fix:

```bash
cp target/release/liblogler_rs.so \
   .venv/lib/python3.12/site-packages/logler_rs/logler_rs.cpython-312-x86_64-linux-gnu.so
```

## Test

```bash
uv run pytest              # 1000+ Python tests
cargo test --workspace     # 26 Rust tests
```

### Test Patterns

- Deterministic fixtures with documented exact counts
- CLI tests use subprocess (`run_llm_command` helper)
- Assert exact values, not types or existence
- README contract tests (C02-C10) in `tests/test_readme.py` enforce public API examples
- Tour notebook tests in `tests/test_tour_notebooks.py` (17 tours)
- **Tests exercise logler's API, never raw SQL** — we test the library, not DuckDB

### Known Flaky Tests

- `test_rust_investigator` — fails with relative paths when run outside repo root
- `test_tail_glob_on_real_fixtures` — glob finds 0 files outside repo root

## CLI

```bash
python -m logler.cli llm <command>
```

Exit codes: 0=success, 1=no results, 2=user error, 3=internal error

### Database Source (`--db`)

All file-based LLM commands accept `--db path/to/sqler.db` as an alternative to FILES.
Converts sqler database rows to JSONL on the fly; auto-detects qler tables.
Can combine `--db` with FILES to search both sources.
Only `context` (needs file+line) and session commands lack `--db`.

### LLM Commands (JSON output)

**Assessment:** triage, summarize, schema
**Discovery:** ids
**Search:** search, sql
**Tracing:** correlate, hierarchy, bottleneck
**Comparison:** compare, diff
**Utilities:** sample, context, export, emit, session, verify-pattern

**Metrics & Detection (M5/M6):**
- `metrics` — Extract numeric values with stats (min/max/mean/p95/p99), anomaly detection
- `detect` — Auto-detect log format with confidence scoring
- `templates` — Drain algorithm template mining

**Custom Formats (M1):**
- `format list` — List configured formats
- `format test` — Test a format against a file
- `format validate` — Validate a format definition against a file

**Correlations (M2/M3):**
- `correlation list` — List configured correlation rules
- `correlation run` — Run correlation rules (all or by group)
- `correlate-events` — Cross-file event correlation with time windows

### Search CLI Flags

Key flags for `logler llm search`:
- `--count-only` — Rust-side: skips materialization entirely, returns `{"total_matches": N}` with zero memory overhead
- `--offset N` — Rust-side pagination: candidates are sorted once, then `skip(N).take(limit)` before materialization
- `--compact` — Short field names (ln/ts/lv/msg/src/th/cid/trc/sid/svc)
- `--metadata-only` — Aggregations only, no results array
- `--max-bytes N` — Truncate output to fit byte budget
- `--after/--before` — Supports relative time: `--after=-1h --before=-30m`

Pagination example: `--offset 100 --limit 100` fetches page 2. `has_more` in the response indicates more pages exist.

`--max-bytes` also available on: correlate, hierarchy, bottleneck, summarize.

## Configuration

### `.logler.toml`

```toml
# Custom log format (M1)
[formats.my-app]
pattern = '(?P<timestamp>\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+(?P<level>\w+)\s+\[(?P<thread_id>[\w-]+)\]\s+(?P<message>.*)'
timestamp_format = "%Y-%m-%dT%H:%M:%S%.fZ"

# Correlation rules (M2)
[correlations.request-tracking]
rules = [
  { type = "field_match", source_field = "correlation_id", target_field = "correlation_id" },
  { type = "temporal", window = "5s", anchor_field = "trace_id" },
]
```

### Config Module Gotchas

- Pydantic v2 field validators only catch `ValueError`/`AssertionError`
- `re.error` must be caught and re-raised as `ValueError` in validators
- `\w+` doesn't match hyphens — use `[\w-]+` for IDs like `TH-042`

## Log Formats Supported

JSON (recommended), syslog (RFC 3164/5424 + BSD), logfmt, plaintext, Apache CLF.
Parser auto-detects format. BSD syslog without `<priority>` prefix uses
pattern-based level inference (auth failures -> ERROR, OOM -> FATAL, etc.).

## Known Limitations

- BSD syslog entries without `<priority>` prefix have no parsed timestamps; time-based filtering is unavailable for these entries
- `_search_core.py` has `except Exception: return None` patterns that silently swallow errors — ensure all imports are local inside these try blocks
- Rust level enum expects title case (`Error`, `Warn`, `Info`) — `_parse_levels()` converts user input, `_normalize_entry()` uppercases for display
- **Investigator index holds all entries in memory** — the Rust backend (`PyInvestigator`) parses entire files into an in-memory index. At 600K+ entries, `load_files()` alone uses ~800 MB. Mitigations: `Investigator(sql_db_path=...)` for disk-backed DuckDB, engine caching to avoid redundant rebuilds, and **two-phase search** (filter+score with lightweight ~40-byte candidates, materialize only the final N results) which prevents `search()` from amplifying the index cost. A `DEFAULT_MAX_RESULTS` (10K) safety cap prevents unbounded queries; callers needing more can pass an explicit `limit`. `count_only=True` skips materialization entirely, and `offset` enables pagination without re-materializing skipped entries. Deferred: lazy/paginated Rust-side loading that indexes file offsets without holding all entries in memory (requires Rust refactor of `PyInvestigator`)
- **comparison.py OOM mitigations** — `compare_time_periods()` pushes time windows to Rust via `time_start`/`time_end` instead of materialising all entries. `cross_service_timeline()` fallback (no correlation/trace ID) is capped at `_DEFAULT_TIMELINE_LIMIT` (10K). `_analyze_thread()` computes duration from `min()`/`max()` timestamps instead of positional first/last (robust to unsorted input).
- **CLI `sql` command streams into DuckDB** — log entries are parsed and inserted in batches of 5,000 via `executemany()` instead of accumulating all entries in a list then building all tuples. Eliminates ~300 MB peak at 600K entries.
- **`_get_sql_engine()` paginated** — fetches entries in pages of `_SQL_ENGINE_PAGE_SIZE` (10K) via `search(limit=N, offset=M)` instead of `search(limit=0)`. Each page is converted to SimpleNamespace, inserted into DuckDB, then discarded. Memory stays bounded to ~one page (~50 MB) regardless of total entry count.

## Key Dependencies

Rust: chrono, serde, regex, rayon (parallel), pyo3
Python: click, rich, duckdb, pydantic, watchdog

## Benchmarks

```bash
uv run python -m benchmarks run --scale small       # Run all 14 scenarios
uv run python -m benchmarks list                      # List available scenarios
uv run python -m benchmarks plot -i results/latest.json  # Generate charts
uv run python -m benchmarks compare -b v1.json -c v2.json -o results/v2  # Before/after comparison
```

- 14 scenarios across 5 suites (search, hierarchy, correlation, output, sampling)
- Scales: small (1K/10K/50K), medium (10K/50K/100K), large (50K/100K/500K)
- Deterministic data generation (seeded RNG), precision timing (warmup + percentiles)
- v1 baseline preserved at `benchmarks/results/v1/baseline.json`
- Comparison report generator produces scientific before/after analysis with confidence levels

## Pre-commit Hooks

black, ruff, fix-end-of-files, trim-trailing-whitespace, cargo-fmt.
First commit attempt often fails (ruff/black auto-fix). Re-stage and commit again.

## Commit Rules

No Co-Authored-By lines. Git user is sole author.
