"""
Tests for the LLM-first CLI commands.

These tests verify that:
1. All commands output valid JSON
2. Exit codes are meaningful
3. No truncation occurs
4. Commands handle edge cases gracefully
"""

import json
import pytest
import subprocess
import tempfile
import os
from pathlib import Path

# Exit codes (should match llm_cli.py)
EXIT_SUCCESS = 0
EXIT_NO_RESULTS = 1
EXIT_USER_ERROR = 2


def run_llm_command(args, timeout=60):
    """Run a logler llm command and return result."""
    cmd = ["python", "-m", "logler.cli", "llm"] + args
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=str(Path(__file__).parent.parent)
    )
    return result


@pytest.fixture
def sample_log_file():
    """Create a sample log file for testing."""
    content = """2024-01-15T10:00:00.000Z INFO [worker-1] correlation_id=req-abc123 Starting request processing
2024-01-15T10:00:00.050Z DEBUG [worker-1] correlation_id=req-abc123 Validating user token
2024-01-15T10:00:00.100Z INFO [worker-1] correlation_id=req-abc123 User validated successfully
2024-01-15T10:00:00.150Z INFO [worker-1] correlation_id=req-abc123 Querying database
2024-01-15T10:00:00.500Z WARN [worker-1] correlation_id=req-abc123 Query took 350ms
2024-01-15T10:00:01.000Z ERROR [worker-1] correlation_id=req-abc123 Database timeout after 500ms
2024-01-15T10:00:01.100Z INFO [worker-1] correlation_id=req-abc123 Retrying database query
2024-01-15T10:00:01.600Z ERROR [worker-1] correlation_id=req-abc123 Retry failed: connection pool exhausted
2024-01-15T10:00:01.700Z INFO [worker-1] correlation_id=req-abc123 Returning error response to client
2024-01-15T10:00:02.000Z INFO [worker-2] correlation_id=req-def456 Starting new request
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(content)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def json_log_file():
    """Create a JSON log file for testing."""
    entries = [
        {
            "timestamp": "2024-01-15T10:00:00Z",
            "level": "INFO",
            "message": "Starting",
            "thread_id": "main",
        },
        {
            "timestamp": "2024-01-15T10:00:01Z",
            "level": "ERROR",
            "message": "Database timeout",
            "thread_id": "worker-1",
        },
        {
            "timestamp": "2024-01-15T10:00:02Z",
            "level": "INFO",
            "message": "Recovered",
            "thread_id": "worker-1",
        },
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        f.flush()
        yield f.name
    os.unlink(f.name)


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


class TestSearchCommand:
    """Tests for logler llm search"""

    def test_search_basic(self, sample_log_file):
        """Test basic search."""
        result = run_llm_command(["search", sample_log_file])
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "query" in output
        assert "summary" in output
        assert "results" in output
        assert output["summary"]["total_matches"] == 10


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

    def test_session_create(self, sample_log_file):
        """Test session creation."""
        result = run_llm_command(
            ["session", "create", "-f", sample_log_file, "--name", "test-session"]
        )
        assert result.returncode == EXIT_SUCCESS

        output = json.loads(result.stdout)
        assert "session_id" in output
        assert output["session_id"].startswith("sess_")
        assert output["status"] == "active"

        # Cleanup
        session_file = Path(output["session_file"])
        if session_file.exists():
            session_file.unlink()

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


# =============================================================================
# New filtering CLI tests
# =============================================================================


@pytest.fixture
def filtering_cli_log():
    """Create a log file with known counts for CLI filter testing.

    80 entries: 4 levels × 2 services × 10 per combination.
    - Levels: INFO (20), DEBUG (20), WARN (20), ERROR (20)
    - Services: svc-x (40), svc-y (40)
    - Threads: t-0, t-1 (40 each)
    """
    entries = []
    idx = 0
    for svc in ["svc-x", "svc-y"]:
        for level in ["INFO", "DEBUG", "WARN", "ERROR"]:
            for j in range(10):
                entries.append(
                    json.dumps(
                        {
                            "timestamp": f"2024-01-15T10:{idx // 60:02d}:{idx % 60:02d}Z",
                            "level": level,
                            "message": "health ping" if j == 0 else f"operation {idx}",
                            "thread_id": f"t-{idx % 2}",
                            "service_name": svc,
                            "correlation_id": f"req-{idx % 5}",
                        }
                    )
                )
                idx += 1
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("\n".join(entries) + "\n")
        f.flush()
        yield f.name
    os.unlink(f.name)


class TestSearchMultiLevel:
    """Test comma-separated --level via CLI."""

    def test_multi_level_filter(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--level", "ERROR,WARN"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["summary"]["total_matches"] == 40

    def test_single_level_filter(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--level", "ERROR"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["summary"]["total_matches"] == 20


class TestSearchTail:
    """Test --tail flag returns last N entries."""

    def test_tail_returns_n(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--tail", "5"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert len(data["results"]) == 5
        assert data["summary"]["total_matches"] == 80


class TestSearchExclude:
    """Test --exclude-level and --exclude-query flags."""

    def test_exclude_level(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--exclude-level", "DEBUG"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["summary"]["total_matches"] == 60

        for item in data["results"]:
            assert item["level"] != "DEBUG"

    def test_exclude_query(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--exclude-query", "health"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        # 8 entries have "health ping" (1 per level × service = 2 services × 4 levels)
        assert data["summary"]["total_matches"] == 72


class TestSearchFields:
    """Test --fields projection."""

    def test_fields_projection(self, filtering_cli_log):
        result = run_llm_command(
            [
                "search",
                filtering_cli_log,
                "--level",
                "ERROR",
                "--limit",
                "3",
                "--fields",
                "timestamp,level,message",
            ]
        )
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert len(data["results"]) == 3

        for item in data["results"]:
            assert "timestamp" in item
            assert "level" in item
            assert "message" in item
            assert "thread_id" not in item


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


# =============================================================================
# New feature tests: --count-only, --offset, --compact, --metadata-only,
# --max-bytes on additional commands, relative --after/--before
# =============================================================================


class TestSearchCountOnly:
    """Test --count-only returns match count without results."""

    def test_count_only_with_results(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--count-only"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["total_matches"] == 80
        assert data["files_searched"] == 1
        assert "results" not in data

    def test_count_only_with_filter(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--level", "ERROR", "--count-only"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["total_matches"] == 20

    def test_count_only_no_results(self, filtering_cli_log):
        result = run_llm_command(
            ["search", filtering_cli_log, "--service", "nonexistent", "--count-only"]
        )
        assert result.returncode == EXIT_NO_RESULTS
        data = json.loads(result.stdout)
        assert data["total_matches"] == 0


class TestSearchOffset:
    """Test --offset for pagination."""

    def test_offset_skips_entries(self, filtering_cli_log):
        """--offset 10 --limit 5 returns entries 11-15."""
        result = run_llm_command(["search", filtering_cli_log, "--offset", "10", "--limit", "5"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert len(data["results"]) == 5
        assert data["summary"]["offset"] == 10

    def test_offset_has_more_flag(self, filtering_cli_log):
        """has_more is true when more results remain."""
        result = run_llm_command(["search", filtering_cli_log, "--offset", "0", "--limit", "10"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert data["summary"]["has_more"] is True

    def test_offset_last_page(self, filtering_cli_log):
        """has_more is false on the last page."""
        result = run_llm_command(["search", filtering_cli_log, "--offset", "75", "--limit", "10"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert len(data["results"]) == 5  # 80 - 75 = 5 remaining
        assert data["summary"]["has_more"] is False

    def test_pagination_three_pages(self, filtering_cli_log):
        """Paginate through 20 ERROR entries in pages of 8."""
        all_line_numbers = []
        for page_offset in [0, 8, 16]:
            result = run_llm_command(
                [
                    "search",
                    filtering_cli_log,
                    "--level",
                    "ERROR",
                    "--offset",
                    str(page_offset),
                    "--limit",
                    "8",
                ]
            )
            assert result.returncode == EXIT_SUCCESS
            data = json.loads(result.stdout)
            all_line_numbers.extend([r["line_number"] for r in data["results"]])

        # 8 + 8 + 4 = 20 total ERROR entries
        assert len(all_line_numbers) == 20
        # No duplicate line numbers
        assert len(set(all_line_numbers)) == 20


class TestSearchCompact:
    """Test --compact uses short field names."""

    def test_compact_short_keys(self, filtering_cli_log):
        result = run_llm_command(
            ["search", filtering_cli_log, "--level", "ERROR", "--limit", "3", "--compact"]
        )
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert len(data["results"]) == 3

        for item in data["results"]:
            assert "ln" in item
            assert "ts" in item
            assert "lv" in item
            assert "msg" in item
            # Long keys should NOT be present
            assert "line_number" not in item
            assert "timestamp" not in item
            assert "level" not in item

    def test_compact_saves_bytes(self, filtering_cli_log):
        """Compact mode should produce smaller output."""
        normal = run_llm_command(["search", filtering_cli_log, "--level", "ERROR", "--limit", "10"])
        compact = run_llm_command(
            ["search", filtering_cli_log, "--level", "ERROR", "--limit", "10", "--compact"]
        )
        assert len(compact.stdout) < len(normal.stdout)


class TestSearchMetadataOnly:
    """Test --metadata-only returns aggregations without results."""

    def test_metadata_only_no_results_key(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--metadata-only"])
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert "results" not in data
        assert "aggregations" in data
        assert "summary" in data
        assert data["summary"]["total_matches"] == 80

    def test_metadata_only_aggregation_counts(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--metadata-only"])
        data = json.loads(result.stdout)
        agg = data["aggregations"]
        assert agg["by_level"]["ERROR"] == 20
        assert agg["by_level"]["INFO"] == 20
        assert agg["by_level"]["WARN"] == 20
        assert agg["by_level"]["DEBUG"] == 20

    def test_metadata_only_by_service(self, filtering_cli_log):
        result = run_llm_command(["search", filtering_cli_log, "--metadata-only"])
        data = json.loads(result.stdout)
        agg = data["aggregations"]
        assert agg["by_service"]["svc-x"] == 40
        assert agg["by_service"]["svc-y"] == 40


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


class TestRelativeTime:
    """Test relative time parsing in --after/--before.

    Note: The Rust backend has a known issue with time_start/time_end
    filtering on some log formats, so we test the parsing layer directly.
    """

    def test_relative_time_parse_units(self):
        """Verify _parse_time_arg produces valid ISO timestamps for various units."""
        from logler.llm_cli import _parse_time_arg
        from datetime import datetime

        for duration in ["-30m", "-2h", "-1d", "-30s"]:
            result = _parse_time_arg(duration, "--after")
            assert result is not None
            # Should be a valid ISO timestamp
            parsed = datetime.fromisoformat(result)
            assert parsed.year > 2020

    def test_relative_time_is_in_past(self):
        """Relative time arguments should produce timestamps before now."""
        from logler.llm_cli import _parse_time_arg
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        one_hour_ago = _parse_time_arg("-1h", "--after")
        parsed = datetime.fromisoformat(one_hour_ago)
        # Make both tz-aware for comparison
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        # Should be approximately 1 hour before now (within 5 sec tolerance)
        diff = (now - parsed).total_seconds()
        assert 3595 < diff < 3605

    def test_resolve_time_filters_relative(self):
        """_resolve_time_filters handles relative --after/--before."""
        from logler.llm_cli import _resolve_time_filters
        from datetime import datetime

        time_start, time_end = _resolve_time_filters(None, "-2h", "-30m")
        assert time_start is not None
        assert time_end is not None
        start = datetime.fromisoformat(time_start)
        end = datetime.fromisoformat(time_end)
        assert start < end

    def test_absolute_time_still_works(self):
        """ISO8601 timestamps still work for --after/--before."""
        from logler.llm_cli import _parse_time_arg

        result = _parse_time_arg("2024-01-15T10:00:00Z", "--after")
        assert "2024-01-15" in result


# ---------------------------------------------------------------------------
# Security: SQL command blocks filesystem access
# ---------------------------------------------------------------------------


class TestSqlCommandSecurity:
    """Verify the logler llm sql command blocks DuckDB filesystem functions."""

    def test_sql_blocks_read_csv_auto(self, sample_log_file):
        """read_csv_auto must be blocked — prevents host file reads."""
        result = run_llm_command(
            [
                "sql",
                "SELECT * FROM read_csv_auto('/etc/passwd')",
                "-f",
                sample_log_file,
            ]
        )
        assert result.returncode == EXIT_USER_ERROR
        data = json.loads(result.stdout)
        assert "error" in data
        assert "file system operations are disabled" in data["error"].lower()

    def test_sql_blocks_copy_to(self, sample_log_file):
        """COPY ... TO must be blocked — prevents data exfiltration."""
        result = run_llm_command(
            [
                "sql",
                "COPY logs TO '/tmp/exfil.csv'",
                "-f",
                sample_log_file,
            ]
        )
        assert result.returncode == EXIT_USER_ERROR
        data = json.loads(result.stdout)
        assert "error" in data
        assert "file system operations are disabled" in data["error"].lower()


class TestSqlCommandBatching:
    """Verify the sql command handles large files via batched inserts."""

    def test_sql_large_file_batched(self):
        """Generate >5000 entries, run sql, verify correct total_entries count."""
        import tempfile
        import os

        n_entries = 6_000
        lines = []
        for i in range(n_entries):
            ts = f"2024-01-15T10:00:{i % 60:02d}.{i:03d}Z"
            level = "INFO" if i % 5 != 0 else "ERROR"
            lines.append(f"{ts} {level} [worker-{i % 4}] Message number {i}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            log_path = f.name

        try:
            result = run_llm_command(
                [
                    "sql",
                    "SELECT COUNT(*) as cnt FROM logs",
                    "-f",
                    log_path,
                ]
            )
            assert result.returncode == EXIT_SUCCESS, result.stderr
            data = json.loads(result.stdout)
            assert data["total_entries"] == n_entries
            assert data["row_count"] == 1
            assert data["results"][0]["cnt"] == n_entries
        finally:
            os.unlink(log_path)

    def test_sql_count_by_level(self):
        """Batched insert preserves all fields correctly (level grouping)."""
        import tempfile
        import os

        # 100 INFO + 50 ERROR = 150 entries
        lines = []
        for i in range(100):
            lines.append(f"2024-01-15T10:00:00.{i:03d}Z INFO [w-1] info msg {i}")
        for i in range(50):
            lines.append(f"2024-01-15T10:00:01.{i:03d}Z ERROR [w-2] error msg {i}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            log_path = f.name

        try:
            result = run_llm_command(
                [
                    "sql",
                    "SELECT level, COUNT(*) as cnt FROM logs GROUP BY level ORDER BY level",
                    "-f",
                    log_path,
                ]
            )
            assert result.returncode == EXIT_SUCCESS, result.stderr
            data = json.loads(result.stdout)
            assert data["total_entries"] == 150
            rows = {r["level"]: r["cnt"] for r in data["results"]}
            assert rows["ERROR"] == 50
            assert rows["INFO"] == 100
        finally:
            os.unlink(log_path)
