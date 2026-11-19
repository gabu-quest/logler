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
    assert result.returncode == 2
    assert result.stderr == "❌ Error: app.log: Is a directory\n"
    assert result.stdout == "🔍 Searching logs...\n\n"


@pytest.mark.parametrize("flag", ["--errors", "--thread=t1"])
def test_the_same_error_in_the_other_modes(tmp_path, flag):
    (tmp_path / "app.log").mkdir()
    result = _investigate(tmp_path, "app.log", flag)
    assert result.returncode == 2
    assert result.stderr == "❌ Error: app.log: Is a directory\n"


def test_square_brackets_in_the_message_are_printed_as_written(tmp_path):
    (tmp_path / "[prod].log").mkdir()
    result = _investigate(tmp_path, "[prod].log")
    assert result.returncode == 2
    assert result.stderr == "❌ Error: [prod].log: Is a directory\n"


def test_a_closing_tag_in_the_message_is_printed_as_written(tmp_path):
    (tmp_path / "[" / "prod].log").mkdir(parents=True)
    result = _investigate(tmp_path, "[/prod].log")
    assert result.returncode == 2
    assert result.stderr == "❌ Error: [/prod].log: Is a directory\n"


def test_a_folder_given_to_a_hierarchy_is_the_one_sentence_and_no_fallback(tmp_path):
    (tmp_path / "[prod].log").mkdir()
    result = _investigate(tmp_path, "[prod].log", "--thread=t1", "--hierarchy")
    assert result.returncode == 2
    assert result.stderr == "❌ Error: [prod].log: Is a directory\n"
    assert "Error building hierarchy" not in result.stdout
    assert "Falling back" not in result.stdout


def _cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "logler.cli", *args],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("command", ["view", "stats"])
def test_view_and_stats_name_the_file_and_exit_2(tmp_path, command):
    (tmp_path / "app.log").mkdir()
    result = _cli(tmp_path, command, "app.log")
    assert result.returncode == 2
    assert result.stderr == "❌ Error: app.log: Is a directory\n"


def test_a_file_name_with_a_space_and_a_quote(tmp_path):
    (tmp_path / "my \"app\" 'x'.log").mkdir()
    result = _cli(tmp_path, "view", "my \"app\" 'x'.log")
    assert result.returncode == 2
    assert result.stderr == "❌ Error: my \"app\" 'x'.log: Is a directory\n"


def test_watch_on_a_missing_directory_is_refused_with_exit_2(tmp_path):
    result = _cli(tmp_path, "watch", "*.log", "-d", "nowhere")
    assert result.returncode == 2
    assert result.stderr.endswith("Directory 'nowhere' does not exist.\n")


def test_an_os_error_with_no_file_name_has_no_file_message():
    from logler.llm_cli._core import file_error_message

    assert file_error_message(OSError("boom")) is None
    assert file_error_message(OSError(2, "No such file or directory")) is None
    assert (
        file_error_message(FileNotFoundError(2, "No such file or directory", "a b.log"))
        == "a b.log: No such file or directory"
    )
