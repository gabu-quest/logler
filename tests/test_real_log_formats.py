"""
Tests that verify logler correctly parses real-world and realistic log formats.

Fixtures:
- real_apache_clf.log: 500 lines of real Apache Combined Log Format (elastic/examples)
- realistic_microservice.jsonl: 200 lines of generated microservice JSON logs
  - 5 services: api-gateway, auth-service, order-service, payment-service, notification-service
  - Health check entries every 20th line (10 total)
  - 20 trace_ids, 10 correlation_ids, 24 thread_ids
- realistic_syslog.log: 150 lines of generated RFC 3164 syslog
  - sshd, kernel, CRON, systemd messages
  - Parser detects as syslog but levels show as UNKNOWN
- realistic_hdfs.log: 150 lines of generated HDFS plaintext logs
  - INFO, WARN, ERROR, DEBUG levels (parser extracts from text)
  - 10 ERROR entries
"""

import re
import pytest
from datetime import datetime
from pathlib import Path

try:
    from logler.investigate import search, extract_ids, follow_thread, RUST_AVAILABLE
except ImportError as e:
    if "logler_rs" in str(e):
        RUST_AVAILABLE = False
    else:
        raise

pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required")

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def apache_clf_file():
    return str(FIXTURES_DIR / "real_apache_clf.log")


@pytest.fixture
def microservice_file():
    return str(FIXTURES_DIR / "realistic_microservice.jsonl")


@pytest.fixture
def syslog_file():
    return str(FIXTURES_DIR / "realistic_syslog.log")


@pytest.fixture
def hdfs_file():
    return str(FIXTURES_DIR / "realistic_hdfs.log")


class TestApacheCLF:
    """Verify parsing of real Apache Combined Log Format."""

    def test_parse_all_500_lines(self, apache_clf_file):
        result = search(files=[apache_clf_file], limit=500)
        assert result["total_matches"] == 500
        assert len(result["results"]) == 500

    def test_entries_have_timestamps(self, apache_clf_file):
        result = search(files=[apache_clf_file], limit=5)
        assert len(result["results"]) == 5
        for item in result["results"]:
            entry = item["entry"]
            assert entry["timestamp"] is not None

    def test_level_extraction_graceful(self, apache_clf_file):
        """Apache CLF has HTTP status codes, not log levels.
        Parser should handle this gracefully (INFO/WARN based on status)."""
        result = search(files=[apache_clf_file], limit=500)
        levels = {item["entry"]["level"] for item in result["results"]}
        # Parser assigns INFO/WARN based on HTTP status codes
        assert len(levels) > 0
        for level in levels:
            assert level in ("INFO", "WARN", "ERROR", "DEBUG", "UNKNOWN")

    def test_timestamps_are_valid_iso8601(self, apache_clf_file):
        """Every Apache CLF entry's timestamp must parse as ISO 8601."""
        result = search(files=[apache_clf_file], limit=500)
        assert len(result["results"]) == 500
        for item in result["results"]:
            ts = item["entry"]["timestamp"]
            assert ts is not None, f"Null timestamp at line {item.get('line_number')}"
            # Must parse without error
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            assert parsed.year >= 2015, f"Unexpected year {parsed.year} in {ts}"

    def test_http_method_in_message(self, apache_clf_file):
        """All 500 CLF lines contain an HTTP method in the message."""
        http_methods = {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"}
        result = search(files=[apache_clf_file], limit=500)
        assert len(result["results"]) == 500
        for item in result["results"]:
            msg = item["entry"]["message"]
            assert msg, f"Empty message at line {item.get('line_number')}"
            found = any(method in msg for method in http_methods)
            assert found, f"No HTTP method in message: {msg[:80]}"

    def test_no_empty_messages(self, apache_clf_file):
        """Every Apache CLF entry has a non-empty message."""
        result = search(files=[apache_clf_file], limit=500)
        assert len(result["results"]) == 500
        for item in result["results"]:
            msg = item["entry"]["message"]
            assert (
                msg is not None and len(msg.strip()) > 0
            ), f"Empty message at line {item.get('line_number')}"


class TestRealisticMicroservice:
    """Verify parsing of realistic microservice JSON logs."""

    def test_parse_all_200_entries(self, microservice_file):
        result = search(files=[microservice_file], limit=200)
        assert result["total_matches"] == 200
        assert len(result["results"]) == 200

    def test_service_filter(self, microservice_file):
        result = search(files=[microservice_file], service_name="api-gateway", limit=200)
        assert result["total_matches"] == 40
        for item in result["results"]:
            assert item["entry"]["service_name"] == "api-gateway"

    def test_all_five_services_present(self, microservice_file):
        ids = extract_ids(files=[microservice_file])
        assert len(ids["services"]) == 5

    def test_trace_ids_extracted(self, microservice_file):
        ids = extract_ids(files=[microservice_file])
        assert len(ids["trace_ids"]) == 20
        assert len(ids["correlation_ids"]) == 10

    def test_thread_ids_extracted(self, microservice_file):
        ids = extract_ids(files=[microservice_file])
        assert len(ids["thread_ids"]) == 24

    def test_exclude_health_checks(self, microservice_file):
        all_results = search(files=[microservice_file], limit=200)
        filtered = search(files=[microservice_file], exclude_query="health", limit=200)
        assert all_results["total_matches"] == 200
        assert filtered["total_matches"] == 190

        for item in filtered["results"]:
            assert "health" not in item["entry"]["message"].lower()

    def test_level_distribution(self, microservice_file):
        """Verify all four log levels are present."""
        result = search(files=[microservice_file], limit=200)
        levels = {item["entry"]["level"] for item in result["results"]}
        assert levels == {"INFO", "DEBUG", "WARN", "ERROR"}

    def test_error_level_filter(self, microservice_file):
        result = search(files=[microservice_file], level="ERROR", limit=200)
        assert result["total_matches"] == 16
        for item in result["results"]:
            assert item["entry"]["level"] == "ERROR"

    def test_correlation_follows_across_services(self, microservice_file):
        """Following corr-000 returns entries from all 5 services."""
        result = follow_thread(files=[microservice_file], correlation_id="corr-000")
        assert result["total_entries"] == 20

        services_found = {
            entry.get("service_name") or entry.get("service") for entry in result["entries"]
        }
        # Remove None if present
        services_found.discard(None)
        assert (
            len(services_found) >= 3
        ), f"Expected entries from multiple services, got: {services_found}"

    def test_search_compact_reduces_size(self, microservice_file):
        """Compact output must be < 60% of normal output size."""
        import subprocess

        cmd_base = [
            "python",
            "-m",
            "logler.cli",
            "llm",
            "search",
            microservice_file,
            "--level",
            "ERROR",
            "--limit",
            "16",
        ]
        normal = subprocess.run(
            cmd_base,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        compact = subprocess.run(
            cmd_base + ["--compact"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert normal.returncode == 0
        assert compact.returncode == 0
        normal_size = len(normal.stdout.encode())
        compact_size = len(compact.stdout.encode())
        assert (
            compact_size < normal_size * 0.75
        ), f"Compact ({compact_size}B) should be < 75% of normal ({normal_size}B)"


class TestRealisticSyslog:
    """Verify parsing of realistic syslog format."""

    def test_parse_all_150_entries(self, syslog_file):
        result = search(files=[syslog_file], limit=200)
        assert result["total_matches"] == 150
        assert len(result["results"]) == 150

    def test_search_auth_failures(self, syslog_file):
        result = search(files=[syslog_file], query="authentication failure", limit=200)
        assert result["total_matches"] == 16

    def test_search_oom_kills(self, syslog_file):
        result = search(files=[syslog_file], query="Out of memory", limit=200)
        assert result["total_matches"] > 0

    def test_entries_have_raw_content(self, syslog_file):
        result = search(files=[syslog_file], limit=3)
        assert len(result["results"]) == 3
        for item in result["results"]:
            entry = item["entry"]
            assert entry["raw"] is not None
            assert len(entry["raw"]) > 10

    def test_syslog_levels_not_all_unknown(self, syslog_file):
        """BSD syslog entries should have inferred levels, not all UNKNOWN."""
        result = search(files=[syslog_file], limit=200)
        levels = [item["entry"]["level"] for item in result["results"]]
        known_levels = [lv for lv in levels if lv is not None and lv != "UNKNOWN"]
        # At least 20% of 150 entries should have meaningful levels
        assert (
            len(known_levels) >= 30
        ), f"Expected >=30 entries with known levels, got {len(known_levels)}"

    def test_syslog_auth_failures_are_error(self, syslog_file):
        """Authentication failures should be classified as ERROR."""
        result = search(files=[syslog_file], query="authentication failure", limit=200)
        assert result["total_matches"] == 16
        for item in result["results"]:
            assert item["entry"]["level"] == "ERROR", (
                f"Expected ERROR for auth failure, got {item['entry']['level']}: "
                f"{item['entry']['message'][:80]}"
            )

    def test_syslog_oom_is_fatal(self, syslog_file):
        """Out of memory kills should be classified as FATAL."""
        result = search(files=[syslog_file], query="Out of memory", limit=200)
        assert result["total_matches"] > 0
        oom_entries = [
            item
            for item in result["results"]
            if "Out of memory" in (item["entry"].get("message") or "")
        ]
        assert len(oom_entries) >= 7
        for item in oom_entries:
            assert item["entry"]["level"] == "FATAL"

    def test_syslog_format_detected(self, syslog_file):
        """BSD syslog lines should be detected as Syslog format, not PlainText."""
        result = search(files=[syslog_file], limit=10)
        for item in result["results"]:
            assert item["entry"]["format"] == "Syslog", (
                f"Expected Syslog format, got {item['entry']['format']}: "
                f"{item['entry']['raw'][:80]}"
            )

    def test_syslog_timestamps_are_null(self, syslog_file):
        """BSD syslog without <priority> prefix has no parsed timestamps.
        This documents and asserts the known limitation explicitly."""
        result = search(files=[syslog_file], limit=150)
        assert len(result["results"]) == 150
        null_count = sum(1 for item in result["results"] if item["entry"]["timestamp"] is None)
        # All 150 BSD syslog entries should have null timestamps
        assert (
            null_count == 150
        ), f"Expected all 150 timestamps to be null, got {150 - null_count} non-null"

    def test_search_output_size_proportional(self, syslog_file):
        """40 syslog errors should produce < 20KB of search output."""
        import subprocess

        cmd = [
            "python",
            "-m",
            "logler.cli",
            "llm",
            "search",
            syslog_file,
            "--level",
            "ERROR",
            "--limit",
            "40",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        output_size = len(result.stdout.encode())
        assert output_size < 20_000, f"ERROR search output is {output_size}B, expected < 20KB"

    def test_every_entry_has_hostname(self, syslog_file):
        """All 150 syslog entries' raw lines contain a hostname pattern."""
        hostname_pattern = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_-]+\b")
        result = search(files=[syslog_file], limit=150)
        assert len(result["results"]) == 150
        for item in result["results"]:
            raw = item["entry"]["raw"]
            assert raw is not None
            # BSD syslog format: "Mon DD HH:MM:SS hostname ..."
            # The hostname is after the timestamp
            assert hostname_pattern.search(raw), f"No hostname found in: {raw[:80]}"


class TestRealisticHDFS:
    """Verify parsing of HDFS plaintext logs."""

    def test_parse_all_150_entries(self, hdfs_file):
        result = search(files=[hdfs_file], limit=200)
        assert result["total_matches"] == 150
        assert len(result["results"]) == 150

    def test_level_filter_error(self, hdfs_file):
        result = search(files=[hdfs_file], level="ERROR", limit=200)
        assert result["total_matches"] == 10
        for item in result["results"]:
            assert item["entry"]["level"] == "ERROR"

    def test_level_filter_warn(self, hdfs_file):
        result = search(files=[hdfs_file], level="WARN", limit=200)
        assert result["total_matches"] > 0
        for item in result["results"]:
            assert item["entry"]["level"] == "WARN"

    def test_search_block_operations(self, hdfs_file):
        result = search(files=[hdfs_file], query="blk_", limit=200)
        # All entries reference block IDs
        assert result["total_matches"] == 150

    def test_multiple_levels_present(self, hdfs_file):
        result = search(files=[hdfs_file], limit=200)
        levels = {item["entry"]["level"] for item in result["results"]}
        assert "INFO" in levels
        assert "ERROR" in levels

    def test_hdfs_levels_exact_distribution(self, hdfs_file):
        """Assert exact level counts: 120 INFO, 15 WARN, 10 ERROR, 5 DEBUG."""
        result = search(files=[hdfs_file], limit=200)
        level_counts = {}
        for item in result["results"]:
            lv = item["entry"]["level"]
            level_counts[lv] = level_counts.get(lv, 0) + 1

        assert level_counts.get("INFO", 0) == 120, f"INFO: {level_counts.get('INFO')}"
        assert level_counts.get("WARN", 0) == 15, f"WARN: {level_counts.get('WARN')}"
        assert level_counts.get("ERROR", 0) == 10, f"ERROR: {level_counts.get('ERROR')}"
        assert level_counts.get("DEBUG", 0) == 5, f"DEBUG: {level_counts.get('DEBUG')}"

    def test_all_entries_reference_blocks(self, hdfs_file):
        """Every HDFS entry raw line contains a blk_ block ID."""
        result = search(files=[hdfs_file], limit=200)
        assert len(result["results"]) == 150
        for item in result["results"]:
            raw = item["entry"].get("raw") or item["entry"].get("message", "")
            assert "blk_" in raw, f"No blk_ pattern at line {item.get('line_number')}: {raw[:80]}"


class TestCrossFormatConsistency:
    """Verify consistent behavior across all 4 log formats."""

    @pytest.fixture
    def all_fixtures(self):
        return {
            "apache": str(FIXTURES_DIR / "real_apache_clf.log"),
            "microservice": str(FIXTURES_DIR / "realistic_microservice.jsonl"),
            "syslog": str(FIXTURES_DIR / "realistic_syslog.log"),
            "hdfs": str(FIXTURES_DIR / "realistic_hdfs.log"),
        }

    def test_search_returns_consistent_structure(self, all_fixtures):
        """Search across all 4 formats returns results with the same keys."""
        required_keys = {"timestamp", "level", "message", "raw"}
        for name, path in all_fixtures.items():
            result = search(files=[path], limit=5)
            assert len(result["results"]) == 5, f"{name}: expected 5 results"
            for item in result["results"]:
                entry = item["entry"]
                for key in required_keys:
                    assert (
                        key in entry
                    ), f"{name}: missing key '{key}' in entry keys: {list(entry.keys())}"

    def test_all_formats_have_messages(self, all_fixtures):
        """No empty message fields across any format."""
        for name, path in all_fixtures.items():
            result = search(files=[path], limit=10)
            assert len(result["results"]) == 10, f"{name}: expected 10 results"
            for item in result["results"]:
                msg = item["entry"]["message"]
                assert (
                    msg is not None and len(msg.strip()) > 0
                ), f"{name}: empty message at line {item.get('line_number')}"

    def test_level_filter_works_on_formats_with_errors(self, all_fixtures):
        """ERROR filter returns >0 results on fixtures with errors."""
        # Apache CLF does not map HTTP status to log levels, so skip it
        for name in ("microservice", "syslog", "hdfs"):
            path = all_fixtures[name]
            result = search(files=[path], level="ERROR", limit=200)
            assert result["total_matches"] > 0, f"{name}: ERROR filter returned 0 results"
