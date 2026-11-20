"""`llm format test` shows the time the engine reads, a `timestamp_format` that can never be used
stops the formats file, and `llm format validate` knows every name the engine reads as the
timestamp group.
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner

from logler.builtin_formats import get_builtin_formats
from logler.cache import clear_cache
from logler.cli import main
from logler.config import FormatFileError, load_usable_config, timestamp_group_names
from logler.investigate import search

PLC_REGEX = r"^(?P<timestamp>\S+ \S+) (?P<level>\w+) (?P<message>.*)$"
PLC_YAML = f"""
formats:
  plc:
    regex: '{PLC_REGEX}'
    timestamp_format: "%d.%m.%Y %H:%M:%S"
    file_patterns: ["plc_*.log"]
"""
PLC_LINES = (
    "31.12.2024 23:59:58 INFO year end\n"
    "01.01.2025 00:00:01 WARN new year\n"
    "2025-01-02 03:04:05 INFO known shape\n"
    "later INFO no time\n"
    "garbage\n"
)


@pytest.fixture()
def logdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".logler").mkdir()
    monkeypatch.chdir(tmp_path)
    clear_cache()
    yield tmp_path
    clear_cache()


def _write_formats(logdir: Path, text: str) -> Path:
    config = logdir / ".logler" / "formats.yaml"
    config.write_text(text)
    stat = config.stat()
    os.utime(config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    return config


def _run(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(main, ["llm", *args])
    return result.exit_code, json.loads(result.output)


def _times(output: dict) -> list:
    return [row.get("timestamp", "absent") for row in output["results"]]


def test_format_test_shows_the_time_the_engine_reads_with_the_named_format(logdir: Path) -> None:
    _write_formats(logdir, PLC_YAML)
    log = logdir / "plc_1.log"
    log.write_text(PLC_LINES)

    code, out = _run("format", "test", "-f", str(log), "--name", "plc")

    assert code == 0
    assert [row["matched"] for row in out["results"]] == [True, True, True, True, False]
    assert _times(out) == [
        "2024-12-31T23:59:58Z",
        "2025-01-01T00:00:01Z",
        "2025-01-02T03:04:05Z",
        None,
        "absent",
    ]
    assert [row.get("engine_matched") for row in out["results"]] == [True] * 4 + [None]
    assert out["timestamp_format"] == "%d.%m.%Y %H:%M:%S"
    assert out["matched_lines"] == 4
    assert out["matched_lines_with_timestamp"] == 3
    assert out["engine_unmatched_lines"] == 0
    # the keys the command printed before are still there, with their values
    assert out["format_source"] == "user_config"
    assert out["regex"] == PLC_REGEX
    assert out["named_groups"] == ["timestamp", "level", "message"]
    assert out["total_lines"] == 5
    assert out["match_rate_percent"] == 80.0
    assert out["results"][0]["groups"] == {
        "timestamp": "31.12.2024 23:59:58",
        "level": "INFO",
        "message": "year end",
    }


def test_format_test_with_a_regex_alone_reads_with_no_format(logdir: Path) -> None:
    log = logdir / "plc_1.log"
    log.write_text(PLC_LINES)

    code, out = _run("format", "test", "-f", str(log), "--regex", PLC_REGEX)

    assert code == 0
    assert _times(out) == [None, None, "2025-01-02T03:04:05Z", None, "absent"]
    assert out["timestamp_format"] is None
    assert out["matched_lines_with_timestamp"] == 1


def test_format_test_counts_every_line_when_limit_is_smaller_than_the_file(
    logdir: Path,
) -> None:
    _write_formats(logdir, PLC_YAML)
    log = logdir / "plc_1.log"
    log.write_text(PLC_LINES)

    code, out = _run("format", "test", "-f", str(log), "--name", "plc", "--limit", "1")

    assert code == 0
    assert len(out["results"]) == 1
    assert out["matched_lines"] == 4
    assert out["matched_lines_with_timestamp"] == 3


def test_format_test_says_a_line_python_matches_and_the_engine_does_not(logdir: Path) -> None:
    # Python reads `[[:alpha:]]` as a set and a bracket; the engine reads a letter class.
    log = logdir / "odd.log"
    log.write_text("a]\na\n")
    regex = r"^(?P<message>[[:alpha:]])$"

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        code, out = _run("format", "test", "-f", str(log), "--regex", regex)

    assert code == 0
    assert len(out["results"]) == 2
    first = out["results"][0]
    assert first["matched"] is True
    assert first["engine_matched"] is False
    assert first["timestamp"] is None
    assert out["matched_lines"] == 1
    assert out["engine_unmatched_lines"] == 1
    assert out["matched_lines_with_timestamp"] == 0


def test_format_test_reads_a_group_named_ts(logdir: Path) -> None:
    config = r"""
formats:
  plc:
    regex: '^(?P<ts>\S+ \S+) (?P<message>.*)$'
    timestamp_format: "%d.%m.%Y %H:%M:%S"
    file_patterns: ["plc_*.log"]
"""
    _write_formats(logdir, config)
    log = logdir / "plc_1.log"
    log.write_text("31.12.2024 23:59:58 year end\n")

    code, out = _run("format", "test", "-f", str(log), "--name", "plc")

    assert code == 0
    assert _times(out) == ["2024-12-31T23:59:58Z"]
    assert out["matched_lines_with_timestamp"] == 1


def test_format_test_says_when_the_format_fits_no_line(logdir: Path) -> None:
    _write_formats(logdir, PLC_YAML)
    log = logdir / "plc_1.log"
    log.write_text("yesterday 10:00 INFO a\ntoday 11:00 INFO b\n")

    code, out = _run("format", "test", "-f", str(log), "--name", "plc")

    assert code == 0
    assert _times(out) == [None, None]
    assert out["matched_lines"] == 2
    assert out["matched_lines_with_timestamp"] == 0


def test_format_test_reads_a_built_in_format_with_its_timestamp_format(logdir: Path) -> None:
    log = logdir / "access.log"
    log.write_text(
        '192.168.1.1 - admin [10/Oct/2024:13:55:36 -0700] "GET /a HTTP/1.1" 200 5 "-" "curl"\n'
    )

    code, out = _run("format", "test", "-f", str(log), "--name", "nginx_access")

    assert code == 0
    assert out["format_source"] == "builtin"
    assert out["timestamp_format"] == "%d/%b/%Y:%H:%M:%S %z"
    assert _times(out) == ["2024-10-10T20:55:36Z"]
    assert out["matched_lines_with_timestamp"] == 1


def test_format_test_finds_a_regex_anywhere_in_the_line_as_the_engine_does(logdir: Path) -> None:
    """A regex without `^` fits a line that has something before it, in every command."""
    _write_formats(
        logdir,
        r"""
formats:
  plc:
    regex: '(?P<timestamp>\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}) (?P<message>.*)'
    timestamp_format: "%d.%m.%Y %H:%M:%S"
    file_patterns: ["plc_*.log"]
""",
    )
    log = logdir / "plc_1.log"
    log.write_text("[plc] 31.12.2024 23:59:58 year end\nno time here\n")

    code, out = _run("format", "test", "-f", str(log), "--name", "plc")

    assert code == 0
    assert [row["matched"] for row in out["results"]] == [True, False]
    assert out["results"][0]["engine_matched"] is True
    assert out["results"][0]["groups"] == {
        "timestamp": "31.12.2024 23:59:58",
        "message": "year end",
    }
    assert _times(out) == ["2024-12-31T23:59:58Z", "absent"]
    assert out["matched_lines"] == 1
    assert out["matched_lines_with_timestamp"] == 1
    assert out["engine_unmatched_lines"] == 0
    # what the command shows is what a search of the file reads
    found = search([str(log)], limit=10)["results"]
    assert [row["entry"]["timestamp"] for row in found] == ["2024-12-31T23:59:58Z", None]


def test_format_test_takes_a_format_of_the_file_before_a_built_in_of_that_name(
    logdir: Path,
) -> None:
    """Every command reads a file with the formats file's format; so does the test."""
    regex = r"^(?P<timestamp>\S+ \S+) (?P<message>.*)$"
    _write_formats(
        logdir,
        f"""
formats:
  nginx_access:
    regex: '{regex}'
    timestamp_format: "%d.%m.%Y %H:%M:%S"
    file_patterns: ["access*.log"]
""",
    )
    log = logdir / "access.log"
    log.write_text("31.12.2024 23:59:58 year end\n")

    code, out = _run("format", "test", "-f", str(log), "--name", "nginx_access")

    assert code == 0
    assert out["format_source"] == "user_config"
    assert out["regex"] == regex
    assert out["timestamp_format"] == "%d.%m.%Y %H:%M:%S"
    assert _times(out) == ["2024-12-31T23:59:58Z"]


def test_format_test_refuses_a_regex_the_engine_cannot_compile(logdir: Path) -> None:
    log = logdir / "a.log"
    log.write_text("x\n")

    code, out = _run("format", "test", "-f", str(log), "--regex", r"^(?<=a)(?P<message>.*)$")

    assert code == 2
    assert sorted(out) == ["code", "error"]
    assert out["code"] == 2
    # the reason after the sentence is the regex library's own text
    assert out["error"].startswith(
        "The regex cannot be compiled by the Rust engine: regex parse error:"
    )
    assert out["error"].endswith(
        "look-around, including look-ahead and look-behind, is not supported"
    )


def test_format_test_reads_a_file_with_invalid_bytes(logdir: Path) -> None:
    log = logdir / "a.log"
    log.write_bytes(b"2025-01-02 03:04:05 INFO ok\n2025-01-02 03:04:06 INFO bad \xff\xfe\n")

    code, out = _run("format", "test", "-f", str(log), "--regex", PLC_REGEX)

    assert code == 0
    assert out["matched_lines"] == 2
    assert _times(out) == ["2025-01-02T03:04:05Z", "2025-01-02T03:04:06Z"]


NO_TIMESTAMP_GROUP_YAML = r"""
formats:
  quiet:
    regex: '^(?P<level>\w+) (?P<message>.*)$'
    timestamp_format: "%Y-%m-%d"
    file_patterns: ["quiet_*.log"]
"""
NO_TIMESTAMP_GROUP_REFUSAL = (
    "format 'quiet': the timestamp_format '%Y-%m-%d' cannot be used: the regex has no group "
    "the engine reads as a timestamp (its groups: level, message); name the group timestamp, "
    "time, ts or datetime"
)


def test_a_timestamp_format_without_a_timestamp_group_stops_every_door(logdir: Path) -> None:
    config = _write_formats(logdir, NO_TIMESTAMP_GROUP_YAML)
    (logdir / "quiet_1.log").write_text("INFO hello\n")
    (logdir / "app.log").write_text("2025-01-02 03:04:05 INFO x\n")
    expected = f"{config}: {NO_TIMESTAMP_GROUP_REFUSAL}"

    with pytest.raises(FormatFileError) as raised:
        load_usable_config(config)
    assert str(raised.value) == expected
    # the verdict is for the whole file: a log no format names is stopped too
    with pytest.raises(FormatFileError) as raised:
        search(["app.log"], limit=10)
    assert str(raised.value) == expected

    for args in (("search", "quiet_1.log"), ("emit", "app.log"), ("schema", "app.log")):
        result = CliRunner().invoke(main, ["llm", *args])
        assert result.exit_code == 2, result.output
        assert expected in result.output
    result = CliRunner().invoke(main, ["llm", "format", "validate", "--config-dir", str(logdir)])
    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "valid": False,
        "config_path": str(config),
        "issues": [f"Config load error: {expected}"],
    }


@pytest.mark.parametrize("name", ["timestamp", "time", "ts", "datetime"])
def test_a_timestamp_format_with_any_group_the_engine_reads_is_usable(
    logdir: Path, name: str
) -> None:
    config = _write_formats(
        logdir,
        f"""
formats:
  plc:
    regex: '^(?P<{name}>\\S+) (?P<message>.*)$'
    timestamp_format: "%Y-%m-%d"
""",
    )
    assert list(load_usable_config(config).formats) == ["plc"]


def test_a_format_without_the_field_needs_no_timestamp_group(logdir: Path) -> None:
    config = _write_formats(
        logdir,
        r"""
formats:
  quiet:
    regex: '^(?P<level>\w+) (?P<message>.*)$'
""",
    )
    assert list(load_usable_config(config).formats) == ["quiet"]


def test_the_engine_names_its_timestamp_keys() -> None:
    import logler_rs

    assert logler_rs.timestamp_keys() == ["timestamp", "time", "@timestamp", "ts", "datetime"]


def test_timestamp_group_names_are_the_names_the_engine_reads() -> None:
    names = ["level", "ts", "message", "time", "timestamp", "datetime", "clock", "when"]
    assert timestamp_group_names(names) == ["ts", "time", "timestamp", "datetime"]
    assert timestamp_group_names(["level", "message"]) == []
    assert timestamp_group_names([]) == []


def test_every_built_in_format_with_a_timestamp_format_has_a_group_the_engine_reads() -> None:
    import re

    with_field = {n: f for n, f in get_builtin_formats().items() if f.timestamp_format}
    assert sorted(with_field) == [
        "apache_access",
        "log4j",
        "logback",
        "nginx_access",
        "nginx_error",
        "postgresql",
        "python_logging",
    ]
    for name, fmt in with_field.items():
        groups = list(re.compile(fmt.regex).groupindex)
        assert timestamp_group_names(groups) == ["timestamp"], name


def _validate(logdir: Path, yaml_text: str) -> dict:
    _write_formats(logdir, yaml_text)
    code, out = _run("format", "validate", "--config-dir", str(logdir))
    assert code == 0
    return out


@pytest.mark.parametrize("name", ["timestamp", "time", "ts", "datetime"])
def test_validate_accepts_every_name_the_engine_reads_as_the_timestamp_group(
    logdir: Path, name: str
) -> None:
    out = _validate(
        logdir,
        f"""
formats:
  plc:
    regex: '^(?P<{name}>\\S+) (?P<message>.*)$'
    file_patterns: ["plc_*.log"]
""",
    )
    assert out["issues"] == []
    assert out["formats"]["plc"]["valid"] is True


def test_validate_flags_a_format_with_none_of_the_names(logdir: Path) -> None:
    out = _validate(
        logdir,
        r"""
formats:
  quiet:
    regex: '^(?P<level>\w+) (?P<message>.*)$'
    file_patterns: ["quiet_*.log"]
""",
    )
    assert out["issues"] == ["quiet: Missing recommended 'timestamp' group"]
    assert out["valid"] is False


def test_validate_regex_accepts_every_name_the_engine_reads(logdir: Path) -> None:
    code, out = _run("format", "validate", "--regex", r"^(?P<ts>\S+) (?P<message>.*)$")
    assert code == 0
    assert out["issues"] == ["Missing recommended groups: level. Present: ts, message"]
    assert out["named_groups"] == ["ts", "message"]
