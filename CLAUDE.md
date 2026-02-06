# Logler

Rust-powered log viewer optimized for AI agents. Three-tier architecture:
Rust core -> PyO3 bridge -> Python API/CLI.

## Architecture

```
crates/logler-core/src/     — Rust engine (parser, index, investigate, hierarchy)
crates/logler-py/src/lib.rs — PyO3 FFI bridge
src/logler/investigate.py   — Python API (wraps Rust via logler_rs)
src/logler/llm_cli.py       — LLM CLI commands (JSON output)
src/logler/cli.py            — Human CLI (view, stats, investigate)
```

### Python Modules

| Module | Purpose |
|--------|---------|
| `investigate.py` | Core API: search, hierarchy, sessions, compare, timeline |
| `llm_cli.py` | Click-based LLM CLI (JSON output, exit codes) |
| `cli.py` | Human CLI (rich terminal output) |
| `config.py` | `.logler.toml` config loader (Pydantic v2 models) |
| `correlator.py` | Virtual trace correlation engine (field match + temporal) |
| `event_correlator.py` | Cross-file event correlation (time windows + triggers) |
| `metrics.py` | Numeric value extraction, stats, z-score anomaly detection |
| `format_detector.py` | Format auto-detection + Drain template mining |
| `builtin_formats.py` | Built-in format library (syslog, logfmt, CLF, etc.) |
| `tree_formatter.py` | Tree and waterfall rendering |
| `sql.py` | DuckDB-powered SQL queries |
| `tracker.py` | Thread/correlation tracking |
| `parser.py` | Log format parsing |
| `models.py` | Data models |
| `safe_regex.py` | Regex compilation with safety limits |
| `cache.py` | LRU caching |
| `helpers.py` | Shared utilities |
| `watcher.py` | File watcher (watchdog) |
| `terminal.py` | Rich terminal rendering |
| `bootstrap.py` | Package initialization |

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

### Known Flaky Tests

- `test_rust_investigator` — fails with relative paths when run outside repo root
- `test_tail_glob_on_real_fixtures` — glob finds 0 files outside repo root

## CLI

```bash
python -m logler.cli llm <command>
```

Exit codes: 0=success, 1=no results, 2=user error, 3=internal error

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
- `format save` — Save format to config

**Correlations (M2/M3):**
- `correlation list` — List configured correlation rules
- `correlation run` — Run correlation rules (all or by group)
- `correlate-events` — Cross-file event correlation with time windows

### Search CLI Flags

Key flags for `logler llm search`:
- `--count-only` — Return only match count (no results array)
- `--offset N` — Skip first N results (pagination)
- `--compact` — Short field names (ln/ts/lv/msg/src/th/cid/trc/sid/svc)
- `--metadata-only` — Aggregations only, no results
- `--max-bytes N` — Truncate output to fit byte budget
- `--after/-before` — Supports relative time: `--after=-1h --before=-30m`

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
- `investigate.py` has `except Exception: return None` patterns that silently swallow errors — ensure all imports are local inside these try blocks

## Key Dependencies

Rust: chrono, serde, regex, rayon (parallel), pyo3
Python: click, rich, duckdb, pydantic, watchdog

## Pre-commit Hooks

black, ruff, fix-end-of-files, trim-trailing-whitespace, cargo-fmt.
First commit attempt often fails (ruff/black auto-fix). Re-stage and commit again.

## Commit Rules

No Co-Authored-By lines. Git user is sole author.
