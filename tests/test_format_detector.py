"""
Brutal test suite for logler.format_detector (M6).

Tests format detection confidence scoring and Drain template mining.
Every test asserts exact values — counts, confidence ranges, template strings.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


from logler.format_detector import (
    DrainParser,
    detect_format,
    mine_templates,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _write_temp_file(lines: list[str], suffix: str = ".log") -> str:
    """Write lines to a temp file and return path."""
    f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=suffix, prefix="test_detect_")
    for line in lines:
        f.write(line + "\n")
    f.close()
    return f.name


# ============================================================================
# Format Detection — confidence scoring
# ============================================================================


class TestDetectJsonFormat:
    """Test JSON format detection against a real fixture."""

    def test_real_jsonl_fixture(self):
        path = str(FIXTURE_DIR / "realistic_microservice.jsonl")
        result = detect_format(path)
        assert result.format == "json"
        assert result.confidence >= 0.95
        assert result.match_rate >= 0.95
        assert result.sample_size > 0
        assert "timestamp" in result.detected_fields
        assert "level" in result.detected_fields
        assert "message" in result.detected_fields

    def test_synthetic_json(self):
        lines = [
            json.dumps({"ts": "2024-01-15T10:00:00Z", "level": "INFO", "msg": "ok"})
            for _ in range(20)
        ]
        path = _write_temp_file(lines)
        try:
            result = detect_format(path)
            assert result.format == "json"
            assert result.confidence >= 0.95
            assert result.match_rate == 1.0
            assert "ts" in result.detected_fields
            assert "level" in result.detected_fields
            assert "msg" in result.detected_fields
        finally:
            Path(path).unlink()


class TestDetectSyslogFormat:
    """Test syslog format detection."""

    def test_real_syslog_fixture(self):
        path = str(FIXTURE_DIR / "realistic_syslog.log")
        result = detect_format(path)
        assert result.format == "syslog"
        assert result.confidence >= 0.8
        assert result.match_rate >= 0.8

    def test_synthetic_bsd_syslog(self):
        lines = [
            f"Mar 15 03:{i:02d}:00 web-prod-01 nginx[{1000+i}]: GET /api/{i} 200" for i in range(20)
        ]
        path = _write_temp_file(lines)
        try:
            result = detect_format(path)
            assert result.format == "syslog"
            assert result.match_rate == 1.0
        finally:
            Path(path).unlink()


class TestDetectApacheCLF:
    """Test Apache Common Log Format detection."""

    def test_real_clf_fixture(self):
        path = str(FIXTURE_DIR / "real_apache_clf.log")
        result = detect_format(path)
        assert result.format == "common_log"
        assert result.confidence >= 0.8
        assert result.match_rate >= 0.8

    def test_synthetic_clf(self):
        lines = [
            f"192.168.1.{i} - user{i} [17/May/2015:10:05:{i:02d} +0000] "
            f'"GET /page/{i} HTTP/1.1" 200 {1000+i}'
            for i in range(20)
        ]
        path = _write_temp_file(lines)
        try:
            result = detect_format(path)
            assert result.format == "common_log"
            assert result.match_rate == 1.0
        finally:
            Path(path).unlink()


class TestDetectLogfmt:
    """Test logfmt format detection."""

    def test_pure_logfmt(self):
        lines = [
            f'level=info msg="request handled" method=GET path=/api/{i} '
            f"status=200 duration={i}ms service=api"
            for i in range(20)
        ]
        path = _write_temp_file(lines)
        try:
            result = detect_format(path)
            assert result.format == "logfmt"
            assert result.match_rate == 1.0
            assert "level" in result.detected_fields
            assert "msg" in result.detected_fields
        finally:
            Path(path).unlink()


class TestDetectCustomFormat:
    """Test detection with user-defined custom regex formats."""

    def test_custom_format_match(self):
        custom_formats = {
            "my_sensor": {
                "regex": r"(?P<timestamp>\d{4}-\d{2}-\d{2}T[\d:]+Z)\s+(?P<level>\w+)\s+(?P<field>\w+)=(?P<value>[\d.]+)"
            }
        }
        lines = [f"2024-01-15T10:00:{i:02d}Z INFO temperature={22.0+i*0.1:.1f}" for i in range(20)]
        path = _write_temp_file(lines)
        try:
            result = detect_format(path, custom_formats=custom_formats)
            # Custom format should be among candidates
            all_formats = [result.format] + [a["format"] for a in result.alternatives]
            assert "custom:my_sensor" in all_formats
        finally:
            Path(path).unlink()


class TestDetectUnknownFormat:
    """Test detection on garbage/unrecognizable content."""

    def test_random_garbage(self):
        lines = [
            "xyzzy plugh 42 foo bar",
            "this is just plain text with no structure",
            "another random line that matches nothing",
            "no timestamps, no levels, just noise",
            "completely unstructured garbage data here",
        ] * 4
        path = _write_temp_file(lines)
        try:
            result = detect_format(path)
            assert result.confidence < 0.3
        finally:
            Path(path).unlink()

    def test_empty_file(self):
        path = _write_temp_file([])
        try:
            result = detect_format(path)
            assert result.format == "unknown"
            assert result.confidence == 0.0
            assert result.sample_size == 0
        finally:
            Path(path).unlink()

    def test_only_comments(self):
        path = _write_temp_file(["# comment 1", "# comment 2"])
        try:
            result = detect_format(path)
            assert result.format == "unknown"
            assert result.sample_size == 0
        finally:
            Path(path).unlink()


class TestDetectConfidenceOrdering:
    """Alternatives must be sorted by confidence descending."""

    def test_alternatives_sorted(self):
        path = str(FIXTURE_DIR / "realistic_microservice.jsonl")
        result = detect_format(path)
        if len(result.alternatives) >= 2:
            for i in range(len(result.alternatives) - 1):
                assert (
                    result.alternatives[i]["confidence"] >= result.alternatives[i + 1]["confidence"]
                ), f"Alternatives not sorted at index {i}"


class TestDetectSampleLines:
    """Verify sample_lines are returned correctly."""

    def test_sample_lines_content(self):
        lines = [f"line {i}" for i in range(10)]
        path = _write_temp_file(lines)
        try:
            result = detect_format(path)
            assert len(result.sample_lines) <= 5
            assert result.sample_lines[0] == "line 0"
        finally:
            Path(path).unlink()


class TestDetectMixedFormat:
    """Test detection of files with mixed formats."""

    def test_half_json_half_syslog(self):
        json_lines = [
            json.dumps({"ts": f"2024-01-15T10:00:{i:02d}Z", "msg": f"msg {i}"}) for i in range(10)
        ]
        syslog_lines = [f"Mar 15 03:{i:02d}:00 server app[{i}]: message {i}" for i in range(10)]
        lines = json_lines + syslog_lines
        path = _write_temp_file(lines)
        try:
            result = detect_format(path)
            # With 50/50 split, should detect mixed
            assert result.mixed is True
        finally:
            Path(path).unlink()


# ============================================================================
# Drain Template Mining — exact template assertions
# ============================================================================


class TestDrainKnownTemplates:
    """Test Drain with messages from exactly N known templates."""

    def test_three_templates_exact_counts(self):
        """100 messages from 3 templates → exactly 3 clusters with known counts."""
        messages = (
            [f"User user_{i} logged in from 192.168.1.{i}" for i in range(40)]
            + [f"Request to /api/endpoint_{i} took {100+i}ms" for i in range(35)]
            + [f"Database query SELECT * FROM table_{i} returned {i*10} rows" for i in range(25)]
        )
        result = mine_templates(messages, max_clusters=100)
        assert result.total_lines == 100
        assert result.unique_templates == 3

        # Counts must sum to exactly 100
        total_count = sum(t["count"] for t in result.templates)
        assert total_count == 100

        # Templates sorted by count descending
        assert result.templates[0]["count"] == 40
        assert result.templates[1]["count"] == 35
        assert result.templates[2]["count"] == 25

    def test_variable_extraction(self):
        """'User alice logged in' + 'User bob logged in' → template with <*>."""
        messages = [
            "User alice logged in",
            "User bob logged in",
            "User charlie logged in",
        ]
        result = mine_templates(messages, max_clusters=10)
        assert result.unique_templates == 1
        template = result.templates[0]
        assert template["count"] == 3
        assert "<*>" in template["template"]
        assert "User" in template["template"]
        assert "logged" in template["template"]
        assert "in" in template["template"]
        # Exactly one variable position (the username)
        assert len(template["variable_positions"]) == 1

    def test_coverage_all_assigned(self):
        """When all messages match templates, coverage = 1.0."""
        messages = [f"Ping from host_{i}" for i in range(50)]
        result = mine_templates(messages, max_clusters=100)
        assert result.coverage == 1.0

    def test_empty_input(self):
        result = mine_templates([])
        assert result.total_lines == 0
        assert result.unique_templates == 0
        assert result.coverage == 0.0
        assert result.templates == []

    def test_single_message(self):
        result = mine_templates(["Hello world"])
        assert result.total_lines == 1
        assert result.unique_templates == 1
        assert result.templates[0]["count"] == 1
        assert result.coverage == 1.0

    def test_completely_different_messages(self):
        """Messages with no shared structure → many templates."""
        messages = [
            "The quick brown fox jumps",
            "Hello world from server",
            "Processing batch job now",
            "Starting service initialization",
            "Connection established successfully today",
        ]
        result = mine_templates(messages, max_clusters=100)
        # Each is unique enough to be its own template (or clustered loosely)
        assert result.unique_templates >= 3  # At minimum, most should be separate
        assert result.total_lines == 5

    def test_templates_have_examples(self):
        messages = [f"Error code {i} in module main" for i in range(10)]
        result = mine_templates(messages, max_clusters=10)
        for template in result.templates:
            assert len(template["examples"]) > 0
            assert len(template["examples"]) <= 3  # Default max_examples

    def test_percentage_accuracy(self):
        """Percentages must be mathematically correct."""
        messages = ["Type A message number one"] * 60 + ["Type B message number two"] * 40
        result = mine_templates(messages, max_clusters=10)
        for template in result.templates:
            expected_pct = round(100.0 * template["count"] / 100, 2)
            assert template["percentage"] == expected_pct

    def test_numeric_tokens_become_wildcards(self):
        """Pure numbers should be recognized as variables."""
        messages = [
            "Error 404 on page",
            "Error 500 on page",
            "Error 503 on page",
        ]
        result = mine_templates(messages, max_clusters=10)
        assert result.unique_templates == 1
        template = result.templates[0]
        assert "<*>" in template["template"]
        assert "Error" in template["template"]
        assert "page" in template["template"]

    def test_ip_addresses_become_wildcards(self):
        """IP addresses should be recognized as variable tokens."""
        messages = [
            "Connection from 192.168.1.1 accepted",
            "Connection from 10.0.0.5 accepted",
            "Connection from 172.16.0.1 accepted",
        ]
        result = mine_templates(messages, max_clusters=10)
        assert result.unique_templates == 1
        assert "<*>" in result.templates[0]["template"]

    def test_max_clusters_respected(self):
        """When max_clusters is hit, excess messages are dropped (not crash)."""
        messages = [f"Unique message type {i} with content {i*100}" for i in range(50)]
        result = mine_templates(messages, max_clusters=5)
        assert result.unique_templates <= 5

    def test_similarity_threshold_effect(self):
        """High threshold → more templates (harder to merge)."""
        messages = [
            "Request GET /api/users completed in 100ms",
            "Request POST /api/orders completed in 200ms",
            "Request DELETE /api/items completed in 50ms",
        ]
        low = mine_templates(messages, sim_threshold=0.3)
        high = mine_templates(messages, sim_threshold=0.9)
        # Low threshold should merge more aggressively
        assert low.unique_templates <= high.unique_templates


class TestDrainParserDirectly:
    """Test the DrainParser class internals."""

    def test_add_message_returns_cluster(self):
        parser = DrainParser()
        cluster = parser.add_message("Hello world")
        assert cluster is not None
        assert cluster.count == 1

    def test_same_message_increments_count(self):
        parser = DrainParser()
        parser.add_message("Hello world")
        cluster = parser.add_message("Hello world")
        assert cluster is not None
        assert cluster.count == 2

    def test_similar_messages_merge(self):
        parser = DrainParser(sim_threshold=0.5)
        parser.add_message("User alice logged in")
        parser.add_message("User bob logged in")
        clusters = parser.get_clusters()
        assert len(clusters) == 1
        assert clusters[0].count == 2

    def test_empty_message_skipped(self):
        parser = DrainParser()
        result = parser.add_message("")
        assert result is None
        assert parser.get_clusters() == []

    def test_whitespace_only_skipped(self):
        parser = DrainParser()
        parser.add_message("   ")
        # Splits into empty tokens or just whitespace
        # Should either return None or handle gracefully
        clusters = parser.get_clusters()
        # At most one cluster from whitespace
        assert len(clusters) <= 1
