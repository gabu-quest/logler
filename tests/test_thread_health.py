"""analyze_thread_health: each thread's count of entries per level, and its total."""

import json
from pathlib import Path

import pytest

from logler.helpers import analyze_thread_health


def _write(path: Path, rows: list[dict]) -> str:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(path)


def _row(second: int, level: str | None, thread: str | None) -> dict:
    row: dict = {"timestamp": f"2024-01-15T10:00:{second:02d}Z", "message": f"m{second}"}
    if level is not None:
        row["level"] = level
    if thread is not None:
        row["thread_id"] = thread
    return row


@pytest.fixture
def mixed_file(tmp_path: Path) -> str:
    """Threads whose levels mix. Exact counts:

    - worker-a: INFO 3, ERROR 2, total 5
    - worker-b: WARN 1, ERROR 1, total 2
    - worker-c: UNKNOWN 2 (no level on either line), total 2
    - one ERROR line with no thread id: in no thread's counts
    """
    rows = [
        _row(0, "INFO", "worker-a"),
        _row(1, "ERROR", "worker-a"),
        _row(2, "INFO", "worker-a"),
        _row(3, "WARN", "worker-b"),
        _row(4, "ERROR", "worker-a"),
        _row(5, "INFO", "worker-a"),
        _row(6, "ERROR", "worker-b"),
        _row(7, None, "worker-c"),
        _row(8, None, "worker-c"),
        _row(9, "ERROR", None),
    ]
    return _write(tmp_path / "mixed.log", rows)


def test_each_thread_has_its_count_per_level_and_its_total(mixed_file):
    assert analyze_thread_health([mixed_file]) == {
        "worker-a": {"INFO": 3, "ERROR": 2, "total": 5},
        "worker-b": {"WARN": 1, "ERROR": 1, "total": 2},
        "worker-c": {"UNKNOWN": 2, "total": 2},
    }


def test_the_docstring_example_gives_a_rate(mixed_file):
    counts = analyze_thread_health([mixed_file])["worker-b"]
    assert counts.get("ERROR", 0) / counts.get("total", 1) * 100 == 50.0


def test_the_same_thread_in_two_files_adds_up(mixed_file, tmp_path):
    other = _write(
        tmp_path / "other.log",
        [_row(0, "ERROR", "worker-a"), _row(1, "FATAL", "worker-d")],
    )
    assert analyze_thread_health([mixed_file, other]) == {
        "worker-a": {"INFO": 3, "ERROR": 3, "total": 6},
        "worker-b": {"WARN": 1, "ERROR": 1, "total": 2},
        "worker-c": {"UNKNOWN": 2, "total": 2},
        "worker-d": {"FATAL": 1, "total": 1},
    }
    assert analyze_thread_health([other]) == {
        "worker-a": {"ERROR": 1, "total": 1},
        "worker-d": {"FATAL": 1, "total": 1},
    }


def test_an_empty_file_has_no_threads(tmp_path):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    assert analyze_thread_health([str(empty)]) == {}


def test_a_file_with_no_thread_ids_has_no_threads(tmp_path):
    path = _write(tmp_path / "nothread.log", [_row(0, "INFO", None), _row(1, "ERROR", None)])
    assert analyze_thread_health([path]) == {}


def test_no_files_give_no_threads():
    assert analyze_thread_health([]) == {}


def test_a_missing_file_raises_file_not_found(tmp_path):
    missing = str(tmp_path / "missing.log")
    with pytest.raises(FileNotFoundError) as info:
        analyze_thread_health([missing])
    assert info.value.filename == missing


def test_a_folder_raises_is_a_directory_error(tmp_path):
    with pytest.raises(IsADirectoryError) as info:
        analyze_thread_health([str(tmp_path)])
    assert info.value.filename == str(tmp_path)
