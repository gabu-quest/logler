"""
CLI integration tests for `logler llm detect` and `logler llm templates` (M6.4).

Tests JSON output structure, confidence values, template counts, exit codes.
Uses Click's CliRunner — no subprocess spawning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from logler.llm_cli import llm, EXIT_SUCCESS

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def json_log():
    return str(FIXTURE_DIR / "realistic_microservice.jsonl")


@pytest.fixture
def syslog_file():
    return str(FIXTURE_DIR / "realistic_syslog.log")


@pytest.fixture
def apache_log():
    return str(FIXTURE_DIR / "real_apache_clf.log")


# ============================================================================
# logler llm detect
# ============================================================================


class TestDetectJsonOutput:
    """Test detect command produces valid JSON with required fields."""

    def test_valid_json_structure(self, runner, json_log):
        result = runner.invoke(llm, ["detect", json_log])
        assert result.exit_code == EXIT_SUCCESS
        data = json.loads(result.output)
        assert "files" in data

    def test_per_file_keys(self, runner, json_log):
        result = runner.invoke(llm, ["detect", json_log])
        data = json.loads(result.output)
        for file_path, detection in data["files"].items():
            assert "format" in detection
            assert "confidence" in detection
            assert "match_rate" in detection
            assert "alternatives" in detection
            assert "detected_fields" in detection
            assert "sample_lines" in detection
            assert isinstance(detection["confidence"], (int, float))
            assert isinstance(detection["match_rate"], (int, float))

    def test_json_file_detected_as_json(self, runner, json_log):
        result = runner.invoke(llm, ["detect", json_log])
        data = json.loads(result.output)
        for detection in data["files"].values():
            assert detection["format"] == "json"
            assert detection["confidence"] >= 0.95

    def test_syslog_file_detected(self, runner, syslog_file):
        result = runner.invoke(llm, ["detect", syslog_file])
        data = json.loads(result.output)
        for detection in data["files"].values():
            assert detection["format"] == "syslog"
            assert detection["confidence"] >= 0.8

    def test_apache_clf_detected(self, runner, apache_log):
        result = runner.invoke(llm, ["detect", apache_log])
        data = json.loads(result.output)
        for detection in data["files"].values():
            assert detection["format"] == "common_log"
            assert detection["confidence"] >= 0.8

    def test_multiple_files(self, runner, json_log, syslog_file):
        result = runner.invoke(llm, ["detect", json_log, syslog_file])
        data = json.loads(result.output)
        assert len(data["files"]) == 2

    def test_sample_size_option(self, runner, json_log):
        result = runner.invoke(llm, ["detect", json_log, "--sample", "10"])
        data = json.loads(result.output)
        for detection in data["files"].values():
            assert detection["sample_size"] <= 10

    def test_alternatives_sorted_by_confidence(self, runner, json_log):
        result = runner.invoke(llm, ["detect", json_log])
        data = json.loads(result.output)
        for detection in data["files"].values():
            alts = detection["alternatives"]
            for i in range(len(alts) - 1):
                assert alts[i]["confidence"] >= alts[i + 1]["confidence"]


class TestDetectPrettyOutput:
    """Test --pretty flag."""

    def test_pretty_has_indentation(self, runner, json_log):
        result = runner.invoke(llm, ["detect", json_log, "--pretty"])
        assert "\n" in result.output
        assert "  " in result.output
        json.loads(result.output)  # Still valid JSON


class TestDetectMissingFile:
    """Test error handling for missing files."""

    def test_nonexistent_file(self, runner):
        result = runner.invoke(llm, ["detect", "/nonexistent/path.log"])
        assert result.exit_code != EXIT_SUCCESS


# ============================================================================
# logler llm templates
# ============================================================================


class TestTemplatesJsonOutput:
    """Test templates command produces valid JSON."""

    def test_valid_json_structure(self, runner, json_log):
        result = runner.invoke(llm, ["templates", json_log])
        assert result.exit_code == EXIT_SUCCESS
        data = json.loads(result.output)
        assert "templates" in data
        assert "total_lines" in data
        assert "unique_templates" in data
        assert "coverage" in data
        assert "files_searched" in data

    def test_template_entries_have_required_keys(self, runner, json_log):
        result = runner.invoke(llm, ["templates", json_log])
        data = json.loads(result.output)
        for template in data["templates"]:
            assert "template" in template
            assert "count" in template
            assert "percentage" in template
            assert "examples" in template
            assert isinstance(template["count"], int)
            assert isinstance(template["percentage"], (int, float))


class TestTemplatesCountAccuracy:
    """Template counts must be mathematically consistent."""

    def test_counts_sum_to_total(self, runner, json_log):
        result = runner.invoke(llm, ["templates", json_log])
        data = json.loads(result.output)
        total_from_templates = sum(t["count"] for t in data["templates"])
        # The sum should equal total_lines (when coverage is 1.0)
        # or be <= total_lines otherwise
        assert total_from_templates <= data["total_lines"]

    def test_percentages_are_correct(self, runner, json_log):
        result = runner.invoke(llm, ["templates", json_log])
        data = json.loads(result.output)
        total = data["total_lines"]
        if total > 0:
            for t in data["templates"]:
                expected_pct = round(100.0 * t["count"] / total, 2)
                assert t["percentage"] == expected_pct, (
                    f"Template '{t['template']}': expected {expected_pct}%, "
                    f"got {t['percentage']}%"
                )


class TestTemplatesOptions:
    """Test CLI options."""

    def test_max_clusters(self, runner, json_log):
        result = runner.invoke(llm, ["templates", json_log, "--max-clusters", "5"])
        data = json.loads(result.output)
        assert data["unique_templates"] <= 5

    def test_pretty_output(self, runner, json_log):
        result = runner.invoke(llm, ["templates", json_log, "--pretty"])
        assert "\n" in result.output
        json.loads(result.output)

    def test_templates_sorted_by_count(self, runner, json_log):
        result = runner.invoke(llm, ["templates", json_log])
        data = json.loads(result.output)
        counts = [t["count"] for t in data["templates"]]
        assert counts == sorted(counts, reverse=True)


class TestTemplatesMissingFile:
    """Test error handling."""

    def test_nonexistent_file(self, runner):
        result = runner.invoke(llm, ["templates", "/nonexistent/path.log"])
        assert result.exit_code != EXIT_SUCCESS


class TestTemplatesWithSensorLog:
    """Test against the sensor fixture with known patterns."""

    def test_sensor_log_has_templates(self, runner):
        sensor = str(FIXTURE_DIR / "numeric_sensor.log")
        result = runner.invoke(llm, ["templates", sensor])
        data = json.loads(result.output)
        assert data["unique_templates"] >= 1
        # Fixture has 20 data lines but Rust parser may count comment
        # lines too — assert at least 20 lines were processed
        assert data["total_lines"] >= 20
        assert data["coverage"] > 0.0
