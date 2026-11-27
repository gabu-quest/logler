# Logler

Rust-powered log viewer optimized for AI agents. Three tiers: Rust core -> PyO3 bridge ->
Python API/CLI. Layers, data flow, memory and limits: [ARCHITECTURE.md](./ARCHITECTURE.md).

## Architecture

```
crates/logler-core/src/     — Rust engine (parser, index, investigate, hierarchy)
crates/logler-py/src/lib.rs — PyO3 FFI bridge
src/logler/investigate.py   — Python API re-export facade (wraps submodules)
src/logler/llm_cli/         — LLM CLI package (JSON output, 8 submodules)
src/logler/cli.py           — Human CLI (view, stats, investigate, watch)
```

### Python Modules

| Module | Purpose |
|--------|---------|
| `investigate.py` | Re-export facade + Investigator class + M5/M6 wrappers |
| `_search_core.py` | Core search, follow, context, patterns, metadata (Rust FFI) |
| `_loading.py` | The one loader: each file goes into an investigator with its own format |
| `cache.py` | Parsed files behind the module-level functions (10 file sets, oldest out) |
| `hierarchy.py` | Thread hierarchy, error flow, bottleneck analysis, correlation chains |
| `comparison.py` | Thread/period comparison, cross-service timeline |
| `sampling.py` | Smart sampling strategies |
| `session.py` | InvestigationSession (stateful investigations) |
| `export.py` | Jaeger/Zipkin trace export |
| `types.py`, `models.py` | TypedDicts for every return shape; Pydantic v2 models of the same |
| `config.py` | Loader for `.logler/formats.yaml` and `.logler/correlations.yaml` |
| `correlator.py`, `event_correlator.py` | Rule-based and time-window correlation across files |
| `metrics.py` | Numeric value extraction, stats, z-score anomaly detection |
| `format_detector.py`, `builtin_formats.py` | Format detection, Drain templates, built-in formats |
| `sql.py` | DuckDB-powered SQL queries |
| `parser.py` | `LogParser`, a thin adapter over the Rust parser |
| `log_reader.py`, `watcher.py` | Lines of a file forwards, backwards and followed; file watcher |
| `db_source.py` | Reads a sqler database as a log source (`--db`) |
| `context.py` | Correlation IDs for programs that write logs |
| `helpers.py` | Shortcuts for common investigations |
| `cli.py`, `terminal.py`, `tree_formatter.py` | Human CLI and its Rich rendering |
| `tracker.py`, `safe_regex.py` | Thread tracking; regex compilation with limits |

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

Every command, flag and output shape: `docs/LLM_CLI_REFERENCE.md`. Exit codes: 0=success,
1=no results, 2=user error, 3=internal error.

`--db path/to/sqler.db` reads a sqler database beside or instead of FILES (qler tables are
detected). Without it: `context`, `format list/test/validate`, `correlation list`,
`session list/note/conclude`.

### Public API Contract (logler-web imports)

logler-web's FastAPI backend imports these from `logler.investigate`; keep their names,
arguments and return keys (`types.py`):

```python
search, extract_ids, follow_thread, get_context, find_patterns,
get_metadata, follow_thread_hierarchy, get_hierarchy_summary,
analyze_error_flow, cross_service_timeline, compare_threads,
smart_sample, extract_metrics, detect_formats, mine_log_templates
```

### Module Split Architecture

```
investigate.py (facade)
  ├── _search_core.py     ← foundation; imports only _loading and cache
  │     ├── _loading.py   ← imports config, nothing from _search_core
  │     └── cache.py      ← imports _loading and config
  ├── hierarchy.py, comparison.py, sampling.py   ← import from _search_core
  ├── session.py          ← imports from _search_core and comparison
  └── export.py           ← standalone
```

**Key rule:** from the package, `_search_core.py` imports only `_loading` and `cache` (and
`logler_rs`, conditionally). Other modules import from `_search_core`, never the reverse.

## Philosophy: Not a SQL Wrapper

Logler's value is its **own algorithms**: Rust parsing and indexing, correlation, sampling,
metrics, format detection. DuckDB (`sql.py`) is an escape hatch for ad-hoc queries, not the
foundation: search, hierarchy, correlation, metrics and sampling use logler's own engines.

**Tests and tours test the library, not DuckDB.** They call the public API (`search()`,
`follow_thread()`, `extract_metrics()`, ...), never raw SQL.

## Build

```bash
uv sync --extra dev        # builds the Rust extension with maturin, installs the dev tools
uv run ruff check && uv run ruff format --check
uv run mypy                # settings in [tool.mypy]; 0 errors expected
```

**Stale extension:** the extension is one abi3 file, `src/logler_rs/logler_rs.abi3.so`.
`uv sync` and `uv run` do not rebuild it when only Rust sources change. After a Rust change:

```bash
uv sync --extra dev --reinstall-package logler
```

## Test

```bash
uv run pytest
cargo test --workspace
```

- Deterministic fixtures with documented exact counts; assert exact values, not types or existence
- CLI tests use subprocess (`run_llm_command` helper)
- README contract tests (C02-C10) in `tests/test_readme.py` pin the public API examples of `docs/API.md`
- Tour notebook tests in `tests/test_tour_notebooks.py` (17 tours)
- Known flaky outside the repo root (relative paths): `test_rust_investigator`, `test_tail_glob_on_real_fixtures`

## Configuration

Custom formats live in `.logler/formats.yaml` (found by walking up from the log file's
folder) and correlation rules in `.logler/correlations.yaml`. Schema, examples and what a
broken file does: `docs/CONFIGURATION.md`.

In `config.py`: Pydantic v2 field validators only catch `ValueError`/`AssertionError`, so
`re.error` is caught and re-raised as `ValueError`. In format regexes `\w+` does not match
hyphens; use `[\w-]+` for IDs like `TH-042`.

## Log Formats and Levels

JSON (recommended), syslog (RFC 3164/5424 + BSD), logfmt, plaintext, Apache CLF; the parser
detects the format. BSD syslog without `<priority>` has no parsed timestamp.

The Rust level enum expects title case (`Error`, `Warn`, `Info`): `_parse_levels()` converts
user input, `_normalize_entry()` uppercases for display.

## Benchmarks, Hooks, Commits

- Benchmark commands, scales and the memory measurement rules: `benchmarks/README.md`; the
  published report is `docs/benchmarks/REPORT.md`. Never measure memory with `ru_maxrss`;
  use `tracemalloc` and VmRSS.
- Pre-commit hooks: ruff (lint and format), fix-end-of-files, trim-trailing-whitespace,
  cargo-fmt. A first commit attempt often fails (ruff auto-fixes): re-stage and commit again.
- No Co-Authored-By lines. Git user is sole author.
