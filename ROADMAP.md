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

### M-3: Session DB Support ⬚
- `--db` support in session commands (create, query, note, conclude)
- Persistent session state backed by sqler database
- Cross-session correlation tracking

### M-4: Human CLI DB Support ⬚
- `--db` support in human CLI (`cli.py`)
- Rich terminal rendering of database-sourced data
- Interactive database exploration
