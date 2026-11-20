"""One parser: the Python LogParser is the Rust parser, so every command agrees with search."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

TRACKED_LOGS = sorted(
    p
    for d in ("examples/logs", "tests/fixtures")
    for p in (ROOT / d).rglob("*")
    if p.suffix in (".log", ".jsonl")
)

EXPECTED_FILES = 16
EXPECTED_LINES = 4287

FIELDS = (
    "level",
    "timestamp",
    "message",
    "thread_id",
    "correlation_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "service_name",
    "format",
    "fields",
)


def _non_empty_lines(path: Path) -> list[tuple[int, str]]:
    """(file line number, line) for every non-empty line."""
    with open(path, errors="replace") as f:
        return [(n, line.rstrip()) for n, line in enumerate(f, start=1) if line.rstrip()]


def _rust_entries(path: Path) -> list[dict]:
    import logler_rs

    inv = logler_rs.PyInvestigator()
    inv.load_files([str(path)])
    page = json.loads(inv.get_entries_page(0, 1_000_000))
    return page["entries"]


def _expected(entry: dict) -> dict:
    ts = entry["timestamp"]
    level = entry["level"]
    return {
        "level": level.upper() if level else "UNKNOWN",
        "timestamp": (datetime.fromisoformat(ts).astimezone(UTC) if ts else None),
        "message": entry["message"],
        "thread_id": entry["thread_id"],
        "correlation_id": entry["correlation_id"],
        "trace_id": entry["trace_id"],
        "span_id": entry["span_id"],
        "parent_span_id": entry["parent_span_id"],
        "service_name": entry["service_name"],
        "format": entry["format"],
        "fields": entry["fields"],
    }


def test_tracked_logs_are_all_there():
    assert len(TRACKED_LOGS) == EXPECTED_FILES
    assert sum(len(_non_empty_lines(p)) for p in TRACKED_LOGS) == EXPECTED_LINES


def test_python_parser_equals_rust_index_on_every_tracked_line():
    from logler.parser import LogParser

    parser = LogParser()
    total = 0
    mismatches = []
    for path in TRACKED_LOGS:
        lines = _non_empty_lines(path)
        by_line = {e["line_number"]: e for e in _rust_entries(path)}
        assert sorted(by_line) == [n for n, _ in lines], path
        for n, line in lines:
            rust = by_line[n]
            got = parser.parse_line(n, line)
            want = _expected(rust)
            for name in FIELDS:
                if getattr(got, name) != want[name]:
                    mismatches.append((path.name, n, name, getattr(got, name), want[name]))
            total += 1
    assert total == EXPECTED_LINES
    assert mismatches == []


# Per-level counts of tests/fixtures/real_apache_clf.log, computed from the Rust entries.
APACHE_COUNTS = {"INFO": 493, "WARN": 7}


def test_summarize_counts_apache_clf_like_the_rust_index():
    path = ROOT / "tests" / "fixtures" / "real_apache_clf.log"
    rust_counts: dict[str, int] = {}
    for entry in _rust_entries(path):
        level = entry["level"].upper()
        rust_counts[level] = rust_counts.get(level, 0) + 1
    assert rust_counts == APACHE_COUNTS

    result = subprocess.run(
        [sys.executable, "-m", "logler.cli", "llm", "summarize", str(path)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["stats"]["by_level"] == APACHE_COUNTS


def _llm(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "logler.cli", "llm", *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )


def _emit_lines(*args: str) -> list[int]:
    result = _llm("emit", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line)["line_number"] for line in result.stdout.splitlines()]


def _search_lines(*args: str) -> list[int]:
    result = _llm("search", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    return sorted(entry["line_number"] for entry in json.loads(result.stdout)["results"])


@pytest.fixture
def four_levels(tmp_path) -> str:
    """Four lines an hour apart: 1 INFO 09:00, 2 ERROR 11:00, 3 `err` 12:00, 4 CRIT 13:00."""
    path = tmp_path / "levels.log"
    path.write_text(
        "2024-01-15 09:00:00 INFO early\n"
        "2024-01-15 11:00:00 ERROR late\n"
        "2024-01-15 12:00:00 err tail\n"
        "2024-01-15 13:00:00 CRIT down\n"
    )
    return str(path)


@pytest.mark.parametrize("lines_of", [_emit_lines, _search_lines])
@pytest.mark.parametrize(
    "word,expected",
    [
        ("ERROR", [2, 3]),
        ("err", [2, 3]),
        ("Info", [1]),
        ("information", [1]),
        ("crit", [4]),
        ("critical", [4]),
        ("FATAL", [4]),
        ("err,crit", [2, 3, 4]),
    ],
)
def test_a_level_can_be_asked_for_by_any_word_the_parser_reads(
    four_levels, lines_of, word, expected
):
    assert lines_of(four_levels, "--level", word) == expected


@pytest.mark.parametrize("command", ["emit", "search"])
def test_a_word_that_names_no_level_is_refused(four_levels, command):
    result = _llm(command, four_levels, "--level", "loud")
    assert result.returncode != 0
    assert "Unknown log level: loud" in result.stdout + result.stderr


@pytest.mark.parametrize("lines_of", [_emit_lines, _search_lines])
@pytest.mark.parametrize(
    "after,expected",
    [
        ("2024-01-15T10:00:00", [2, 3, 4]),  # no zone: UTC, as a log timestamp without one
        ("2024-01-15T10:00:00Z", [2, 3, 4]),
        ("2024-01-15T21:30:00+09:00", [4]),
    ],
)
def test_after_takes_a_time_with_or_without_a_zone(four_levels, lines_of, after, expected):
    assert lines_of(four_levels, "--after", after) == expected


def test_epoch_milliseconds_are_the_same_instant_in_every_command(tmp_path):
    path = tmp_path / "pino.jsonl"
    path.write_text('{"time":1705312800123,"level":"info","msg":"listening"}\n')
    instant = datetime(2024, 1, 15, 10, 0, 0, 123000, tzinfo=UTC)

    from logler.parser import LogParser

    entry = LogParser().parse_line(1, path.read_text().rstrip())
    assert entry.timestamp == instant
    assert entry.level == "INFO"

    result = _llm("search", str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    [found] = json.loads(result.stdout)["results"]
    assert datetime.fromisoformat(found["timestamp"]) == instant

    result = _llm("summarize", str(path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["stats"]["by_level"] == {"INFO": 1}


@pytest.mark.parametrize(
    "written",
    ["0000-06-01T00:00:00Z", "9999-12-31T23:59:59-01:00"],
)
def test_a_time_python_cannot_hold_leaves_the_entry_without_one(written):
    from logler.parser import LogParser

    entry = LogParser().parse_line(1, json.dumps({"timestamp": written, "msg": "odd year"}))
    assert entry.timestamp is None
    assert entry.message == "odd year"
    assert entry.format == "Json"


def test_a_leap_second_is_the_last_second_of_its_minute():
    from logler.parser import LogParser

    entry = LogParser().parse_line(1, "2016-12-31T23:59:60Z INFO leap")
    assert entry.timestamp == datetime(2016, 12, 31, 23, 59, 59, tzinfo=UTC)


def test_log_parser_without_extension_raises_runtime_error(monkeypatch):
    import logler.parser as parser_module

    monkeypatch.setattr(parser_module, "logler_rs", None)
    with pytest.raises(RuntimeError, match="Rust backend not available"):
        parser_module.LogParser()
