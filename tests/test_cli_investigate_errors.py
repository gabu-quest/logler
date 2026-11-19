"""`logler investigate` prints an error it cannot recover from on stderr and exits 1.

The message is printed as written: square brackets in a path are not rich markup.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


def _investigate(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "logler.cli", "investigate", *args],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_a_folder_where_a_file_is_expected_is_an_error_on_stderr(tmp_path):
    (tmp_path / "app.log").mkdir()
    result = _investigate(tmp_path, "app.log")
    assert result.returncode == 1
    assert result.stderr == "❌ Error: [Errno 21] Is a directory: 'app.log'\n"
    assert result.stdout == "🔍 Searching logs...\n\n"


@pytest.mark.parametrize("flag", ["--errors", "--thread=t1"])
def test_the_same_error_in_the_other_modes(tmp_path, flag):
    (tmp_path / "app.log").mkdir()
    result = _investigate(tmp_path, "app.log", flag)
    assert result.returncode == 1
    assert result.stderr == "❌ Error: [Errno 21] Is a directory: 'app.log'\n"


def test_square_brackets_in_the_message_are_printed_as_written(tmp_path):
    (tmp_path / "[prod].log").mkdir()
    result = _investigate(tmp_path, "[prod].log")
    assert result.returncode == 1
    assert result.stderr == "❌ Error: [Errno 21] Is a directory: '[prod].log'\n"


def test_a_closing_tag_in_the_message_is_printed_as_written(tmp_path):
    (tmp_path / "[" / "prod].log").mkdir(parents=True)
    result = _investigate(tmp_path, "[/prod].log")
    assert result.returncode == 1
    assert result.stderr == "❌ Error: [Errno 21] Is a directory: '[/prod].log'\n"


def test_the_hierarchy_error_line_prints_brackets_as_written(tmp_path):
    (tmp_path / "[prod].log").mkdir()
    result = _investigate(tmp_path, "[prod].log", "--thread=t1", "--hierarchy")
    assert result.returncode == 1
    assert "❌ Error building hierarchy: [Errno 21] Is a directory: '[prod].log'\n" in result.stdout
    assert result.stderr == "❌ Error: [Errno 21] Is a directory: '[prod].log'\n"
