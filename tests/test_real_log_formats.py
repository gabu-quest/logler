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

import pytest
from pathlib import Path

try:
    from logler.investigate import search, extract_ids, RUST_AVAILABLE
except ImportError:
    RUST_AVAILABLE = False

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
        assert result["total_matches"] > 0
        for item in result["results"]:
            assert item["entry"]["level"] == "ERROR"


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
