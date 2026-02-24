# Roadmap: Sqler Bridge

## Milestones

### M-1: Database Bridge & Correlation Context ✅
- `db_source.py` module with `db_to_jsonl()` and auto-detect mappings
- `Investigator.load_from_db()` convenience method
- `--db` flag on `search` command
- qler-specific mappings (qler_jobs, qler_job_attempts)
- Correlation context propagation from sqler databases

### M-2: Universal --db CLI Support ✅
- Shared `db_source_option` decorator and `_db_file_source` context manager in `_core.py`
- `--db` on all 20+ LLM CLI commands (search, schema, ids, sample, triage, summarize, sql, correlate, hierarchy, bottleneck, export, compare, diff, verify-pattern, emit, metrics, detect, templates, correlation run, correlate-events)
- Refactored `search` to use shared infrastructure
- Automatic temp file cleanup via context manager
- Universal test coverage for `--db` across commands

### M-3: Session DB Support ✅
- `--db` on `session create` with persistent db_path in session JSON
- `--db` on `session query` with stored/override db_path via `_db_file_source`
- Cross-session correlation tracking (correlation IDs recorded per session)
- `session list` shows `has_db` and `correlation_count` fields
- Security hardening: restricted template formatter, realpath, dir_okay=False

### M-4: Human CLI DB Support ⬚
- `--db` support in human CLI (`cli.py`)
- Rich terminal rendering of database-sourced data
- Interactive database exploration
