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
        assert "files_analyzed" in output
        assert "total_entries" in output
        assert "schema" in output
        assert output["total_entries"] > 0

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
            entry = item.get("entry", item)
            assert entry["level"] != "DEBUG"

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
            entry = item.get("entry", item)
            assert "timestamp" in entry
            assert "level" in entry
            assert "message" in entry
            assert "thread_id" not in entry


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
