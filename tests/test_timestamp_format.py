"""A format's ``timestamp_format`` reads its timestamp group, in Python's strptime words.

Only a file whose format has the field is read with it; every other file reads as before. The
words, and how each is read, are listed in docs/CONFIGURATION.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

import logler_rs
from logler.cache import clear_cache
from logler.cli import main
from logler.config import FormatConfig, FormatFileError, load_usable_config
from logler.investigate import search
from logler.parser import LogParser

DAY_FIRST = "%d.%m.%Y %H:%M:%S"
MONTH_FIRST = "%m/%d/%Y %H:%M:%S"
REGEX = r"^(?P<timestamp>\S+ \S+) (?P<level>\w+) (?P<message>.*)$"


def _formats(*formats: tuple[str, str, str | None]) -> str:
    """A formats.yaml: one (name, file pattern, timestamp_format) per format, one regex."""
    lines = ["formats:"]
    for name, pattern, timestamp_format in formats:
        lines += [f"  {name}:", f"    regex: '{REGEX}'"]
        if timestamp_format is not None:
            lines.append(f'    timestamp_format: "{timestamp_format}"')
        lines.append(f'    file_patterns: ["{pattern}"]')
    return "\n".join(lines) + "\n"


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
    # a new (mtime, size) for every rewrite, however fast the test runs
    stat = config.stat()
    os.utime(config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    return config


def _times(files: list[str]) -> dict[tuple[str, int], str | None]:
    """(file, line) -> the timestamp search gives, for every entry of the files."""
    results = search(files, limit=100)["results"]
    return {
        (os.path.basename(r["entry"]["file"]), r["entry"]["line_number"]): r["entry"]["timestamp"]
        for r in results
    }


def test_the_format_reads_its_timestamp_group(logdir: Path) -> None:
    _write_formats(logdir, _formats(("plc", "plc_*.log", DAY_FIRST)))
    (logdir / "plc_1.log").write_text("31.12.2024 23:59:58 INFO year end\n")

    assert _times(["plc_1.log"]) == {("plc_1.log", 1): "2024-12-31T23:59:58Z"}
    entry = LogParser.for_file("plc_1.log").parse_entry(1, "31.12.2024 23:59:58 INFO year end")
    assert entry["timestamp"] == "2024-12-31T23:59:58Z"
    assert entry["message"] == "year end"


def test_a_timestamp_the_format_does_not_fit_is_read_in_the_known_shapes(logdir: Path) -> None:
    _write_formats(logdir, _formats(("plc", "plc_*.log", DAY_FIRST)))
    (logdir / "plc_1.log").write_text(
        "31.12.2024 23:59:58 INFO by the format\n"
        "2024-01-15 10:00:00.5 INFO a known shape\n"
        "15-01-2024 10:00:01 INFO the day-first shape of a custom group\n"
        "31.02.2024 10:00:00 INFO no such day\n"
        "31.12.2024 23:59:58,1 INFO more than the format\n"
    )

    assert _times(["plc_1.log"]) == {
        ("plc_1.log", 1): "2024-12-31T23:59:58Z",
        ("plc_1.log", 2): "2024-01-15T10:00:00.500Z",
        ("plc_1.log", 3): "2024-01-15T10:00:01Z",
        ("plc_1.log", 4): None,
        ("plc_1.log", 5): None,
    }


def test_two_formats_with_one_regex_and_two_timestamp_formats_keep_apart(logdir: Path) -> None:
    _write_formats(
        logdir,
        _formats(
            ("eu", "eu_*.log", DAY_FIRST),
            ("us", "us_*.log", MONTH_FIRST),
            ("plain", "plain_*.log", None),
        ),
    )
    (logdir / "eu_1.log").write_text("02.01.2024 10:00:00 INFO second of January\n")
    (logdir / "us_1.log").write_text("02/01/2024 10:00:00 INFO first of February\n")
    (logdir / "plain_1.log").write_text("02.01.2024 10:00:00 INFO no timestamp_format\n")

    assert _times(["eu_1.log", "us_1.log", "plain_1.log"]) == {
        ("eu_1.log", 1): "2024-01-02T10:00:00Z",
        ("us_1.log", 1): "2024-02-01T10:00:00Z",
        ("plain_1.log", 1): None,
    }


def test_the_cache_keeps_a_file_read_with_and_without_the_field_apart(logdir: Path) -> None:
    (logdir / "plc_1.log").write_text("31.12.2024 23:59:58 INFO year end\n")

    _write_formats(logdir, _formats(("plc", "plc_*.log", DAY_FIRST)))
    assert _times(["plc_1.log"]) == {("plc_1.log", 1): "2024-12-31T23:59:58Z"}
    _write_formats(logdir, _formats(("plc", "plc_*.log", None)))
    assert _times(["plc_1.log"]) == {("plc_1.log", 1): None}
    _write_formats(logdir, _formats(("plc", "plc_*.log", DAY_FIRST)))
    assert _times(["plc_1.log"]) == {("plc_1.log", 1): "2024-12-31T23:59:58Z"}


def test_an_empty_timestamp_format_is_no_field(logdir: Path) -> None:
    assert FormatConfig(regex=REGEX, timestamp_format="").timestamp_format is None
    _write_formats(logdir, _formats(("plc", "plc_*.log", "")))
    (logdir / "plc_1.log").write_text("2024-01-15 10:00:00 INFO known shape\n")

    assert _times(["plc_1.log"]) == {("plc_1.log", 1): "2024-01-15T10:00:00Z"}


ZONE_NAME = (
    "%Z is not supported: a zone name is read differently from machine to machine; "
    "write the zone as an offset and read it with %z"
)
NO_DATE = (
    "a timestamp needs a date: the format has no year (%Y or %y), no month (%m, %b or %B) "
    "and no day (%d)"
)
# timestamp_format -> the reason the format file is refused
REFUSED = {
    "%Y-%m-%d %H:%M:%S %Z": ZONE_NAME,
    "%H:%M:%S": NO_DATE,
    "%a %d.%m.%Y": ("%a is read in the machine's language, which differs from machine to machine"),
    "%d.%m.%Y %": "the format ends in a lone %; write a literal % as %%",
}


@pytest.mark.parametrize("timestamp_format", list(REFUSED))
def test_a_word_that_is_not_read_refuses_the_file_naming_format_and_word(
    logdir: Path, timestamp_format: str
) -> None:
    config = _write_formats(
        logdir, _formats(("app", "app_*.log", None), ("plc", "plc_*.log", timestamp_format))
    )
    (logdir / "app_1.log").write_text("2024-01-15 10:00:00 INFO x\n")
    expected = (
        f"{config}: format 'plc': the timestamp_format {timestamp_format!r} cannot be used: "
        f"{REFUSED[timestamp_format]}"
    )

    with pytest.raises(FormatFileError) as raised:
        load_usable_config(config)
    assert str(raised.value) == expected
    # the verdict is for the whole file: a log another format names is stopped too
    with pytest.raises(FormatFileError) as raised:
        search(["app_1.log"], limit=10)
    assert str(raised.value) == expected

    result = CliRunner().invoke(main, ["llm", "search", "app_1.log"])
    assert result.exit_code == 2
    assert expected in result.output

    result = CliRunner().invoke(main, ["llm", "format", "validate", "--config-dir", str(logdir)])
    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "valid": False,
        "config_path": str(config),
        "issues": [f"Config load error: {expected}"],
    }


def test_the_engine_refuses_a_timestamp_format_without_a_custom_regex() -> None:
    with pytest.raises(ValueError) as raised:
        logler_rs.PyLineParser(timestamp_format=DAY_FIRST)
    assert str(raised.value) == (
        "a timestamp_format reads the timestamp group of a custom_regex; give both"
    )
    with pytest.raises(ValueError) as raised:
        LogParser(custom_regex=REGEX, timestamp_format="%Y-%m-%d %Z")
    assert str(raised.value) == ZONE_NAME


def test_an_explicit_parser_reads_with_the_timestamp_format() -> None:
    regex = r"^(?P<timestamp>\S+) (?P<level>\w+) (?P<message>.*)$"
    parser = LogParser(custom_regex=regex, timestamp_format="%d/%b/%Y:%H:%M:%S%z")
    entry = parser.parse_entry(1, "10/oct/2024:13:55:36+09:00 WARN hot")
    assert entry["timestamp"] == "2024-10-10T04:55:36Z"
    assert entry["message"] == "hot"
