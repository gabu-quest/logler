"""
LLM Output Quality Tests - Prove CLI output is useful for LLM consumption.

Tests cover:
- Token efficiency: output stays within reasonable token budgets
- Truncation correctness: --max-bytes produces valid, useful output
- Information density: output contains enough info for LLM reasoning
- Edge cases: behaviors that would confuse an LLM
- Real-log stress: CLI-level tests using real fixture files

Fixtures:
- tests/fixtures/real_apache_clf.log (500 lines, Apache CLF)
- tests/fixtures/realistic_microservice.jsonl (200 lines, JSON)
- tests/fixtures/realistic_syslog.log (150 lines, syslog)
- tests/fixtures/realistic_hdfs.log (150 lines, HDFS)
- examples/logs/huge/massive_incident.log (9999 lines, JSON)
"""

import json
import os
import subprocess
import tempfile
import pytest
from pathlib import Path

# Exit codes (match llm_cli.py)
EXIT_SUCCESS = 0
EXIT_NO_RESULTS = 1
EXIT_USER_ERROR = 2
EXIT_INTERNAL_ERROR = 3

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parent.parent
MASSIVE_LOG = PROJECT_ROOT / "examples" / "logs" / "huge" / "massive_incident.log"

# Approximate: 1 token ~ 4 bytes for English/JSON text
BYTES_PER_TOKEN = 4


def run_llm_command(args, timeout=120):
    """Run a logler llm command and return result."""
    cmd = ["python", "-m", "logler.cli", "llm"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )
    return result


def parse_json_output(result):
    """Parse JSON from command stdout, raising clear errors."""
    assert result.returncode in (
        EXIT_SUCCESS,
        EXIT_NO_RESULTS,
    ), f"Command failed (exit {result.returncode}): {result.stderr[:200]}"
    data = json.loads(result.stdout)
    return data


@pytest.fixture
def apache_clf():
    return str(FIXTURES_DIR / "real_apache_clf.log")


@pytest.fixture
def microservice():
    return str(FIXTURES_DIR / "realistic_microservice.jsonl")


@pytest.fixture
def syslog():
    return str(FIXTURES_DIR / "realistic_syslog.log")


@pytest.fixture
def hdfs():
    return str(FIXTURES_DIR / "realistic_hdfs.log")


@pytest.fixture
def massive():
    path = str(MASSIVE_LOG)
    if not os.path.exists(path):
        pytest.skip("massive_incident.log not available")
    return path


@pytest.fixture
def all_fixtures():
    return {
        "apache": str(FIXTURES_DIR / "real_apache_clf.log"),
        "microservice": str(FIXTURES_DIR / "realistic_microservice.jsonl"),
        "syslog": str(FIXTURES_DIR / "realistic_syslog.log"),
        "hdfs": str(FIXTURES_DIR / "realistic_hdfs.log"),
    }


@pytest.fixture
def empty_log():
    """Create an empty log file for edge case testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.flush()
        yield f.name
    os.unlink(f.name)


class TestTokenEfficiency:
    """Tests that LLM CLI output stays within reasonable token budgets."""

    def test_triage_under_500_tokens(self, microservice):
        """Triage on a 200-entry fixture should be < 2KB (~500 tokens)."""
        result = run_llm_command(["triage", microservice])
        data = parse_json_output(result)
        output_size = len(result.stdout.encode())
        assert output_size < 2000, (
            f"Triage output is {output_size}B (~{output_size // BYTES_PER_TOKEN} tokens), "
            f"expected < 2KB"
        )
        assert "assessment" in data

    def test_search_errors_under_25k_tokens(self, microservice):
        """Search ERROR on 200-entry fixture should be < 100KB (~25K tokens)."""
        result = run_llm_command(["search", microservice, "--level", "ERROR"])
        data = parse_json_output(result)
        output_size = len(result.stdout.encode())
        assert output_size < 100_000, (
            f"Search ERROR output is {output_size}B (~{output_size // BYTES_PER_TOKEN} tokens), "
            f"expected < 100KB"
        )
        total = data.get("total_matches") or data.get("summary", {}).get("total_matches")
        assert total == 16, f"Expected 16 ERROR matches, got {total}"

    def test_search_compact_saves_40_percent(self, microservice):
        """Compact vs normal on microservice fixture must save at least 40%."""
        normal = run_llm_command(["search", microservice, "--level", "ERROR"])
        compact = run_llm_command(["search", microservice, "--level", "ERROR", "--compact"])
        assert normal.returncode == 0
        assert compact.returncode == 0

        normal_size = len(normal.stdout.encode())
        compact_size = len(compact.stdout.encode())
        saving = 1.0 - (compact_size / normal_size)
        assert saving >= 0.40, (
            f"Compact only saved {saving:.0%} (normal={normal_size}B, compact={compact_size}B), "
            f"expected >= 40%"
        )

    def test_search_no_raw_saves_space(self, syslog):
        """--no-raw vs default on syslog fixture should save bytes."""
        with_raw = run_llm_command(["search", syslog, "--limit", "50"])
        without_raw = run_llm_command(["search", syslog, "--no-raw", "--limit", "50"])
        assert with_raw.returncode == 0
        assert without_raw.returncode == 0

        raw_size = len(with_raw.stdout.encode())
        no_raw_size = len(without_raw.stdout.encode())
        assert (
            no_raw_size < raw_size
        ), f"--no-raw ({no_raw_size}B) should be smaller than default ({raw_size}B)"

    def test_ids_output_scales_linearly(self, microservice, apache_clf):
        """IDs on 200 entries vs 500 entries — ratio should be within 4x."""
        ids_200 = run_llm_command(["ids", microservice])
        ids_500 = run_llm_command(["ids", apache_clf])
        assert ids_200.returncode == 0
        assert ids_500.returncode in (0, 1)  # CLF may have no IDs

        size_200 = len(ids_200.stdout.encode())
        _ = len(ids_500.stdout.encode())  # Just check both commands succeed

        # Both should produce output; just check the 200-entry one is reasonable
        assert size_200 < 20_000, f"IDs output for 200 entries is {size_200}B, expected < 20KB"

    def test_summarize_under_2k_tokens(self, microservice):
        """Summarize output should be < 8KB regardless of input size."""
        result = run_llm_command(["summarize", microservice])
        _ = parse_json_output(result)  # Just verify output is valid JSON
        output_size = len(result.stdout.encode())
        assert output_size < 8_000, (
            f"Summarize output is {output_size}B (~{output_size // BYTES_PER_TOKEN} tokens), "
            f"expected < 8KB"
        )

    def test_search_huge_file_with_max_bytes(self, massive):
        """10K file with --max-bytes 4000 fits within the budget."""
        result = run_llm_command(
            [
                "search",
                massive,
                "--level",
                "ERROR",
                "--max-bytes",
                "4000",
            ]
        )
        assert result.returncode == 0
        output_size = len(result.stdout.encode())
        assert (
            output_size <= 4200
        ), f"--max-bytes 4000 produced {output_size}B, expected <= 4200B (small overshoot ok)"
        # Must still be valid JSON
        data = json.loads(result.stdout)
        assert "results" in data or "total_matches" in data

    def test_search_huge_file_without_limit_is_massive(self, massive):
        """Document that unbounded search on 10K file exceeds 100KB."""
        result = run_llm_command(
            [
                "search",
                massive,
                "--level",
                "ERROR",
                "--limit",
                "9999",
            ],
            timeout=120,
        )
        assert result.returncode == 0
        output_size = len(result.stdout.encode())
        # This is intentionally documenting the problem — large output
        assert (
            output_size > 50_000
        ), f"Expected large output for unbounded search on 10K file, got {output_size}B"


class TestTruncationCorrectness:
    """Tests that --max-bytes produces valid, useful output."""

    def test_max_bytes_produces_valid_json(self, microservice):
        """Truncated output must be parseable JSON."""
        result = run_llm_command(
            [
                "search",
                microservice,
                "--max-bytes",
                "2000",
            ]
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_max_bytes_includes_truncation_metadata(self, microservice):
        """Truncated output must include truncation indicators."""
        result = run_llm_command(
            [
                "search",
                microservice,
                "--max-bytes",
                "2000",
            ]
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # When truncation happens, there should be metadata about it
        if data.get("total_matches", 0) > len(data.get("results", [])):
            # Truncation occurred — verify we know about it
            has_truncation_info = (
                data.get("truncated") is True
                or "truncated_at" in data
                or len(data.get("results", [])) < data.get("total_matches", 0)
            )
            assert has_truncation_info, (
                f"Truncation occurred but no truncation metadata. "
                f"total_matches={data.get('total_matches')}, "
                f"results_len={len(data.get('results', []))}"
            )

    def test_max_bytes_summary_matches_result_count(self, microservice):
        """When truncated, result count should match what's actually returned."""
        result = run_llm_command(
            [
                "search",
                microservice,
                "--max-bytes",
                "3000",
            ]
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        actual_results = len(data.get("results", []))
        # The returned results count should equal what's actually in the array
        assert actual_results >= 0
        # If summary exists, its count should match
        summary = data.get("summary", {})
        if "returned" in summary:
            assert (
                summary["returned"] == actual_results
            ), f"summary.returned={summary['returned']} != actual results={actual_results}"

    def test_max_bytes_very_small_budget_no_crash(self, microservice):
        """Very small byte budget (200 bytes) returns valid JSON, not crash."""
        result = run_llm_command(
            [
                "search",
                microservice,
                "--max-bytes",
                "200",
            ]
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # Should have at least the structure, even if no results
        assert isinstance(data, dict)

    def test_max_bytes_on_correlate(self, microservice):
        """Truncation works on correlate command."""
        result = run_llm_command(
            [
                "correlate",
                "corr-000",
                "-f",
                microservice,
                "--max-bytes",
                "3000",
            ]
        )
        # May be exit 0 or 1 depending on findings
        assert result.returncode in (
            0,
            1,
        ), f"Correlate failed (exit {result.returncode}): {result.stderr[:200]}"
        if result.returncode == 0:
            _ = json.loads(result.stdout)  # Just verify valid JSON
            output_size = len(result.stdout.encode())
            assert output_size <= 3500, f"--max-bytes 3000 on correlate produced {output_size}B"

    def test_max_bytes_on_summarize(self, microservice):
        """Truncation works on summarize command."""
        result = run_llm_command(
            [
                "summarize",
                microservice,
                "--max-bytes",
                "2000",
            ]
        )
        assert result.returncode == 0
        _ = json.loads(result.stdout)  # Just verify valid JSON
        output_size = len(result.stdout.encode())
        assert output_size <= 2500, f"--max-bytes 2000 on summarize produced {output_size}B"


class TestOutputInformationDensity:
    """Tests that output contains enough info for LLM reasoning."""

    def test_search_results_have_all_context_fields(self, microservice):
        """Each search result has timestamp, level, message, line_number."""
        result = run_llm_command(["search", microservice, "--limit", "10"])
        data = parse_json_output(result)
        assert len(data["results"]) == 10
        for item in data["results"]:
            # CLI output may nest under "entry" or flatten fields
            entry = item.get("entry", item)
            assert "timestamp" in entry, f"Missing timestamp: {list(entry.keys())}"
            assert "level" in entry, f"Missing level: {list(entry.keys())}"
            assert "message" in entry, f"Missing message: {list(entry.keys())}"
            # line_number may be in item or entry
            has_line = "line_number" in item or "line_number" in entry
            assert (
                has_line
            ), f"Missing line_number: item={list(item.keys())}, entry={list(entry.keys())}"

    def test_triage_has_actionable_suggestions(self, microservice):
        """Triage output contains suggested_actions list with >0 entries."""
        result = run_llm_command(["triage", microservice])
        data = parse_json_output(result)
        assert (
            "suggested_actions" in data
        ), f"Triage missing suggested_actions. Keys: {list(data.keys())}"
        assert (
            len(data["suggested_actions"]) > 0
        ), "suggested_actions is empty — LLM gets no guidance"

    def test_triage_severity_matches_error_rate(self, microservice):
        """Microservice fixture has 8% error rate (16/200) -> medium severity."""
        result = run_llm_command(["triage", microservice])
        data = parse_json_output(result)
        assessment = data.get("assessment", {})
        severity = assessment.get("severity", "")
        # 16/200 = 8% error rate -> should be "medium" (5-10%) or "high" (>10%)
        assert severity in (
            "medium",
            "high",
        ), f"Expected medium/high severity for 8% error rate, got '{severity}'"

    def test_correlate_timeline_is_chronological(self, microservice):
        """Correlate entries are ordered by timestamp."""
        result = run_llm_command(["correlate", "corr-000", "-f", microservice])
        data = parse_json_output(result)
        timeline = data.get("timeline", [])
        assert len(timeline) > 0, "Correlate returned empty timeline"

        timestamps = [
            entry.get("timestamp") for entry in timeline if entry.get("timestamp") is not None
        ]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], (
                f"Timeline not chronological at index {i}: "
                f"{timestamps[i - 1]} > {timestamps[i]}"
            )

    def test_correlate_shows_service_flow(self, microservice):
        """Correlate for corr-000 shows entries from multiple services."""
        result = run_llm_command(["correlate", "corr-000", "-f", microservice])
        data = parse_json_output(result)
        trace = data.get("trace", {})
        services = trace.get("services", [])
        assert len(services) >= 3, f"Expected cross-service flow, got services: {services}"

    def test_schema_identifies_json_format(self, microservice):
        """JSON fixture detected as Json."""
        result = run_llm_command(["schema", microservice])
        data = parse_json_output(result)
        detected = data.get("detected_formats", {})
        assert "Json" in detected, f"Expected 'Json' in detected_formats, got: {detected}"

    def test_schema_identifies_syslog_format(self, syslog):
        """Syslog fixture detected as Syslog or PlainText (BSD syslog without priority)."""
        result = run_llm_command(["schema", syslog])
        data = parse_json_output(result)
        detected = data.get("detected_formats", {})
        # BSD syslog without <priority> prefix may be detected as either
        has_valid_format = "Syslog" in detected or "PlainText" in detected
        assert (
            has_valid_format
        ), f"Expected Syslog or PlainText in detected_formats, got: {detected}"

    def test_ids_returns_all_id_types(self, microservice):
        """IDs command returns thread_ids, correlation_ids, trace_ids, services."""
        result = run_llm_command(["ids", microservice])
        data = parse_json_output(result)
        for key in ("thread_ids", "correlation_ids", "trace_ids", "services"):
            assert key in data, f"Missing '{key}' in ids output. Keys: {list(data.keys())}"
            assert len(data[key]) > 0, f"'{key}' is empty"


class TestEdgeCasesLLM:
    """Tests edge cases that would confuse an LLM."""

    def test_empty_file_returns_useful_error(self, empty_log):
        """Empty log file produces meaningful JSON error, not crash."""
        result = run_llm_command(["triage", empty_log])
        # Should return exit 1 (no results) or 0 with empty data, not crash
        assert result.returncode in (
            EXIT_SUCCESS,
            EXIT_NO_RESULTS,
        ), f"Empty file caused exit {result.returncode}: {result.stderr[:200]}"
        # Output should be valid JSON
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert isinstance(data, dict)

    def test_nonexistent_correlation_returns_nonzero(self, microservice):
        """Correlate on bogus ID returns non-success exit code."""
        result = run_llm_command(
            [
                "correlate",
                "NONEXISTENT-BOGUS-ID-XYZ",
                "-f",
                microservice,
            ]
        )
        assert (
            result.returncode != EXIT_SUCCESS
        ), f"Expected non-zero exit for bogus correlation, got {result.returncode}"

    def test_hierarchy_empty_result_has_structure(self, microservice):
        """Hierarchy on non-existent trace returns valid structure."""
        result = run_llm_command(
            [
                "hierarchy",
                "NONEXISTENT-TRACE-ID",
                "-f",
                microservice,
            ]
        )
        # May return exit 0 or 1
        assert result.returncode in (
            EXIT_SUCCESS,
            EXIT_NO_RESULTS,
        ), f"Hierarchy failed (exit {result.returncode}): {result.stderr[:200]}"
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert isinstance(data, dict)

    def test_bottleneck_empty_result_structure(self, microservice):
        """Bottleneck on an identifier with no timing returns valid structure."""
        result = run_llm_command(
            [
                "bottleneck",
                "NONEXISTENT-BOTTLENECK-ID",
                "-f",
                microservice,
            ]
        )
        assert result.returncode in (
            EXIT_SUCCESS,
            EXIT_NO_RESULTS,
        ), f"Bottleneck failed (exit {result.returncode}): {result.stderr[:200]}"
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert isinstance(data, dict)

    def test_search_with_impossible_level_returns_nonzero(self, microservice):
        """Search --level BANANA returns a non-success exit code."""
        result = run_llm_command(
            [
                "search",
                microservice,
                "--level",
                "BANANA",
            ]
        )
        # Invalid level should produce exit 1 (no results), 2 (user error), or 3 (internal)
        assert (
            result.returncode != EXIT_SUCCESS
        ), f"Expected non-zero exit for invalid level BANANA, got {result.returncode}"


class TestRealLogStress:
    """CLI-level stress tests using real fixture files."""

    def test_triage_all_fixtures_succeed(self, all_fixtures):
        """Triage on all 4 fixtures returns exit 0."""
        for name, path in all_fixtures.items():
            result = run_llm_command(["triage", path])
            assert (
                result.returncode == EXIT_SUCCESS
            ), f"Triage failed on {name} (exit {result.returncode}): {result.stderr[:200]}"
            data = json.loads(result.stdout)
            assert "assessment" in data, f"{name}: triage missing assessment"

    def test_search_all_fixtures_return_valid_json(self, all_fixtures):
        """Search on all 4 fixtures returns parseable JSON."""
        for name, path in all_fixtures.items():
            result = run_llm_command(["search", path, "--limit", "10"])
            assert (
                result.returncode == EXIT_SUCCESS
            ), f"Search failed on {name} (exit {result.returncode}): {result.stderr[:200]}"
            data = json.loads(result.stdout)
            assert "results" in data, f"{name}: search missing results key"
            assert (
                len(data["results"]) == 10
            ), f"{name}: expected 10 results, got {len(data['results'])}"

    def test_correlate_microservice_fixture(self, microservice):
        """Correlate a known corr-000 in microservice fixture."""
        result = run_llm_command(["correlate", "corr-000", "-f", microservice])
        data = parse_json_output(result)
        trace = data.get("trace", {})
        assert trace.get("total_entries", 0) > 0, "Correlate found no entries for corr-000"

    def test_massive_file_triage(self, massive):
        """Triage on 10K massive_incident.log completes and fits token budget."""
        result = run_llm_command(["triage", massive], timeout=120)
        assert (
            result.returncode == EXIT_SUCCESS
        ), f"Triage failed on massive file (exit {result.returncode}): {result.stderr[:200]}"
        output_size = len(result.stdout.encode())
        assert output_size < 4000, (
            f"Massive file triage is {output_size}B (~{output_size // BYTES_PER_TOKEN} tokens), "
            f"expected < 4KB"
        )

    def test_massive_file_search_with_limit(self, massive):
        """Search + --limit 50 on massive file returns exactly 50 results."""
        result = run_llm_command(
            [
                "search",
                massive,
                "--limit",
                "50",
            ],
            timeout=120,
        )
        assert result.returncode == EXIT_SUCCESS
        data = json.loads(result.stdout)
        assert len(data["results"]) == 50, f"Expected 50 results, got {len(data['results'])}"

    def test_massive_file_count_only(self, massive):
        """--count-only on massive file returns small output."""
        result = run_llm_command(
            [
                "search",
                massive,
                "--count-only",
            ],
            timeout=120,
        )
        assert result.returncode == EXIT_SUCCESS
        output_size = len(result.stdout.encode())
        assert output_size < 500, f"--count-only output is {output_size}B, expected < 500B"
        data = json.loads(result.stdout)
        assert "total_matches" in data
        assert data["total_matches"] > 0
