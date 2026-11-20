"""The binding: a log file that cannot be read is the caller's error (an ``OSError``), the
GIL is released while the engine works, and the module-level functions nothing calls are gone."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest import mock

import click
import pytest
from click.testing import CliRunner

import logler_rs
from logler.cache import clear_cache
from logler.cli import main
from logler.investigate import get_context, get_metadata, search
from logler.llm_cli._core import command

LINE = "2024-01-15T10:00:00.000Z INFO [worker-1] hello world\n"

needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a mode 000 file"
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def unreadable(tmp_path: Path) -> str:
    path = tmp_path / "locked.log"
    path.write_text(LINE)
    path.chmod(0o000)
    yield str(path)
    path.chmod(0o600)


@pytest.fixture
def missing(tmp_path: Path) -> str:
    return str(tmp_path / "gone.log")


@pytest.fixture
def folder(tmp_path: Path) -> str:
    path = tmp_path / "a_folder.log"
    path.mkdir()
    return str(path)


def _load(path: str, with_config: bool) -> None:
    inv = logler_rs.PyInvestigator()
    if with_config:
        inv.load_files_with_config([path], None, None)
    else:
        inv.load_files([path])


@pytest.mark.parametrize("with_config", [False, True])
class TestLoadRaisesOSError:
    @needs_non_root
    def test_unreadable_file_is_permission_error(self, unreadable, with_config):
        with pytest.raises(PermissionError) as info:
            _load(unreadable, with_config)
        assert info.value.filename == unreadable
        assert info.value.errno == 13
        assert info.value.strerror == "Permission denied"

    def test_missing_file_is_file_not_found(self, missing, with_config):
        with pytest.raises(FileNotFoundError) as info:
            _load(missing, with_config)
        assert info.value.filename == missing
        assert info.value.errno == 2
        assert info.value.strerror == "No such file or directory"

    def test_folder_is_is_a_directory_error(self, folder, with_config):
        with pytest.raises(IsADirectoryError) as info:
            _load(folder, with_config)
        assert info.value.filename == folder
        assert info.value.errno == 21
        assert info.value.strerror == "Is a directory"


class TestPythonApi:
    def test_search_of_a_missing_file_raises_file_not_found(self, missing):
        with pytest.raises(FileNotFoundError) as info:
            search(files=[missing])
        assert info.value.filename == missing

    def test_metadata_of_a_folder_raises_is_a_directory_error(self, folder):
        with pytest.raises(IsADirectoryError) as info:
            get_metadata(files=[folder])
        assert info.value.filename == folder


class TestOtherErrorsKeepTheirType:
    def _loaded(self, tmp_path: Path):
        path = tmp_path / "ok.log"
        path.write_text(LINE)
        inv = logler_rs.PyInvestigator()
        inv.load_files([str(path)])
        return inv, str(path)

    def test_broken_query_json_is_value_error(self, tmp_path):
        inv, _ = self._loaded(tmp_path)
        with pytest.raises(ValueError):
            inv.search("{not json")

    def test_engine_error_that_is_not_io_is_runtime_error_not_os_error(self, tmp_path):
        inv, path = self._loaded(tmp_path)
        with pytest.raises(RuntimeError) as info:
            inv.get_context(path + ".other", 1, 0, 0, False)
        assert not isinstance(info.value, OSError)
        assert str(info.value) == f"File not indexed: {path}.other"

    def test_a_pattern_that_is_not_a_regex_is_a_value_error(self, tmp_path):
        inv, path = self._loaded(tmp_path)
        query = {"files": [path], "filters": {"exclude_pattern": "("}}
        with pytest.raises(logler_rs.InvalidPatternError) as info:
            inv.search(json.dumps(query))
        assert isinstance(info.value, ValueError)
        assert not isinstance(info.value, RuntimeError)
        assert str(info.value) == 'Invalid exclude pattern "(": unclosed group'


class TestLlmSearchExitCodes:
    @needs_non_root
    def test_unreadable_file_is_exit_2_and_names_the_file(self, unreadable):
        result = CliRunner().invoke(main, ["llm", "search", unreadable])
        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data == {
            "error": f"{unreadable}: Permission denied",
            "code": 2,
            "file": unreadable,
        }

    def test_file_deleted_after_the_glob_is_exit_2_and_names_the_file(self, missing):
        with mock.patch("logler.llm_cli._core._expand_globs", return_value=[missing]):
            result = CliRunner().invoke(main, ["llm", "search", "whatever.log"])
        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data == {
            "error": f"{missing}: No such file or directory",
            "code": 2,
            "file": missing,
        }

    @needs_non_root
    def test_a_file_that_cannot_be_written_is_named_without_calling_it_a_read(
        self, tmp_path, monkeypatch
    ):
        log = tmp_path / "ok.log"
        log.write_text(LINE)
        home = tmp_path / "home"
        (home / ".logler").mkdir(parents=True)
        (home / ".logler").chmod(0o500)
        monkeypatch.setenv("HOME", str(home))
        try:
            result = CliRunner().invoke(main, ["llm", "session", "create", "-f", str(log)])
        finally:
            (home / ".logler").chmod(0o700)
        assert result.exit_code == 2, result.output
        assert json.loads(result.output) == {
            "error": f"{home}/.logler/sessions: Permission denied",
            "code": 2,
            "file": f"{home}/.logler/sessions",
        }

    def test_non_io_engine_error_stays_exit_3(self, tmp_path):
        path = tmp_path / "ok.log"
        path.write_text(LINE)
        with mock.patch(
            "logler.investigate.search", side_effect=RuntimeError("File not indexed: ok.log")
        ):
            result = CliRunner().invoke(main, ["llm", "search", str(path)])
        # an engine error that is not I/O and not the caller's input: an internal error
        assert result.exit_code == 3, result.output
        assert json.loads(result.output) == {
            "error": "Internal error: File not indexed: ok.log",
            "code": 3,
        }

    def test_an_os_error_with_no_file_name_is_exit_3_and_has_no_file_key(self):
        group = click.Group()

        @command("oserr_nofile", group=group)
        def _boom(pretty):
            raise OSError("no name here")

        result = CliRunner().invoke(group, ["oserr_nofile"])
        assert result.exit_code == 3, result.output
        assert json.loads(result.output) == {
            "error": "Internal error: no name here",
            "code": 3,
        }


LINES_41 = LINE * 41


class TestLineWithNoEntryIsTheCallersError:
    @pytest.fixture
    def app_log(self, tmp_path):
        path = tmp_path / "app.log"
        path.write_text(LINES_41)
        return str(path)

    @pytest.mark.parametrize("line", ["9999", "0", "42", "-1"])
    def test_llm_context_is_exit_2_and_names_file_and_line(self, app_log, line):
        result = CliRunner().invoke(main, ["llm", "context", app_log, "--", line])
        assert result.exit_code == 2, result.output
        assert json.loads(result.output) == {
            "error": f"{app_log}: no entry at line {line}",
            "code": 2,
        }

    def test_llm_context_on_an_empty_file_is_exit_2(self, tmp_path):
        path = tmp_path / "empty.log"
        path.write_text("")
        result = CliRunner().invoke(main, ["llm", "context", str(path), "1"])
        assert result.exit_code == 2, result.output
        assert json.loads(result.output) == {
            "error": f"{path}: no entry at line 1",
            "code": 2,
        }

    @pytest.mark.parametrize("line", [9999, 0, -1])
    def test_get_context_raises_value_error_with_the_same_text(self, app_log, line):
        with pytest.raises(ValueError) as info:
            get_context(app_log, line)
        assert str(info.value) == f"{app_log}: no entry at line {line}"
        assert not isinstance(info.value, RuntimeError)

    def test_a_line_with_an_entry_is_unchanged(self, app_log):
        assert get_context(app_log, 41, 1, 0)["target"]["line_number"] == 41


class TestHumanCliMessage:
    """The human commands print any error and exit 1; now the text of the error names the file."""

    def test_error_text_holds_the_file_name_and_reason(self, missing):
        with pytest.raises(FileNotFoundError) as info:
            search(files=[missing])
        assert str(info.value) == f"[Errno 2] No such file or directory: '{missing}'"


def test_module_level_functions_nothing_calls_are_gone():
    for name in (
        "search",
        "follow_thread",
        "find_patterns",
        "get_metadata",
        "build_hierarchy",
        "extract_ids",
    ):
        assert not hasattr(logler_rs, name), name
    assert sorted(n for n in dir(logler_rs) if not n.startswith("_") and n != "logler_rs") == [
        "InvalidPatternError",
        "LineNotFoundError",
        "PyInvestigator",
        "PyLineParser",
        "level_name",
        "timestamp_keys",
    ]


def _big_log(path: Path, lines: int) -> str:
    row = (
        "2024-01-15T10:00:00.000Z {level} [worker-{n}] correlation_id=req-{n} message number {i}\n"
    )
    levels = ("INFO", "WARN", "ERROR", "DEBUG")
    with path.open("w") as out:
        for i in range(lines):
            out.write(row.format(level=levels[i % 4], n=i % 50, i=i))
    return str(path)


def _longest_stall_while(work) -> tuple[float, float]:
    """Run ``work`` in a thread; return (its duration, the longest gap between two ticks of
    a plain Python loop in this thread while it ran). A call that holds the GIL for its whole
    duration leaves a gap as long as the call."""
    done = threading.Event()
    failure: list[BaseException] = []

    def run():
        try:
            work()
        except BaseException as exc:  # reported below, so a failing call cannot hang the loop
            failure.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=run)
    start = time.perf_counter()
    last = start
    longest = 0.0
    worker.start()
    while not done.is_set():
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
        time.sleep(0.001)
    worker.join()
    if failure:
        raise failure[0]
    return time.perf_counter() - start, longest


class TestGilReleased:
    def test_load_and_search_do_not_stall_other_threads(self, tmp_path):
        path = _big_log(tmp_path / "big.log", 400_000)
        inv = logler_rs.PyInvestigator()
        load_time, load_stall = _longest_stall_while(lambda: inv.load_files([path]))
        # every line matches and 100,000 are written out, so the search is long enough to time
        query = json.dumps({"files": [path], "query": "number", "filters": {}, "limit": 100_000})
        search_time, search_stall = _longest_stall_while(lambda: inv.search(query))
        assert load_time > 0.1, load_time  # long enough to show a stall
        assert load_stall < load_time / 2, (load_stall, load_time)
        assert search_time > 0.1, search_time
        assert search_stall < search_time / 2, (search_stall, search_time)

    def test_a_call_made_during_a_load_waits_for_the_load(self, tmp_path):
        path = _big_log(tmp_path / "big.log", 400_000)
        inv = logler_rs.PyInvestigator()
        done = threading.Event()
        failure: list[BaseException] = []

        def load():
            try:
                inv.load_files([path])
            except BaseException as exc:  # reported below
                failure.append(exc)
            finally:
                done.set()

        loader = threading.Thread(target=load)
        loader.start()
        pages = 0
        while not done.is_set():
            inv.get_entries_page(0, 1)  # raised "Already mutably borrowed" during the load
            pages += 1
        loader.join()
        assert failure == []
        assert pages > 0
        first = json.loads(inv.get_entries_page(0, 1))
        assert [entry["line_number"] for entry in first["entries"]] == [1]
        assert first["total_entries"] == 400_000
