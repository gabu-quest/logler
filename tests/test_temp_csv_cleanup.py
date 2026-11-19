"""The temp CSV that SQL loading writes is never left behind."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from logler.sql import SqlEngine

ROOT = Path(__file__).resolve().parent.parent


class _Entry:
    def __init__(self, n: int):
        self.line_number = n
        self.timestamp = None
        self.level = "INFO"
        self.message = f"m{n}"
        self.thread_id = None
        self.correlation_id = None
        self.trace_id = None
        self.span_id = None
        self.raw = f"raw{n}"


class _BadEntry(_Entry):
    @property
    def message(self):
        raise ValueError("boom")

    @message.setter
    def message(self, value):
        pass


class _Index:
    def __init__(self, entries):
        self.entries = entries


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    d = tmp_path / "scratch"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


def test_sql_engine_success_leaves_nothing(scratch):
    engine = SqlEngine()
    engine.load_files({"a.log": _Index([_Entry(1), _Entry(2)])})
    assert engine.conn.execute("SELECT COUNT(*) FROM logs").fetchone() == (2,)
    engine.close()
    assert list(scratch.iterdir()) == []


def test_sql_engine_write_failure_leaves_nothing(scratch):
    engine = SqlEngine()
    with pytest.raises(ValueError, match="boom"):
        engine.load_files({"a.log": _Index([_Entry(1), _BadEntry(2)])})
    engine.close()
    assert list(scratch.iterdir()) == []


def _run_sql_cli(tmp_path, files):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {**os.environ, "TMPDIR": str(scratch)}
    args = [sys.executable, "-m", "logler.cli", "llm", "sql", "SELECT COUNT(*) AS n FROM logs"]
    for f in files:
        args += ["-f", str(f)]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        timeout=60,
    )
    return result, scratch


def test_cli_sql_success_leaves_nothing(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("2024-01-15 10:00:00 INFO hello\n2024-01-15 10:00:01 ERROR bad\n")
    result, scratch = _run_sql_cli(tmp_path, [log])
    assert result.returncode == 0, result.stderr
    assert list(scratch.iterdir()) == []


def test_cli_sql_unreadable_second_file_leaves_nothing(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("2024-01-15 10:00:00 INFO hello\n")
    # A dangling symlink is matched by the glob expansion (a plain missing
    # path is dropped before the loop), so open() fails after file one is
    # already written to the temp CSV.
    dangling = tmp_path / "b.log"
    dangling.symlink_to(tmp_path / "does-not-exist.log")
    result, scratch = _run_sql_cli(tmp_path, [log, dangling])
    assert result.returncode == 2
    assert "Cannot read file" in result.stdout + result.stderr
    assert list(scratch.iterdir()) == []
