"""A format in .logler/formats.yaml parses the files it names, through every door.

The same file must read the same whichever command or API call it comes through. The files
below are documented line by line; every expected value is one the built-in detection would
get wrong (the levels of robot_1.log, the message "valve stuck", the field "station").

Fixture, in a directory with ``.logler/formats.yaml``:

    plc_1.log    3 lines; line 1-2 read by the ``plc`` format, line 3 does not match it
    robot_1.log  2 lines, all read by the ``robot`` format (no timestamp, level word in ``lvl``)
    app.log      1 line, no format names it
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest
from click.testing import CliRunner

from logler.cache import clear_cache
from logler.cli import main
from logler.config import format_for_file
from logler.investigate import Investigator, get_metadata, search
from logler.parser import LogParser
from logler.terminal import TerminalViewer

PLC_RAW_3 = "2024-01-15 10:00:02 INFO a plain line in a plc file"
APP_RAW = "2024-01-15 10:00:03 INFO plain line"

FORMATS_YAML = textwrap.dedent(
    r"""
    formats:
      plc:
        regex: '^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\|(?P<level>\w+)\|(?P<station>[\w-]+)\|(?P<message>.*)$'
        file_patterns: ["plc_*.log"]
      robot:
        regex: '^(?P<lvl>\w+);(?P<axis>\d+);(?P<msg>.*)$'
        file_patterns: ["robot_*.log"]
    """
)

FILE_TEXT = {
    "plc_1.log": (
        "2024-01-15 10:00:00|warn|ST-07|pressure low\n"
        "2024-01-15 10:00:01|error|ST-07|valve stuck\n" + PLC_RAW_3 + "\n"
    ),
    "robot_1.log": "error;3;overtravel\ninfo;1;homed\n",
    "app.log": APP_RAW + "\n",
}

# file -> [(line, level, message, fields, has_timestamp)]
GROUND: Dict[str, List[Tuple[int, str, str, Dict[str, str], bool]]] = {
    "plc_1.log": [
        (1, "WARN", "pressure low", {"station": "ST-07"}, True),
        (2, "ERROR", "valve stuck", {"station": "ST-07"}, True),
        (3, "INFO", PLC_RAW_3, {}, True),
    ],
    "robot_1.log": [
        (1, "ERROR", "overtravel", {"axis": "3"}, False),
        (2, "INFO", "homed", {"axis": "1"}, False),
    ],
    "app.log": [(1, "INFO", APP_RAW, {}, True)],
}

FILE_SETS = {
    "plc": ["plc_1.log"],
    "robot": ["robot_1.log"],
    "app": ["app.log"],
    "all": ["plc_1.log", "robot_1.log", "app.log"],
    "all_reversed": ["app.log", "robot_1.log", "plc_1.log"],
}


@pytest.fixture()
def logdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The three files and the formats file, with the working directory set to them."""
    (tmp_path / ".logler").mkdir()
    (tmp_path / ".logler" / "formats.yaml").write_text(FORMATS_YAML)
    for name, text in FILE_TEXT.items():
        (tmp_path / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    clear_cache()
    return tmp_path


def _expected_entries(files: List[str]) -> List[Tuple[str, int, str, str]]:
    return sorted(
        (name, line, level, message)
        for name in files
        for (line, level, message, _fields, _ts) in GROUND[name]
    )


def _expected_fields(files: List[str]) -> Dict[Tuple[str, int], Dict[str, str]]:
    return {(name, row[0]): row[3] for name in files for row in GROUND[name]}


def _expected_levels(files: List[str], timestamped_only: bool = False) -> Dict[str, int]:
    return dict(
        Counter(row[1] for name in files for row in GROUND[name] if row[4] or not timestamped_only)
    )


def _llm(*args: str) -> Any:
    result = CliRunner().invoke(main, ["llm", *args])
    assert result.exit_code in (0, 1), result.output  # 1 is "no results"
    return result


def _json_docs(text: str) -> List[Any]:
    """Every JSON document in a text, one after the other."""
    decoder = json.JSONDecoder()
    docs, pos = [], 0
    while pos < len(text):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        doc, pos = decoder.raw_decode(text, pos)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
# Doors that give entries: (file, line, level, message) and maybe the fields
# ---------------------------------------------------------------------------

Observed = Tuple[List[Tuple[str, int, str, str]], Optional[Dict[Tuple[str, int], Dict[str, str]]]]


def _entries_from_search_results(results: List[Dict[str, Any]], nested: bool) -> Observed:
    rows, fields = [], {}
    for item in results:
        e = item["entry"] if nested else item
        key = (os.path.basename(e["file"]), e["line_number"])
        rows.append((key[0], key[1], e["level"], e["message"]))
        if "fields" in e:
            fields[key] = e["fields"]
    return sorted(rows), (fields or None)


def door_search_function(files: List[str]) -> Observed:
    return _entries_from_search_results(search(files, limit=100)["results"], True)


def door_investigator(files: List[str]) -> Observed:
    inv = Investigator()
    inv.load_files(files)
    return _entries_from_search_results(inv.search(limit=100)["results"], True)


def door_llm_search(files: List[str]) -> Observed:
    out = json.loads(_llm("search", *files).output)
    return _entries_from_search_results(out["results"], False)


def door_emit(files: List[str]) -> Observed:
    lines = _llm("emit", *files).output.strip().splitlines()
    return _entries_from_search_results([json.loads(line) for line in lines], False)


def door_viewer(files: List[str]) -> Observed:
    rows: List[Tuple[str, int, str, str]] = []
    fields: Dict[Tuple[str, int], Dict[str, str]] = {}
    for name in files:
        viewer = TerminalViewer(use_colors=False)
        viewer.console.width = 400
        with viewer.console.capture() as capture:
            asyncio.run(viewer.view_file(name))
        current: Optional[Tuple[str, int]] = None
        for text in capture.get().splitlines():
            parts = text.split()
            if parts and parts[0].isdigit() and "UNKNOWN" not in parts[:4]:
                # "<line> [<date> <time>] <LEVEL> <message>"
                at = 3 if parts[1][:2] == "20" else 1
                level = parts[at]
                message = text.split(level, 1)[1].strip()
                current = (name, int(parts[0]))
                rows.append((name, current[1], level, message))
                fields[current] = {}
            elif current and text.startswith("    ") and ": " in text:
                key, value = text.strip().split(": ", 1)
                fields[current][key] = value
    return sorted(rows), fields


ENTRY_DOORS: Dict[str, Callable[[List[str]], Observed]] = {
    "search()": door_search_function,
    "Investigator.load_files": door_investigator,
    "llm search": door_llm_search,
    "llm emit": door_emit,
    "viewer": door_viewer,
}


@pytest.mark.parametrize("set_name", list(FILE_SETS))
@pytest.mark.parametrize("door", list(ENTRY_DOORS))
def test_entry_doors_read_each_file_with_its_format(logdir: Path, door: str, set_name: str) -> None:
    files = FILE_SETS[set_name]
    rows, fields = ENTRY_DOORS[door](files)

    assert rows == _expected_entries(files)
    if fields is not None:
        assert fields == _expected_fields(files)


# ---------------------------------------------------------------------------
# Doors that give counts
# ---------------------------------------------------------------------------


def door_get_metadata(files: List[str]) -> Dict[str, int]:
    total: Counter = Counter()
    for item in get_metadata(files):
        total.update(item["log_levels"])
    return dict(total)


def door_stats(files: List[str]) -> Dict[str, int]:
    result = CliRunner().invoke(main, ["stats", *files, "--json"])
    assert result.exit_code == 0, result.output
    total: Counter = Counter()
    for doc in _json_docs(result.output):
        total.update(doc["by_level"])
    return dict(total)


def door_schema(files: List[str]) -> Dict[str, int]:
    out = json.loads(_llm("schema", *files).output)
    # schema gives the level values and the format shares, not counts
    return {
        "levels": sorted(out["schema"]["level"]["values"]),
        "formats": out["detected_formats"],
    }


def door_summarize(files: List[str]) -> Dict[str, int]:
    return json.loads(_llm("summarize", *files).output)["stats"]["by_level"]


def door_sql(files: List[str]) -> Dict[str, int]:
    args: List[str] = []
    for name in files:
        args += ["--files", name]
    out = json.loads(
        _llm("sql", "SELECT level, count(*) AS c FROM logs GROUP BY level", *args).output
    )
    return {row["level"]: row["c"] for row in out["results"]}


def door_diff(files: List[str]) -> Dict[str, int]:
    out = json.loads(
        _llm(
            "diff",
            "--before-start",
            "2024-01-15T09:00:00Z",
            "--before-end",
            "2024-01-15T09:59:00Z",
            "--after-start",
            "2024-01-15T10:00:00Z",
            "--after-end",
            "2024-01-15T10:00:03Z",
            *files,
        ).output
    )
    return out["comparison"]["after"]["by_level"]


COUNT_DOORS: Dict[str, Callable[[List[str]], Any]] = {
    "get_metadata": door_get_metadata,
    "stats": door_stats,
    "summarize": door_summarize,
    "sql": door_sql,
}


@pytest.mark.parametrize("set_name", list(FILE_SETS))
@pytest.mark.parametrize("door", list(COUNT_DOORS))
def test_count_doors_read_each_file_with_its_format(logdir: Path, door: str, set_name: str) -> None:
    files = FILE_SETS[set_name]
    assert COUNT_DOORS[door](files) == _expected_levels(files)


def test_diff_counts_the_levels_a_format_read(logdir: Path) -> None:
    """The fixture's robot lines carry no timestamp and its plc lines read the same either way,
    so diff gets a file of its own: the level is the last word, which only a format reads."""
    (logdir / ".logler" / "formats.yaml").write_text(
        r"""
formats:
  tick:
    regex: '^(?P<timestamp>\S+ \S+) :: (?P<message>.*) :: (?P<level>\w+)$'
    file_patterns: ["tick_*.log"]
"""
    )
    (logdir / "tick_1.log").write_text(
        "2024-01-15 10:00:01 :: disk full :: err\n2024-01-15 10:00:02 :: all well :: info\n"
    )

    assert door_diff(["tick_1.log"]) == {"ERROR": 1, "INFO": 1}


@pytest.mark.parametrize(
    "set_name,levels,formats",
    [
        ("plc", ["ERROR", "INFO", "WARN"], {"Custom": 0.667, "PlainText": 0.333}),
        ("robot", ["ERROR", "INFO"], {"Custom": 1.0}),
        ("app", ["INFO"], {"PlainText": 1.0}),
        ("all", ["ERROR", "INFO", "WARN"], {"Custom": 0.667, "PlainText": 0.333}),
        ("all_reversed", ["ERROR", "INFO", "WARN"], {"Custom": 0.667, "PlainText": 0.333}),
    ],
)
def test_schema_reports_the_formats_the_files_read_with(
    logdir: Path, set_name: str, levels: List[str], formats: Dict[str, float]
) -> None:
    observed = door_schema(FILE_SETS[set_name])
    assert observed["levels"] == levels
    assert observed["formats"] == formats


@pytest.mark.parametrize(
    "set_name,matches",
    [("plc", 1), ("robot", 0), ("app", 0), ("all", 1), ("all_reversed", 1)],
)
def test_verify_pattern_matches_the_message_the_format_read(
    logdir: Path, set_name: str, matches: int
) -> None:
    """``^valve stuck$`` matches the message of plc line 2 and no raw line."""
    out = json.loads(
        _llm("verify-pattern", *FILE_SETS[set_name], "--pattern", "^valve stuck$").output
    )
    assert out["statistics"]["total_matches"] == matches


def test_get_metadata_lists_the_fields_each_format_captured(logdir: Path) -> None:
    fields = {
        os.path.basename(item["path"]): item["available_fields"]
        for item in get_metadata(FILE_SETS["all"])
    }
    assert fields == {"plc_1.log": ["station"], "robot_1.log": ["axis"], "app.log": []}


def test_another_cached_function_reads_the_format_too(logdir: Path) -> None:
    from logler.investigate import extract_ids

    # a thread id captured by a group named in the key lists reaches extract_ids
    (logdir / ".logler" / "formats.yaml").write_text(
        r"""
formats:
  plc:
    regex: '^(?P<thread>[\w-]+)\|(?P<message>.*)$'
    file_patterns: ["plc_*.log"]
"""
    )
    (logdir / "plc_1.log").write_text("T-9|hello\nT-9|again\n")
    ids = extract_ids(["plc_1.log"])["thread_ids"]
    assert [(item["id"], item["count"]) for item in ids] == [("T-9", 2)]


# ---------------------------------------------------------------------------
# Hostile inputs
# ---------------------------------------------------------------------------


def _robot_levels(path: str) -> Dict[str, int]:
    return dict(Counter(item["entry"]["level"] for item in search([path], limit=10)["results"]))


def test_formats_file_two_directories_above_the_log(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".logler").mkdir()
    (tmp_path / ".logler" / "formats.yaml").write_text(FORMATS_YAML)
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "robot_1.log").write_text(FILE_TEXT["robot_1.log"])
    monkeypatch.chdir(tmp_path)
    clear_cache()

    assert _robot_levels("a/b/robot_1.log") == {"ERROR": 1, "INFO": 1}
    clear_cache()
    assert _robot_levels(str(deep / "robot_1.log")) == {"ERROR": 1, "INFO": 1}
    monkeypatch.chdir(deep)
    clear_cache()
    assert _robot_levels("robot_1.log") == {"ERROR": 1, "INFO": 1}


def test_first_format_in_the_file_wins_when_two_patterns_match(
    logdir: Path,
) -> None:
    (logdir / ".logler" / "formats.yaml").write_text(
        r"""
formats:
  first:
    regex: '^(?P<lvl>\w+);(?P<axis>\d+);(?P<msg>.*)$'
    file_patterns: ["robot_*.log"]
  second:
    regex: '^(?P<lvl>\w+);(?P<other>\d+);(?P<msg>.*)$'
    file_patterns: ["*.log"]
"""
    )
    rows = search(["robot_1.log"], limit=10)["results"]
    assert sorted(item["entry"]["fields"].get("axis") for item in rows) == ["1", "3"]
    assert [item["entry"]["fields"].get("other") for item in rows] == [None, None]


LOOKAHEAD_YAML = r"""
formats:
  robot:
    regex: '^(?=e)(?P<lvl>\w+);(?P<axis>\d+);(?P<msg>.*)$'
    file_patterns: ["robot_*.log"]
"""

BUILTIN_ROBOT = {("UNKNOWN", "error;3;overtravel"), ("UNKNOWN", "info;1;homed")}
BUILTIN_ROBOT_EMIT = {("UNKNOWN", "error;3;overtravel"), ("UNKNOWN", "info;1;homed")}


def test_format_rust_cannot_compile_loads_with_builtin_detection(logdir: Path) -> None:
    (logdir / ".logler" / "formats.yaml").write_text(LOOKAHEAD_YAML)

    assert format_for_file("robot_1.log") is None
    found = search(["robot_1.log"], limit=10)["results"]
    assert {(i["entry"]["level"], i["entry"]["message"]) for i in found} == BUILTIN_ROBOT
    emitted = [json.loads(x) for x in _llm("emit", "robot_1.log").output.strip().splitlines()]
    assert {(e["level"], e["message"]) for e in emitted} == BUILTIN_ROBOT_EMIT
    assert LogParser.for_file("robot_1.log").parse_line(1, "error;3;x").format == "PlainText"


def test_broken_yaml_loads_with_builtin_detection(logdir: Path) -> None:
    (logdir / ".logler" / "formats.yaml").write_text("not: valid: yaml: {{{")

    assert format_for_file("robot_1.log") is None
    found = search(["robot_1.log"], limit=10)["results"]
    assert {(i["entry"]["level"], i["entry"]["message"]) for i in found} == BUILTIN_ROBOT
    emitted = [json.loads(x) for x in _llm("emit", "robot_1.log").output.strip().splitlines()]
    assert {(e["level"], e["message"]) for e in emitted} == BUILTIN_ROBOT_EMIT


def test_explicit_custom_regex_rust_cannot_compile_is_an_error(logdir: Path) -> None:
    with pytest.raises(ValueError):
        search(["robot_1.log"], custom_regex="(?=x)")


def _bump(path: Path, seconds: int = 10) -> None:
    stat = path.stat()
    os.utime(path, (stat.st_atime + seconds, stat.st_mtime + seconds))


def test_rewriting_formats_yaml_gives_the_next_search_the_new_reading(logdir: Path) -> None:
    assert _robot_levels("robot_1.log") == {"ERROR": 1, "INFO": 1}

    config = logdir / ".logler" / "formats.yaml"
    config.write_text(FORMATS_YAML.replace("robot_*.log", "nothing_*.log"))
    _bump(config)

    assert _robot_levels("robot_1.log") == {"UNKNOWN": 2}


def test_deleting_formats_yaml_gives_the_next_search_the_new_reading(logdir: Path) -> None:
    assert _robot_levels("robot_1.log") == {"ERROR": 1, "INFO": 1}

    (logdir / ".logler" / "formats.yaml").unlink()

    assert _robot_levels("robot_1.log") == {"UNKNOWN": 2}


def test_creating_formats_yaml_gives_the_next_search_the_new_reading(logdir: Path) -> None:
    config = logdir / ".logler" / "formats.yaml"
    config.unlink()
    assert _robot_levels("robot_1.log") == {"UNKNOWN": 2}

    config.write_text(FORMATS_YAML)
    _bump(config)

    assert _robot_levels("robot_1.log") == {"ERROR": 1, "INFO": 1}


def test_a_closer_formats_yaml_created_later_wins(logdir: Path) -> None:
    sub = logdir / "sub"
    sub.mkdir()
    (sub / "robot_1.log").write_text(FILE_TEXT["robot_1.log"])
    assert _robot_levels("sub/robot_1.log") == {"ERROR": 1, "INFO": 1}

    (sub / ".logler").mkdir()
    (sub / ".logler" / "formats.yaml").write_text(
        FORMATS_YAML.replace("robot_*.log", "nothing_*.log")
    )

    assert _robot_levels("sub/robot_1.log") == {"UNKNOWN": 2}


def test_rewriting_the_formats_yaml_behind_one_of_two_links_gives_the_new_reading(
    tmp_path: Path,
) -> None:
    """Two links in one directory, each to a log under its own formats file."""
    links = tmp_path / "links"
    links.mkdir()
    for tree in ("a", "b"):
        (tmp_path / tree / ".logler").mkdir(parents=True)
        (tmp_path / tree / ".logler" / "formats.yaml").write_text(FORMATS_YAML)
        (tmp_path / tree / f"robot_{tree}.log").write_text(FILE_TEXT["robot_1.log"])
        (links / f"robot_{tree}.log").symlink_to(tmp_path / tree / f"robot_{tree}.log")
    clear_cache()
    files = [str(links / "robot_a.log"), str(links / "robot_b.log")]

    def levels() -> List[Tuple[str, str]]:
        found = search(files, limit=10)["results"]
        return sorted((os.path.basename(i["entry"]["file"]), i["entry"]["level"]) for i in found)

    assert levels() == [
        ("robot_a.log", "ERROR"),
        ("robot_a.log", "INFO"),
        ("robot_b.log", "ERROR"),
        ("robot_b.log", "INFO"),
    ]

    config = tmp_path / "b" / ".logler" / "formats.yaml"
    config.write_text(FORMATS_YAML.replace("robot_*.log", "nothing_*.log"))
    _bump(config)

    assert levels() == [
        ("robot_a.log", "ERROR"),
        ("robot_a.log", "INFO"),
        ("robot_b.log", "UNKNOWN"),
        ("robot_b.log", "UNKNOWN"),
    ]


def test_a_format_without_file_patterns_is_never_applied(logdir: Path) -> None:
    (logdir / ".logler" / "formats.yaml").write_text(
        r"""
formats:
  robot:
    regex: '^(?P<lvl>\w+);(?P<axis>\d+);(?P<msg>.*)$'
"""
    )
    assert format_for_file("robot_1.log") is None
    assert _robot_levels("robot_1.log") == {"UNKNOWN": 2}


def test_db_source_is_read_as_before_with_a_formats_file_around(logdir: Path) -> None:
    db = logdir / "jobs.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE qler_jobs (_id INTEGER PRIMARY KEY AUTOINCREMENT, data JSON NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'pending', priority INTEGER NOT NULL DEFAULT 0, "
        "attempt_count INTEGER NOT NULL DEFAULT 0)"
    )
    for task, status in (("send_email", "completed"), ("process_image", "failed")):
        data = json.dumps({"task": task, "queue_name": "q", "created_at": 1705312800})
        conn.execute("INSERT INTO qler_jobs (data, status) VALUES (?, ?)", (data, status))
    conn.commit()
    conn.close()
    (logdir / ".logler" / "formats.yaml").write_text(
        FORMATS_YAML.replace("plc_*.log", "*.jsonl").replace("robot_*.log", "*")
    )

    out = json.loads(_llm("search", "--db", str(db)).output)

    assert out["summary"]["total_matches"] == 2
    assert sorted(r["level"] for r in out["results"]) == ["ERROR", "INFO"]
