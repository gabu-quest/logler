"""
Tests for the LLM-first CLI commands.

These tests verify that:
1. All commands output valid JSON
2. Exit codes are meaningful
3. No truncation occurs
4. Commands handle edge cases gracefully
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from logler.llm_cli import llm

from tests.conftest import EXIT_NO_RESULTS, EXIT_SUCCESS, EXIT_USER_ERROR, invoke, run_llm_command


class TestSchemaCommand:
    """Tests for logler llm schema"""

    def test_schema_basic(self, sample_log_file):
        """Test basic schema inference."""
        result = run_llm_command(["schema", sample_log_file])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert output["files_analyzed"] == 1
        assert output["total_entries"] == 10
        assert "schema" in output

    def test_schema_json_output(self, sample_log_file):
        """Test that schema outputs valid JSON."""
        result = run_llm_command(["schema", sample_log_file])
        assert result.returncode == EXIT_SUCCESS

        # Should be valid JSON
        output = json.loads(result.stdout)
        assert isinstance(output, dict)

    def test_schema_empty_file(self):
        """Test schema with empty file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("")
            f.flush()
            result = run_llm_command(["schema", f.name])
        os.unlink(f.name)

        assert result.returncode == EXIT_NO_RESULTS
        output = json.loads(result.stdout)
        assert output["total_entries"] == 0

    def test_schema_file_not_found(self):
        """Test schema with non-existent file."""
        result = run_llm_command(["schema", "/nonexistent/file.log"])
        assert result.returncode == EXIT_USER_ERROR

        output = json.loads(result.stdout)
        assert "error" in output

    def test_schema_with_sample_size(self, sample_log_file):
        """Test schema with custom sample size."""
        result = run_llm_command(["schema", sample_log_file, "--sample-size", "5"])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert output["sample_size"] == 5

    def test_schema_pretty_output(self, sample_log_file):
        """Test pretty-printed JSON output."""
        result = run_llm_command(["schema", sample_log_file, "--pretty"])
        assert result.returncode == EXIT_SUCCESS

        # Pretty output should have indentation
        assert "\n  " in result.stdout


class TestSampleCommand:
    """Tests for logler llm sample"""

    def test_sample_basic(self, sample_log_file):
        """Test basic sampling."""
        result = run_llm_command(["sample", sample_log_file, "--size", "5"])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "population" in output
        assert "sample" in output
        assert "entries" in output


class TestTriageCommand:
    """Tests for logler llm triage"""

    def test_triage_basic(self, sample_log_file):
        """Test basic triage."""
        result = run_llm_command(["triage", sample_log_file])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "assessment" in output
        assert "severity" in output["assessment"]
        assert "metrics" in output


class TestEmitCommand:
    """Tests for logler llm emit"""

    def test_emit_basic(self, sample_log_file):
        """Test basic JSONL emission."""
        result = run_llm_command(["emit", sample_log_file])
        assert result.returncode == EXIT_SUCCESS

        # Each line should be valid JSON
        for line in result.stdout.strip().split("\n"):
            if line:
                parsed = json.loads(line)
                assert "line_number" in parsed

    def test_emit_compact(self, sample_log_file):
        """Test compact JSONL emission."""
        result = run_llm_command(["emit", sample_log_file, "--compact"])
        assert result.returncode == EXIT_SUCCESS

        # Compact format uses short keys
        for line in result.stdout.strip().split("\n"):
            if line:
                parsed = json.loads(line)
                assert "ln" in parsed  # Short key for line_number

    def test_emit_compact_src_multi_file(self, sample_log_file):
        """Compact mode includes src field when emitting multiple files."""
        # Create a second log file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f2:
            f2.write("2024-01-15T11:00:00.000Z INFO [worker-3] Secondary log entry\n")
            f2.flush()
            second_file = f2.name

        try:
            result = run_llm_command(
                ["emit", sample_log_file, second_file, "--compact", "--limit", "5"]
            )
            assert result.returncode == EXIT_SUCCESS

            lines = [line for line in result.stdout.strip().split("\n") if line]
            assert len(lines) > 0
            for line in lines:
                parsed = json.loads(line)
                assert "src" in parsed, "compact multi-file emit must include 'src'"
                # src should be filename only, not full path
                assert "/" not in parsed["src"]
        finally:
            os.unlink(second_file)

    def test_emit_compact_no_src_single_file(self, sample_log_file):
        """Compact mode omits src field for single-file emit."""
        result = run_llm_command(["emit", sample_log_file, "--compact", "--limit", "3"])
        assert result.returncode == EXIT_SUCCESS

        for line in result.stdout.strip().split("\n"):
            if line:
                parsed = json.loads(line)
                assert "src" not in parsed, "compact single-file emit should NOT include 'src'"

    def test_emit_with_level_filter(self, sample_log_file):
        """Test emit with level filter."""
        result = run_llm_command(["emit", sample_log_file, "--level", "ERROR"])
        assert result.returncode == EXIT_SUCCESS

        lines = [line for line in result.stdout.strip().split("\n") if line]
        assert len(lines) > 0
        for output_line in lines:
            parsed = json.loads(output_line)
            level = parsed.get("level") or parsed.get("lv")
            assert level == "ERROR"


class TestVerifyPatternCommand:
    """Tests for logler llm verify-pattern"""

    def test_verify_pattern_basic(self, sample_log_file):
        """Test basic pattern verification."""
        result = run_llm_command(["verify-pattern", sample_log_file, "--pattern", "timeout"])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "pattern" in output
        assert "verified" in output
        assert "statistics" in output
        assert output["verified"] is True

    def test_verify_pattern_no_match(self, sample_log_file):
        """Test pattern that doesn't match."""
        result = run_llm_command(
            ["verify-pattern", sample_log_file, "--pattern", "zzzznonexistentzzzz"]
        )
        assert result.returncode == EXIT_NO_RESULTS

        output = json.loads(result.stdout)
        assert output["verified"] is False

    def test_verify_pattern_with_groups(self, sample_log_file):
        """Test pattern with capture groups."""
        result = run_llm_command(
            [
                "verify-pattern",
                sample_log_file,
                "--pattern",
                r"timeout after (\d+)ms",
                "--extract-groups",
            ]
        )
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "extracted_groups" in output


class TestDiffCommand:
    """Tests for logler llm diff"""

    def test_diff_with_baseline(self, sample_log_file):
        """Test diff with baseline."""
        result = run_llm_command(["diff", sample_log_file, "--baseline", "1h"])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "comparison" in output
        assert "before" in output["comparison"]
        assert "after" in output["comparison"]
        assert "changes" in output


class TestSessionCommands:
    """Tests for logler llm session subcommands"""

    def test_session_create(self, sample_log_file, _isolated_home):
        """Test session creation."""
        result = run_llm_command(
            ["session", "create", "-f", sample_log_file, "--name", "test-session"]
        )
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "session_id" in output
        assert output["session_id"].startswith("sess_")
        assert output["status"] == "active"

        assert Path(output["session_file"]).parent == _isolated_home / ".logler" / "sessions"
        assert Path(output["session_file"]).exists()

    def test_session_list(self):
        """Test session listing."""
        result = run_llm_command(["session", "list"])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "sessions" in output


class TestExitCodes:
    """Tests for consistent exit codes across commands"""

    def test_schema_success(self, sample_log_file):
        """Verify schema exits with success on valid file."""
        result = run_llm_command(["schema", sample_log_file])
        assert result.returncode == EXIT_SUCCESS

    def test_schema_error_on_missing_file(self):
        """Verify schema exits with error on missing file."""
        result = run_llm_command(["schema", "/nonexistent/file.log"])
        assert result.returncode == EXIT_USER_ERROR


class TestJSONOutput:
    """Tests to verify all commands output valid JSON"""

    def test_schema_outputs_json(self, sample_log_file):
        """Verify schema outputs valid JSON."""
        result = run_llm_command(["schema", sample_log_file])
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"schema did not output valid JSON: {result.stdout[:200]}")

    def test_emit_outputs_jsonl(self, sample_log_file):
        """Verify emit outputs valid JSONL."""
        result = run_llm_command(["emit", sample_log_file])
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    pytest.fail(f"emit line was not valid JSON: {line[:200]}")

    def test_verify_pattern_outputs_json(self, sample_log_file):
        """Verify verify-pattern outputs valid JSON."""
        result = run_llm_command(["verify-pattern", sample_log_file, "--pattern", "test"])
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"verify-pattern did not output valid JSON: {result.stdout[:200]}")

    def test_diff_outputs_json(self, sample_log_file):
        """Verify diff outputs valid JSON."""
        result = run_llm_command(["diff", sample_log_file, "--baseline", "1h"])
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"diff did not output valid JSON: {result.stdout[:200]}")

    def test_session_list_outputs_json(self):
        """Verify session list outputs valid JSON."""
        result = run_llm_command(["session", "list"])
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"session list did not output valid JSON: {result.stdout[:200]}")


class TestNoTruncation:
    """Tests to verify no truncation occurs"""

    def test_emit_no_truncation(self):
        """Verify emit returns all entries without truncation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            for i in range(150):
                f.write(f"2024-01-15T10:00:{i % 60:02d}.000Z INFO Line {i}\n")
            f.flush()
            log_file = f.name

        try:
            result = run_llm_command(["emit", log_file])
            assert result.returncode == EXIT_SUCCESS

            lines = [line for line in result.stdout.strip().split("\n") if line]
            assert len(lines) == 150

        finally:
            os.unlink(log_file)


class TestIdsCommand:
    """Test the ids CLI command."""

    def test_ids_outputs_json(self, filtering_cli_log):
        result = run_llm_command(["ids", filtering_cli_log])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["total_entries"] == 80
        assert len(data["thread_ids"]) == 2
        assert len(data["services"]) == 2

    def test_ids_pretty(self, filtering_cli_log):
        result = run_llm_command(["ids", filtering_cli_log, "--pretty"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["total_entries"] == 80


class TestMaxBytesCLI:
    """Test --max-bytes truncation via CLI."""

    def test_max_bytes_truncates(self, filtering_cli_log):
        result = run_llm_command(
            [
                "search",
                filtering_cli_log,
                "--max-bytes",
                "500",
            ]
        )
        assert result.returncode == EXIT_SUCCESS
        raw = result.stdout.encode("utf-8")
        assert len(raw) <= 600  # Some margin for final serialization
        data = json.loads(result.stdout)
        assert data.get("truncated") is True


# =============================================================================
# CLI Smoke Suite
# =============================================================================


class TestCLISmokeSuite:
    """Comprehensive CLI smoke tests using filtering_cli_log (80 entries)."""

    def test_ids_command_structure(self, filtering_cli_log):
        """ids returns valid JSON with exact counts."""
        result = run_llm_command(["ids", filtering_cli_log])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["total_entries"] == 80
        assert len(data["thread_ids"]) == 2
        assert len(data["services"]) == 2
        assert len(data["correlation_ids"]) == 5

    def test_search_multi_level_tail(self, filtering_cli_log):
        """--level ERROR,WARN --tail 5 returns last 5 of 40 matches."""
        result = run_llm_command(
            ["search", filtering_cli_log, "--level", "ERROR,WARN", "--tail", "5"]
        )
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["summary"]["total_matches"] == 40
        assert len(data["results"]) == 5

    def test_search_exclude_level(self, filtering_cli_log):
        """--exclude-level DEBUG removes 20 entries, leaving 60."""
        result = run_llm_command(["search", filtering_cli_log, "--exclude-level", "DEBUG"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["summary"]["total_matches"] == 60

    def test_search_service_filter(self, filtering_cli_log):
        """--service svc-x returns 40 entries."""
        result = run_llm_command(["search", filtering_cli_log, "--service", "svc-x"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["summary"]["total_matches"] == 40

    def test_search_fields_projection(self, filtering_cli_log):
        """--fields limits to exact key set."""
        result = run_llm_command(
            [
                "search",
                filtering_cli_log,
                "--level",
                "ERROR",
                "--limit",
                "3",
                "--fields",
                "timestamp,level",
            ]
        )
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert len(data["results"]) == 3
        for item in data["results"]:
            assert set(item.keys()) == {"timestamp", "level"}

    def test_search_max_bytes_truncates(self, filtering_cli_log):
        """--max-bytes truncates and reports metadata."""
        result = run_llm_command(["search", filtering_cli_log, "--max-bytes", "2000"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["truncated"] is True
        assert data["original_count"] == 80
        assert 0 < data["truncated_at"] < 80
        assert len(data["results"]) == data["truncated_at"]

    def test_search_nonexistent_service(self, filtering_cli_log):
        """Nonexistent service returns exit code 1."""
        result = run_llm_command(["search", filtering_cli_log, "--service", "nonexistent"])
        assert result.returncode == EXIT_NO_RESULTS

    def test_triage_output_structure(self, filtering_cli_log):
        """Triage returns metrics with exact error_count/rate."""
        result = run_llm_command(["triage", filtering_cli_log])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        metrics = data["metrics"]
        assert metrics["total_entries"] == 80
        assert metrics["error_count"] == 20
        assert metrics["error_rate"] == 0.25
        assert metrics["log_levels"]["ERROR"] == 20
        assert metrics["log_levels"]["INFO"] == 20


class TestMaxBytesAdditionalCommands:
    """Test --max-bytes on correlate, hierarchy, bottleneck, summarize."""

    def test_summarize_max_bytes(self, filtering_cli_log):
        """--max-bytes on summarize should truncate list fields."""
        normal = run_llm_command(["summarize", filtering_cli_log])
        capped = run_llm_command(["summarize", filtering_cli_log, "--max-bytes", "800"])
        assert normal.returncode == EXIT_SUCCESS
        assert capped.returncode == EXIT_SUCCESS
        # Capped output should be smaller or equal
        assert len(capped.stdout) <= len(normal.stdout)


class TestLevelWords:
    """A level word names a level, or it is the user's error; every command reads it alike."""

    LEVEL_COMMANDS = [
        ["search", "{f}", "--level", "bogus"],
        ["search", "{f}", "--exclude-level", "bogus"],
        ["sample", "{f}", "--level", "bogus"],
        ["sample", "{f}", "--exclude-level", "bogus"],
        ["emit", "{f}", "--level", "bogus"],
        ["emit", "{f}", "--exclude-level", "bogus"],
        ["session", "query", "no-such-session", "--level", "bogus"],
        ["correlate-events", "{f}", "--trigger-level", "bogus"],
    ]

    @pytest.mark.parametrize("args", LEVEL_COMMANDS)
    def test_unknown_word_is_exit_2_with_json_error(self, three_hour_log, args):
        code, stdout, _ = invoke([a.replace("{f}", three_hour_log) for a in args])
        assert code == 2
        assert json.loads(stdout) == {"error": "Unknown log level: bogus", "code": 2}

    @pytest.fixture
    def three_level_log(self, tmp_path):
        path = tmp_path / "levels.log"
        path.write_text(
            "2024-01-15 10:00:00 INFO fine\n"
            "2024-01-15 10:00:01 WARN careful\n"
            "2024-01-15 10:00:02 ERROR broken\n"
        )
        return str(path)

    @pytest.mark.parametrize("word", ["warning", "WARN", "warn"])
    def test_sample_exclude_level_reads_every_spelling_alike(self, three_level_log, word):
        _, stdout, _ = invoke(["sample", three_level_log, "--exclude-level", word, "--size", "10"])
        assert sorted(e["level"] for e in json.loads(stdout)["entries"]) == ["ERROR", "INFO"]

    @pytest.mark.parametrize("word", ["warning", "WARN", "warn"])
    def test_emit_exclude_level_reads_every_spelling_alike(self, three_level_log, word):
        _, stdout, _ = invoke(["emit", three_level_log, "--exclude-level", word])
        assert [json.loads(line)["level"] for line in stdout.splitlines()] == ["INFO", "ERROR"]


class TestCommandShell:
    """Every llm command takes --pretty and reports an uncaught exception the same way."""

    @staticmethod
    def _commands(group, prefix=()):
        import click

        for name, cmd in sorted(group.commands.items()):
            if isinstance(cmd, click.Group):
                yield from TestCommandShell._commands(cmd, prefix + (name,))
            else:
                yield prefix + (name,), cmd

    def test_every_command_has_pretty_but_the_one_that_streams_lines(self):
        commands = list(self._commands(llm))
        assert len(commands) == 30
        without = [
            " ".join(path)
            for path, cmd in commands
            if not any("--pretty" in p.opts for p in cmd.params)
        ]
        assert without == ["emit"]

    @pytest.mark.parametrize(
        "args,target,stream",
        [
            (["summarize", "{f}"], "logler.parser.LogParser.for_file", "stdout"),
            (["compare", "a", "b", "-f", "{f}"], "logler.investigate.follow_thread", "stdout"),
            (["emit", "{f}"], "logler.parser.LogParser.for_file", "stderr"),
        ],
    )
    def test_uncaught_exception_is_the_json_internal_error(
        self, monkeypatch, three_hour_log, args, target, stream
    ):
        module, _, attr = target.rpartition(".")
        if module == "logler.parser.LogParser":
            from logler.parser import LogParser as owner

            monkeypatch.setattr(owner, "for_file", classmethod(_boom))
        else:
            import logler.investigate as owner

            monkeypatch.setattr(owner, attr, _boom)
        code, stdout, stderr = invoke([a.replace("{f}", three_hour_log) for a in args])
        assert code == 3
        text = {"stdout": stdout, "stderr": stderr}[stream]
        assert json.loads(text) == {"error": "Internal error: boom", "code": 3}
        assert {"stdout": stderr, "stderr": stdout}[stream] == ""


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


class TestFilesArgument:
    """Which files a FILES argument names."""

    def test_a_folder_matched_by_a_glob_is_not_a_log_file(self, three_hour_log, tmp_path):
        (tmp_path / "old").mkdir()

        code, out, _ = invoke(["search", str(tmp_path / "*"), "--count-only"])

        assert code == 0, out
        assert json.loads(out)["total_matches"] == 3

    def test_a_folder_given_by_name_is_no_file(self, tmp_path):
        (tmp_path / "old").mkdir()

        code, out, _ = invoke(["search", str(tmp_path / "old")])

        assert code == 2, out
        assert json.loads(out)["error"].startswith("No files found matching")


class TestPerLineReadersNumberLinesAsSearchDoes:
    """schema, summarize, verify-pattern, emit, diff, format test and stats cut a file as
    search does: a line ends at "\\n" or "\\r\\n", a bare "\\r" stays in the line, the text
    keeps its trailing spaces."""

    @pytest.fixture
    def carriage_return_log(self, tmp_path):
        """Four lines; line 2 ends in spaces, line 3 holds a bare carriage return."""
        path = tmp_path / "cr.log"
        path.write_bytes(
            b"2024-01-15T10:00:00Z ERROR one\n"
            b"2024-01-15T10:00:01Z ERROR two  \n"
            b"2024-01-15T10:00:02Z ERROR three\r2024-01-15T10:00:02Z ERROR still three\n"
            b"2024-01-15T10:00:03Z ERROR four\n"
        )
        return str(path)

    def test_search_is_the_reference(self, carriage_return_log):
        _, stdout, _ = invoke(["search", carriage_return_log, "--compact"])
        assert sorted(e["ln"] for e in json.loads(stdout)["results"]) == [1, 2, 3, 4]

    def test_emit(self, carriage_return_log):
        _, stdout, _ = invoke(["emit", carriage_return_log])
        assert [json.loads(line)["line_number"] for line in stdout.splitlines()] == [1, 2, 3, 4]

    def test_summarize(self, carriage_return_log):
        _, stdout, _ = invoke(["summarize", carriage_return_log])
        data = json.loads(stdout)
        assert data["stats"]["total_entries"] == 4
        assert [e["line"] for e in data["errors"]] == [1, 2, 3, 4]

    def test_schema(self, carriage_return_log):
        _, stdout, _ = invoke(["schema", carriage_return_log])
        assert json.loads(stdout)["total_entries"] == 4

    def test_verify_pattern_numbers_the_line_after_it_as_search_does(self, carriage_return_log):
        _, stdout, _ = invoke(["verify-pattern", carriage_return_log, "--pattern", "four"])
        (match,) = json.loads(stdout)["sample_matches"]
        assert (match["line_number"], match["raw"]) == (4, "2024-01-15T10:00:03Z ERROR four")

    def test_verify_pattern_raw_keeps_trailing_spaces(self, carriage_return_log):
        _, stdout, _ = invoke(["verify-pattern", carriage_return_log, "--pattern", "two"])
        (match,) = json.loads(stdout)["sample_matches"]
        assert (match["line_number"], match["raw"]) == (2, "2024-01-15T10:00:01Z ERROR two  ")

    def test_diff(self, carriage_return_log):
        _, stdout, _ = invoke(
            [
                "diff",
                carriage_return_log,
                "--before-start",
                "2024-01-15T10:00:00",
                "--before-end",
                "2024-01-15T10:00:03",
                "--after-start",
                "2024-01-15T11:00:00",
                "--after-end",
                "2024-01-15T12:00:00",
            ]
        )
        assert json.loads(stdout)["comparison"]["before"]["total"] == 4

    def test_format_test(self, carriage_return_log):
        regex = r"(?P<ts>\S+) (?P<level>\w+) (?P<msg>four)"
        _, stdout, _ = invoke(["format", "test", "-f", carriage_return_log, "--regex", regex])
        data = json.loads(stdout)
        assert data["total_lines"] == 4
        assert [r["line_number"] for r in data["results"] if r["matched"]] == [4]

    def test_stats(self, carriage_return_log):
        from click.testing import CliRunner

        from logler.cli import main

        result = CliRunner().invoke(main, ["stats", carriage_return_log, "--json"])
        assert json.loads(result.stdout)["total"] == 4

    def test_blank_lines_keep_their_present_treatment(self, tmp_path):
        """The five that skip a blank line still skip it (and a line of spaces); the line
        numbers still count it."""
        path = tmp_path / "blank.log"
        path.write_bytes(
            b"2024-01-15T10:00:00Z ERROR one\n\n   \n2024-01-15T10:00:03Z ERROR four\n"
        )
        _, stdout, _ = invoke(["emit", str(path)])
        assert [json.loads(line)["line_number"] for line in stdout.splitlines()] == [1, 4]
        _, stdout, _ = invoke(["summarize", str(path)])
        assert json.loads(stdout)["stats"]["total_entries"] == 2
        _, stdout, _ = invoke(["schema", str(path)])
        assert json.loads(stdout)["total_entries"] == 2
        _, stdout, _ = invoke(["verify-pattern", str(path), "--pattern", "ERROR"])
        assert json.loads(stdout)["statistics"]["total_entries"] == 2
        _, stdout, _ = invoke(
            [
                "diff",
                str(path),
                "--before-start",
                "2024-01-15T10:00:00",
                "--before-end",
                "2024-01-15T10:00:05",
                "--after-start",
                "2024-01-15T11:00:00",
                "--after-end",
                "2024-01-15T12:00:00",
            ]
        )
        assert json.loads(stdout)["comparison"]["before"]["total"] == 2

    def test_format_test_skips_an_empty_line_and_keeps_a_line_of_spaces(self, tmp_path):
        path = tmp_path / "blank.log"
        path.write_bytes(
            b"2024-01-15T10:00:00Z ERROR one\n\n   \n2024-01-15T10:00:03Z ERROR four\n"
        )
        _, stdout, _ = invoke(["format", "test", "-f", str(path), "--regex", r"(?P<ts>\S+) .*"])
        data = json.loads(stdout)
        assert data["total_lines"] == 3
        assert [(r["line_number"], r["matched"]) for r in data["results"]] == [
            (1, True),
            (3, False),
            (4, True),
        ]
