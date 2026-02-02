# Logler

Rust-powered log viewer optimized for AI agents. Three-tier architecture:
Rust core -> PyO3 bridge -> Python API/CLI.

## Architecture

```
crates/logler-core/src/     — Rust engine (parser, index, investigate, hierarchy)
crates/logler-py/src/lib.rs — PyO3 FFI bridge
src/logler/investigate.py   — Python API (wraps Rust via logler_rs)
src/logler/llm_cli.py       — 17 LLM CLI commands (JSON output)
src/logler/cli.py           — Human CLI (view, stats, investigate)
```

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
uv run pytest              # 680+ Python tests
cargo test --workspace     # 26 Rust tests
```

## CLI

```bash
python -m logler.cli llm <command>
```

Exit codes: 0=success, 1=no results, 2=user error, 3=internal error

17 LLM commands: triage, search, ids, summarize, correlate, hierarchy,
bottleneck, compare, diff, sql, schema, sample, verify-pattern, context,
emit, export, session

## Test Patterns

- Deterministic fixtures with documented exact counts
- CLI tests use subprocess (`run_llm_command` helper)
- Assert exact values, not types or existence
- README contract tests (C02-C10) enforce public API examples

## Search CLI Flags

Key flags for `logler llm search`:
- `--count-only` — Return only match count (no results array)
- `--offset N` — Skip first N results (pagination)
- `--compact` — Short field names (ts/lv/msg/svc/th/cid/trc)
- `--metadata-only` — Aggregations only, no results
- `--max-bytes N` — Truncate output to fit byte budget
- `--after/-before` — Supports relative time: `--after=-1h --before=-30m`

`--max-bytes` also available on: correlate, hierarchy, bottleneck, summarize.

## Log Formats Supported

JSON (recommended), syslog (RFC 3164/5424 + BSD), logfmt, plaintext, Apache CLF.
Parser auto-detects format. BSD syslog without `<priority>` prefix uses
pattern-based level inference (auth failures → ERROR, OOM → FATAL, etc.).

## Known Issues

- Tour 12 duplicates entries when correlation_id AND trace_id match
- Rust backend crashes with time_start/time_end on some log formats (BSD syslog)

## Key Dependencies

Rust: chrono, serde, regex, rayon (parallel), pyo3
Python: click, rich, duckdb, pydantic, watchdog

## Commit Rules

No Co-Authored-By lines. Git user is sole author.
