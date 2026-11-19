<p align="center">
  <img src="assets/logler-logo.png" width="200" alt="logler">
</p>

<h3 align="center">Log investigation for people and AI agents, with a Rust parser</h3>

<p align="center">
  <a href="https://pypi.org/project/logler/"><img src="https://img.shields.io/pypi/v/logler.svg?logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT"></a>
  <a href="https://github.com/gabu-quest/logler/actions"><img src="https://img.shields.io/github/actions/workflow/status/gabu-quest/logler/ci.yml?logo=github&label=CI" alt="CI"></a>
</p>

<p align="center">
  English | <a href="README.ja.md">日本語</a>
</p>

---

logler reads log files where they are and answers questions about them: which requests failed, what a request did across services, where the time went. It sits between `grep`, which finds strings and knows no structure, and a log platform, which needs servers. Nothing is uploaded and nothing runs in the background.

Every investigation command has a JSON form under `logler llm`, made for an AI agent to call; the same engine is a Python library and a terminal viewer.

## Install

```bash
pip install logler
```

Python 3.12 or newer. The wheels include the Rust parser, so no compiler is needed.

## Quick start

Save five lines as `app.log`:

```json
{"timestamp":"2026-11-14T10:00:00.000Z","level":"INFO","message":"request start","thread_id":"req-123","span_id":"a","service":"api"}
{"timestamp":"2026-11-14T10:00:00.050Z","level":"INFO","message":"auth ok","thread_id":"req-123","span_id":"b","parent_span_id":"a","service":"auth"}
{"timestamp":"2026-11-14T10:00:00.450Z","level":"ERROR","message":"Redis connection refused","thread_id":"req-123","span_id":"c","parent_span_id":"a","service":"cache"}
{"timestamp":"2026-11-14T10:00:00.520Z","level":"INFO","message":"request done","thread_id":"req-123","span_id":"a","service":"api"}
{"timestamp":"2026-11-14T10:00:01.000Z","level":"ERROR","message":"timeout talking to db","thread_id":"req-124","span_id":"d","service":"api"}
```

**For an agent** (JSON out):

```console
$ logler llm triage app.log
{"assessment": {"severity": "critical", "confidence": 0.95, "summary": "Error rate: 40.0%, 2 errors in 5 entries"}, ...}

$ logler llm search app.log --level ERROR --tail 5
$ logler llm hierarchy req-123 --files app.log
```

**For a person:**

```bash
logler view app.log --level ERROR    # coloured terminal output
logler stats app.log                 # counts per level
```

**From Python:**

```python
from logler.investigate import follow_thread_hierarchy, search

results = search(files=["app.log"], level="ERROR", limit=5)
for hit in results["results"]:
    print(f"[{hit['entry']['level']}] {hit['entry']['message']}")
# [ERROR] Redis connection refused
# [ERROR] timeout talking to db

tree = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
```

## What it can do

| | |
|---|---|
| **Search** | Filter by level, time, thread, service or pattern; page through results or only count them |
| **Request trees** | Build the parent and child spans of one request, and find the slowest branch |
| **Error flow** | From an error, the path it travelled and the spans it affected |
| **Across services** | One request's timeline across several log files |
| **Compare** | Two requests, or two time periods, side by side |
| **Sample** | A representative sample of a large file |
| **Metrics** | Numbers pulled from log lines, with statistics and outliers |
| **Formats** | Detect the format; mine recurring message templates |
| **SQL** | Query log files with DuckDB |
| **Sessions** | A saved investigation with notes and a report |

Formats read without configuration: JSON (the most reliable), syslog (RFC 3164 and 5424), logfmt, Apache common log format, plain text. A format of your own is a regex in `.logler/formats.yaml` ([docs/CONFIGURATION.md](docs/CONFIGURATION.md)).

The request tree of `req-123` in the quick-start file, as `format_tree()` prints it:

```
└── request start (2 entries, 520ms)
    ├── auth ok (1 entries, <1ms)
    └── ❌ [1 errors] Redis connection refused (1 entries, <1ms)
```

## The agent commands

All under `logler llm`, all JSON. Exit code 0 means results, 1 means none, 2 an error of yours (a bad argument, a file that cannot be read), 3 an internal error.

| Purpose | Commands |
|---|---|
| First look | `triage`, `summarize`, `schema` |
| Search | `search`, `ids`, `sample`, `sql` |
| Tracing | `correlate`, `hierarchy`, `bottleneck`, `context`, `export` |
| Comparison | `compare`, `diff` |
| Sessions | `session create/list/query/note/conclude` |
| Formats | `detect`, `format list/test/validate`, `templates` |
| Correlation | `correlation list/run`, `correlate-events` |
| Metrics and checks | `metrics`, `verify-pattern`, `emit` |

The commands that read log files, all but `context` and `format test`, also take `--db path/to/app.db` and read the log records stored in a [sqler](https://github.com/gabu-quest/sqler) database, which is how [qler](https://github.com/gabu-quest/qler)'s `qler logs` shows a job's log lines.

Full reference: [docs/LLM_CLI_REFERENCE.md](docs/LLM_CLI_REFERENCE.md)

## When to use it

Good for: an incident where the evidence is log files on a disk; an agent that has to investigate logs; following one request through several services' files.

Use something else when you need to store and aggregate logs (Loki, ELK, Datadog), alert in real time (Prometheus with Alertmanager), or only search text (ripgrep).

## Interactive tours

Seventeen [marimo](https://marimo.io) notebooks with their own sample data: **[open them in the browser](https://gabu-quest.github.io/logler/)**, or run one locally with `uv run marimo edit examples/tours/tour_01_fundamentals.py`.

| Tour | Topics |
|------|--------|
| 01. Fundamentals | Search, filter, output formats |
| 02. Thread Tracking | Grouping, correlation IDs |
| 03. Hierarchy | Tree views, waterfall, bottleneck |
| 04. Investigation | Sessions, history, reports |
| 05. Pattern Detection | Repeated patterns, frequency |
| 06. Flamegraph | Where the time went |
| 07. Error Flow | Root cause, propagation |
| 08. Comparison | Diff trees, compare threads |
| 09. Tracing Exports | Jaeger and Zipkin formats |
| 10. Sampling | Sampling strategies |
| 11. AI Insights | An agent's investigation, step by step |
| 12. Multi-File | One request across services |
| 13. Live Watching | Tailing |
| 14. Performance | Large files |
| 15. Filtering | Field filters, complex queries |
| 16. Metrics | Numbers, statistics, outliers |
| 17. Format Detection | Formats and templates |

## Documentation

| | |
|---|---|
| [API reference](docs/API.md) | The Python API and its tested contracts |
| [Agent command reference](docs/LLM_CLI_REFERENCE.md) | Every `logler llm` command and flag |
| [Python guide](docs/LLM_README.md) | Library usage |
| [Configuration](docs/CONFIGURATION.md) | Your own log formats and correlation rules |
| [Timestamps](docs/TIMESTAMPS.md) | Which spellings of a time are read, and how the zone is decided |
| [Request trees](docs/HIERARCHY_GUIDE.md) | How a request's spans are found and shown |
| [Changelog](CHANGELOG.md) | What changed, and what to change when upgrading |
| [Web UI](https://github.com/gabu-quest/logler-web) | A browser interface, in its own repository |

## The -ler family

| Package | What it is |
|---|---|
| [sqler](https://github.com/gabu-quest/sqler) | JSON documents in SQLite |
| [qler](https://github.com/gabu-quest/qler) | A background job queue built on sqler |
| **logler** | This package; `--db` reads log records from a sqler database |

## Development

```bash
uv sync --extra dev            # builds the Rust extension, installs the dev tools
uv run pytest
cargo test --workspace
uv sync --extra dev --reinstall-package logler   # after a change to the Rust code
```

## License

MIT. See [LICENSE](LICENSE).
