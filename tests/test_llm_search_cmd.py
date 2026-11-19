"""Tests for the `logler llm search` command and its filtering options."""

import json
from typing import ClassVar

import pytest

from tests.conftest import EXIT_NO_RESULTS, EXIT_SUCCESS, invoke, run_llm_command


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


class TestCountsByLevelAddUp:
    """A line with no level is counted under UNKNOWN, in every count by level."""

    @pytest.fixture
    def ten_lines_three_without_a_level(self, tmp_path):
        path = tmp_path / "ten.log"
        path.write_text(
            "2024-01-15T10:00:00Z INFO one\n"
            "2024-01-15T10:00:01Z ERROR two\n"
            "continuation without a level\n"
            "2024-01-15T10:00:03Z WARN four\n"
            "2024-01-15T10:00:04Z INFO five\n"
            "  at somewhere.java:12\n"
            "2024-01-15T10:00:06Z INFO seven\n"
            "2024-01-15T10:00:07Z ERROR eight\n"
            "plain nine\n"
            "2024-01-15T10:00:09Z DEBUG ten\n"
        )
        return str(path)

    EXPECTED: ClassVar[dict[str, int]] = {
        "INFO": 3,
        "ERROR": 2,
        "WARN": 1,
        "DEBUG": 1,
        "UNKNOWN": 3,
    }

    def test_search(self, ten_lines_three_without_a_level):
        _, stdout, _ = invoke(["search", ten_lines_three_without_a_level])
        assert json.loads(stdout)["aggregations"]["by_level"] == self.EXPECTED

    def test_summarize(self, ten_lines_three_without_a_level):
        _, stdout, _ = invoke(["summarize", ten_lines_three_without_a_level])
        assert json.loads(stdout)["stats"]["by_level"] == self.EXPECTED

    def test_triage_reads_the_metadata_counts(self, ten_lines_three_without_a_level):
        _, stdout, _ = invoke(["triage", ten_lines_three_without_a_level])
        assert json.loads(stdout)["metrics"]["log_levels"] == self.EXPECTED

    def test_a_file_with_no_level_on_any_line(self, tmp_path):
        path = tmp_path / "none.log"
        path.write_text("alpha\nbeta\ngamma\n")
        _, stdout, _ = invoke(["summarize", str(path)])
        assert json.loads(stdout)["stats"]["by_level"] == {"UNKNOWN": 3}

    @pytest.mark.parametrize("entry", [{}, {"level": None}, {"level": ""}])
    def test_an_entry_dict_with_no_level_is_counted_under_unknown(self, entry):
        from logler._search_core import _format_as_count, _format_as_summary

        result = {"results": [{"entry": {"message": "m", "file": "f", **entry}}]}
        assert _format_as_count(result)["by_level"] == {"UNKNOWN": 1}
        assert _format_as_summary(result)["log_levels"] == {"UNKNOWN": 1}
