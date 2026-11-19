# Changelog

All notable changes to logler will be documented in this file.

## [Unreleased]

Requires Python 3.12 or later. One compiled wheel per platform serves 3.12, 3.13, 3.14 and later (the extension is built against CPython's stable ABI).

### Upgrading from 1.3

- **A log file that cannot be read raises Python's own file errors.** `logler.investigate` functions raise `FileNotFoundError`, `PermissionError` or `IsADirectoryError`, with `.filename` set, where they raised a bare `RuntimeError`. Code that caught `RuntimeError` for a missing file no longer catches it.
- **Exit code 2 for a file a command cannot open, read or write.** The `llm` commands print `<file>: <reason>` and exit 2, where they printed "Internal error" and exited 3.
- **A line with no level is `UNKNOWN` everywhere**, and it is counted in every count by level. The Python API gave such a line the text `NONE`.
- **A `.logler/formats.yaml` or `.logler/correlations.yaml` that cannot be used stops the command.** Broken YAML, a schema error or a regex the engine cannot compile is exit 2 with the file and the problem (`FormatFileError`, a `ValueError`, from the API). Before, the file was skipped in silence and the log was read with the built-in detection.
- **`llm sql` and `Investigator.sql_query` query the same `logs` table.** Its `timestamp` column is a `TIMESTAMP` in both, and the columns come in one order. A query written for the command's old text timestamps may need a cast removed.
- **A line number the file has no entry for is the caller's error.** `get_context()` raises `ValueError` (`LineNotFoundError`) with `<file>: no entry at line N`, where it raised `RuntimeError`, or `OverflowError` for a negative line. `llm context` exits 2 with that text, where it exited 3.
- **A `representative` sample comes back in file order.** It was grouped by level.
- **`llm emit --pretty` is removed.**
- **`llm emit` exits 1 when nothing matches**, like every other `llm` command. It exited 0.
- **`LogReader.tail(0)` gives no lines.** It gave the whole file.
- **Fields of the pydantic models in `logler.models` follow the API's names:** `FileMetadata.lines` (was `line_count`) and `log_levels` (was `level_distribution`), `PatternMatch.occurrences` (was `count`), `SamplingResult.samples` (was `entries`). `SpanNode.entry_ids` holds the entries' ids as text.
- **Importing logler never starts a build.** Without the compiled extension the import warns once and says how to build it.
- The unused HTTP server, the second command-line program and the old web back end are deleted from the repository. None of them was in the published package.

### Fixed

- **One parser.** `logler stats`, the viewer and the `llm` commands `schema`, `summarize`, `sql`, `verify-pattern`, `emit` and `compare` parsed with a second parser that knew JSON and plain text only, so `summarize` and `search` could count the same file differently. Every command now parses with the Rust parser.
- **More level words and line shapes are read:** `NOTICE`, `SEVERE`, `EMERG`, `EMERGENCY`, `ALERT`, `PANIC`, `INFORMATION`, `ERR` and `CRIT`; a level in any letter case at the head of a line before a colon, after a leading timestamp, or alone in square brackets; a logfmt line that leads with a timestamp and a level keeps both.
- **A custom format applies in every command.** A format in `.logler/formats.yaml` reached only `Investigator.load_files()`. It now parses the files it names, file by file, in every command and API call, and its regex keeps every named group.
- **A log with a byte that is not UTF-8 can be read.** One Latin-1 byte failed every command that loads the file. Such a byte is now shown as U+FFFD. A byte-order mark at the start of a file is not part of line 1.
- **Line numbers and line text agree between commands.** Every command cuts a file into lines the same way: a line ends at a newline, a carriage return right before it is dropped, and nothing else is trimmed.
- **`--last 30m` works.** It ended every command that takes it with an internal error. It means from that long ago until now.
- **Time bounds are compared as times.** `llm summarize --after 2024-01-15T09:00:00Z` dropped every line of that day; `sample`, `correlate` and `diff` had related faults. A line with no time is inside any bounds, in every command.
- **A zone written after a space is read:** `2024-01-15 10:00:00 +0900 INFO started` was read nine hours off.
- **A bad level word is exit 2**, not an internal error, and a duration too long for the calendar is exit 2 with the flag named.
- **A time is written one way** by every `llm` command, with the digits of a second that the log has; `llm metrics --bucket` writes its bounds the same way.
- **A followed log shows every line once and whole**, under its line number in the file (`logler view --follow`, `LogReader.tail(follow=True)`).
- **`LogReader.tail(n)` reads only the end of the file.** It read the whole file; a very long single line took time that grew with the square of its length.
- **`logler llm sql "SELECT now()"` returns the time.** It failed for want of `pytz`, now a dependency.
- **`logler investigate`** prints an error it cannot recover from on stderr and exits 1, where its error handler raised.
- **`logler.__version__`** is the installed version; it said 1.1.2.
- **A logfmt value `nan` or `inf`** no longer ends a whole search with a panic.
- **Finding the numbers in a message is linear in its length.** A message holding one unbroken word of 50,000 characters took about a minute to scan.
- **A request tree counts each log line once.** A span under a parent with several log lines reported each of its own lines once per line of the parent, in `entry_count`, `error_count`, `level_counts` and `entry_ids`.
- **A `representative` sample has the size that was asked for.** `smart_sample(strategy="representative", sample_size=10)` could return 9 entries.
- **The same command on the same files prints the same output on every run.** `llm hierarchy`, `correlate`, `ids`, `schema`, `metrics` and `export` gave lists and map keys in another order from run to run, `schema` could show another hundred thread patterns, and `export` gave other span ids; `compare_threads`, `compare_time_periods`, `trace_request`, `detect_correlation_chains`, `diff_hierarchies` and `ThreadTracker` did the same with their lists. Files are now read in order of path, map keys are written sorted, ties in a ranked list break by name, nodes of a request tree that start together come in the order of their lines, and a list taken from log lines keeps the order of first appearance.
- **The typed dicts in `logler.types` describe what the API returns.** `LogEntryDict` lacked `id`, `raw`, `format` and `parent_span_id`; `SearchResultItem` lacked `relevance_score`; `SearchResult` lacked `search_time_ms`; `ContextResult` lacked `related_threads`; `BottleneckInfo` lacked `node_name`; `PatternInfo` lacked `pattern_type`; `ExtractedIds` said its lists hold text where they hold `{id, count, first_seen, last_seen}`; `SearchResult` and `PatternResult` listed keys that are never returned; `MetricsFieldStats` listed its numbers as flat keys where `extract_metrics` returns them under `stats`. Every class is now total, a key returned only under a condition is `NotRequired` and says when, and each class is checked against the real output, keys and value types, in the test suite. The docstrings that showed the old shapes are corrected.
- **The context lines of a search result carry the same level text as every other entry.** With `--context` or `context_lines`, the entries before and after a match read `Info`, and null for a line with no level, where the match itself read `INFO` and `UNKNOWN`.
- **`analyze_bottlenecks`** ranks its secondary bottlenecks by self-time, as it ranks the primary one.
- **A count of matches is the total.** `search(output_format="count", count_only=True)` said 0 where the same search without `count_only` said 20, and `total_matches` of the `count` and `summary` formats was the size of the page when `limit` was given. It is now every match of the query.
- **A summary and a count describe every match.** `log_levels`, `by_level`, `by_file`, `unique_messages`, `top_messages` and `time_range` of the `summary` and `count` formats were counted from the entries returned, at most `limit` or 10,000, while `total_matches` was every match, so `llm triage` gave a file of 12,000 lines whose last 2,000 are errors an error rate of 0. The engine now counts them over every match; `limit`, `tail` and `offset` choose only the `sample_entries`. A message's `first_seen` and `last_seen` and the `time_range` are compared as times: a whole second, written with no fraction, came after a time later in that second.
- **Reading a thread does not break the tracker.** `ThreadTracker.get_thread()` replaced the thread's set of correlation ids with a list, so the next line tracked for that thread failed. It returns a sorted copy.
- **`trace_request()` names the services of a JSON log.** It read only a `service` field of the entry, which a JSON line does not keep there.
- **`ProjectedSearchResult` describes `search(fields=[...])`**, whose entries hold only the asked keys; `LogEntryDict` still describes a whole entry.
- A failed SQL load no longer leaves its temporary CSV behind.

### Changed

- **A long search no longer blocks the other threads of a Python program:** the engine releases the GIL while it works.
- **Parsing is faster:** a JSON line is parsed once (about 30% less time a line), and a plain line costs less than it did in 1.3.
- The index reads each file once, in file order, with bounded memory per batch.

### Added

- **A node of a hierarchy names its service:** `service` is the `service_name` of the first of its entries that has one, or null.
- **Type information.** The package ships `py.typed` and a stub for the compiled extension, and is checked with mypy.

### Development

- ruff alone formats and lints (black is gone); `uv sync --extra dev` installs every development tool.
- Building from source needs Rust 1.89 or later. `Cargo.lock` is tracked.
- One benchmark report is published, in `docs/benchmarks/`.
