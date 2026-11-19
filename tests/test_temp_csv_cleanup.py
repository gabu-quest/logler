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


def _entry(n: int) -> dict:
    return {
        "file": "a.log",
        "line_number": n,
        "timestamp": None,
        "level": "Info",
        "message": f"m{n}",
        "raw": f"raw{n}",
    }


class _BoomEntry(dict):
    """An entry whose message cannot be read."""

    def get(self, key, default=None):
        if key == "message":
            raise ValueError("boom")
        return super().get(key, default)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    d = tmp_path / "scratch"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


def test_sql_engine_success_leaves_nothing(scratch):
    engine = SqlEngine()
    engine.load_entries([_entry(1), _entry(2)])
    assert engine.conn.execute("SELECT COUNT(*) FROM logs").fetchone() == (2,)
    engine.close()
    assert list(scratch.iterdir()) == []


def test_sql_engine_write_failure_leaves_nothing(scratch):
    engine = SqlEngine()
    with pytest.raises(ValueError, match="boom"):
        engine.load_entries([_entry(1), _BoomEntry(_entry(2))])
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


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs a file its owner cannot read"
)
def test_cli_sql_unreadable_second_file_leaves_nothing(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("2024-01-15 10:00:00 INFO hello\n")
    # A file with no read permission is still a file to the glob expansion (a
    # missing path or a dangling link is dropped before the loop), so open()
    # fails after file one is already written to the temp CSV.
    unreadable = tmp_path / "b.log"
    unreadable.write_text("2024-01-15 10:00:01 INFO never read\n")
    unreadable.chmod(0)
    result, scratch = _run_sql_cli(tmp_path, [log, unreadable])
    assert result.returncode == 2
    assert "Cannot read file" in result.stdout + result.stderr
    assert list(scratch.iterdir()) == []
