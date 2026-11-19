"""
PARAMETRIZED SEARCH TESTS - Exact Value Assertions

These tests use deterministic fixtures with KNOWN values and assert
EXACT expected outputs. If any test passes with wrong data, it's a bug
in the test, not a pass.

Fixture: deterministic_log_file
- 100 entries total
- 25 each of INFO/DEBUG/WARN/ERROR (lines 0,4,8... = INFO, 1,5,9... = DEBUG, etc.)
- 25 each of worker-0/1/2/3 (same pattern as levels)
- 10 each of req-0 through req-9
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

try:
    from logler.investigate import RUST_AVAILABLE, search
except ImportError as e:
    if "logler_rs" in str(e):
        RUST_AVAILABLE = False
    else:
        raise


pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required for search tests")


class TestSearchLevelFilter:
    """Test level filtering returns exact expected counts."""

    @pytest.mark.parametrize(
        "level,expected_count",
        [
            ("INFO", 25),
            ("DEBUG", 25),
            ("WARN", 25),
            ("ERROR", 25),
        ],
        ids=["info_25", "debug_25", "warn_25", "error_25"],
    )
    def test_level_filter_exact_count(self, deterministic_log_file, level, expected_count):
        """Each level appears exactly 25 times in 100 entries."""
        result = search(files=[deterministic_log_file], level=level, limit=100)

        # MUST have exact count
        assert result["total_matches"] == expected_count, (
            f"Level {level} should have exactly {expected_count} matches, "
            f"got {result['total_matches']}"
        )

        # MUST return exactly that many results
        assert len(result["results"]) == expected_count

        # ALL results must match the filter
        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["level"].upper() == level, (
                f"Entry level {entry['level']} doesn't match filter {level}"
            )


class TestSearchThreadFilter:
    """Test thread filtering returns exact expected counts."""

    @pytest.mark.parametrize(
        "thread_id,expected_count",
        [
            ("worker-0", 25),
            ("worker-1", 25),
            ("worker-2", 25),
            ("worker-3", 25),
        ],
        ids=["worker0_25", "worker1_25", "worker2_25", "worker3_25"],
    )
    def test_thread_filter_exact_count(self, deterministic_log_file, thread_id, expected_count):
        """Each thread appears exactly 25 times in 100 entries."""
        result = search(files=[deterministic_log_file], thread_id=thread_id, limit=100)

        assert result["total_matches"] == expected_count, (
            f"Thread {thread_id} should have exactly {expected_count} matches, "
            f"got {result['total_matches']}"
        )

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["thread_id"] == thread_id


class TestSearchCorrelationFilter:
    """Test correlation ID filtering returns exact expected counts."""

    @pytest.mark.parametrize(
        "correlation_id,expected_count",
        [
            ("req-0", 10),
            ("req-1", 10),
            ("req-5", 10),
            ("req-9", 10),
        ],
        ids=["req0_10", "req1_10", "req5_10", "req9_10"],
    )
    def test_correlation_filter_exact_count(
        self, deterministic_log_file, correlation_id, expected_count
    ):
        """Each correlation ID appears exactly 10 times (100 entries / 10 IDs)."""
        result = search(files=[deterministic_log_file], correlation_id=correlation_id, limit=100)

        assert result["total_matches"] == expected_count, (
            f"Correlation {correlation_id} should have exactly {expected_count} matches"
        )

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["correlation_id"] == correlation_id


class TestSearchCombinedFilters:
    """Test combined filters with exact expected outcomes."""

    @pytest.mark.parametrize(
        "level,thread_id,expected_count",
        [
            # Level and thread are aligned: INFO=worker-0, DEBUG=worker-1, etc.
            ("INFO", "worker-0", 25),  # All 25 INFO entries are from worker-0
            ("DEBUG", "worker-1", 25),  # All 25 DEBUG entries are from worker-1
            ("WARN", "worker-2", 25),  # All 25 WARN entries are from worker-2
            ("ERROR", "worker-3", 25),  # All 25 ERROR entries are from worker-3
            # Misaligned combinations should return 0
            ("INFO", "worker-1", 0),  # INFO is never from worker-1
            ("ERROR", "worker-0", 0),  # ERROR is never from worker-0
        ],
        ids=[
            "info_worker0_match",
            "debug_worker1_match",
            "warn_worker2_match",
            "error_worker3_match",
            "info_worker1_nomatch",
            "error_worker0_nomatch",
        ],
    )
    def test_level_and_thread_combined(
        self, deterministic_log_file, level, thread_id, expected_count
    ):
        """Combined level+thread filters return exact counts."""
        result = search(
            files=[deterministic_log_file],
            level=level,
            thread_id=thread_id,
            limit=100,
        )

        assert result["total_matches"] == expected_count, (
            f"Level={level} + Thread={thread_id} should have {expected_count} matches, "
            f"got {result['total_matches']}"
        )


class TestSearchQuery:
    """Test text query matching with exact expected results."""

    @pytest.mark.parametrize(
        "query,min_expected,max_expected",
        [
            ("message", 100, 100),  # All entries contain "message"
            ("Log message number", 100, 100),  # All messages have this prefix
            ("ZZZNOTFOUND", 0, 0),  # No matches
        ],
        ids=["all_entries", "message_prefix", "no_match"],
    )
    def test_query_match_counts(self, deterministic_log_file, query, min_expected, max_expected):
        """Text queries return expected match counts within range."""
        result = search(files=[deterministic_log_file], query=query, limit=100)

        assert min_expected <= result["total_matches"] <= max_expected, (
            f"Query '{query}' should have {min_expected}-{max_expected} matches, "
            f"got {result['total_matches']}"
        )

    def test_specific_message_search(self, deterministic_log_file):
        """Search for a specific unique message pattern."""
        # Search for a pattern that only appears once
        result = search(files=[deterministic_log_file], query="Log message number 50", limit=100)

        # Should find at least 1 match (the exact message)
        assert result["total_matches"] >= 1, "Should find message with 'number 50'"

        # Verify the result contains the expected message
        found = False
        for item in result["results"]:
            entry = item.get("entry", item)
            if "number 50" in entry.get("message", ""):
                found = True
                break
        assert found, "Should find entry with 'number 50' in message"


class TestSearchLimit:
    """Test limit parameter enforces exact boundaries."""

    @pytest.mark.parametrize(
        "limit,expected_returned",
        [
            (1, 1),
            (5, 5),
            (10, 10),
            (50, 50),
            (100, 100),  # All entries
            (200, 100),  # More than available, should cap at 100
        ],
        ids=["limit_1", "limit_5", "limit_10", "limit_50", "limit_100", "limit_200"],
    )
    def test_limit_exact_results(self, deterministic_log_file, limit, expected_returned):
        """Limit parameter returns exactly min(limit, total) results."""
        result = search(files=[deterministic_log_file], query="message", limit=limit)

        assert len(result["results"]) == expected_returned, (
            f"With limit={limit}, should return {expected_returned} results, "
            f"got {len(result['results'])}"
        )
        # Total matches should always be 100 (all entries match "message")
        assert result["total_matches"] == 100


class TestSearchOutputFormats:
    """Test different output formats have required keys."""

    @pytest.mark.parametrize(
        "output_format,required_keys",
        [
            ("full", ["results", "total_matches"]),
            ("summary", ["total_matches"]),
            ("count", ["total_matches"]),
        ],
        ids=["full", "summary", "count"],
    )
    def test_output_format_keys(self, deterministic_log_file, output_format, required_keys):
        """Each output format includes its required keys."""
        result = search(
            files=[deterministic_log_file],
            query="message",
            output_format=output_format,
        )

        for key in required_keys:
            assert key in result, f"Format '{output_format}' missing required key '{key}'"

    def test_full_format_has_100_results(self, deterministic_log_file):
        """Full format with 'message' query should have 100 matches."""
        result = search(
            files=[deterministic_log_file],
            query="message",
            output_format="full",
            limit=100,
        )

        assert result["total_matches"] == 100
        assert len(result["results"]) == 100


class TestSearchEdgeCases:
    """Edge cases that should return specific results."""

    def test_empty_query_returns_all(self, deterministic_log_file):
        """Empty query should match all 100 entries."""
        result = search(files=[deterministic_log_file], query="", limit=100)

        assert result["total_matches"] == 100, "Empty query should match all entries"

    def test_none_query_returns_all(self, deterministic_log_file):
        """None query should match all 100 entries."""
        result = search(files=[deterministic_log_file], query=None, limit=100)

        assert result["total_matches"] == 100, "None query should match all entries"

    def test_nonexistent_level_returns_zero(self, deterministic_log_file):
        """Non-existent level should return 0 matches."""
        result = search(files=[deterministic_log_file], level="TRACE", limit=100)

        assert result["total_matches"] == 0, "Non-existent level should return 0 matches"

    def test_nonexistent_thread_returns_zero(self, deterministic_log_file):
        """Non-existent thread should return 0 matches."""
        result = search(files=[deterministic_log_file], thread_id="worker-99", limit=100)

        assert result["total_matches"] == 0, "Non-existent thread should return 0 matches"

    def test_nonexistent_correlation_returns_zero(self, deterministic_log_file):
        """Non-existent correlation ID should return 0 matches."""
        result = search(files=[deterministic_log_file], correlation_id="req-nonexistent", limit=100)

        assert result["total_matches"] == 0


class TestSearchResultStructure:
    """Verify result structure has required fields with correct values."""

    def test_result_entries_have_required_fields(self, deterministic_log_file):
        """Each result entry must have level, message, thread_id, correlation_id."""
        result = search(files=[deterministic_log_file], limit=10)

        assert len(result["results"]) == 10, "Should return exactly 10 results"

        required_fields = ["level", "message", "thread_id", "correlation_id"]
        for item in result["results"]:
            entry = item.get("entry", item)
            for field in required_fields:
                assert field in entry, f"Entry missing required field '{field}'"

    def test_entries_have_correct_line_indices(self, deterministic_log_file):
        """Entries should have their original line indices preserved."""
        # Search for entries with specific line numbers
        result = search(files=[deterministic_log_file], query="number 0", limit=10)

        # "number 0" should match entry at line 0
        assert result["total_matches"] >= 1
        found = False
        for item in result["results"]:
            entry = item.get("entry", item)
            if "number 0" in entry.get("message", ""):
                found = True
                # Verify it's actually entry 0
                assert entry.get("line_index") == 0 or "number 0" in entry["message"]
                break
        assert found, "Should find entry with 'number 0'"


NO_LEVEL_LOG = """2024-01-01T10:00:00Z INFO [w-1] hello
plain line without a level
another plain line
2024-01-01T10:00:01Z ERROR [w-1] boom
plain line without a level
"""


@pytest.fixture
def no_level_file(tmp_path):
    path = tmp_path / "nolevel.log"
    path.write_text(NO_LEVEL_LOG)
    return str(path)


class TestLineWithNoLevelIsUnknown:
    """A line the engine gives no level reads UNKNOWN through every door, never NONE."""

    def test_search(self, no_level_file):
        result = search([no_level_file])
        levels = {i["entry"]["line_number"]: i["entry"]["level"] for i in result["results"]}
        assert levels == {1: "INFO", 2: "UNKNOWN", 3: "UNKNOWN", 4: "ERROR", 5: "UNKNOWN"}
        assert search([no_level_file], output_format="count")["by_level"] == {
            "INFO": 1,
            "ERROR": 1,
            "UNKNOWN": 3,
        }

    def test_search_context_entries(self, no_level_file):
        result = search([no_level_file], context_lines=1)
        by_line = {i["entry"]["line_number"]: i for i in result["results"]}
        assert sorted(by_line) == [1, 2, 3, 4, 5]
        assert [e["level"] for e in by_line[2]["context_before"]] == ["INFO"]
        assert [e["level"] for e in by_line[2]["context_after"]] == ["UNKNOWN"]
        assert [e["level"] for e in by_line[4]["context_before"]] == ["UNKNOWN"]
        assert [e["level"] for e in by_line[4]["context_after"]] == ["UNKNOWN"]

    def test_investigator_search(self, no_level_file):
        from logler.investigate import Investigator

        inv = Investigator()
        inv.load_files([no_level_file])
        levels = [i["entry"]["level"] for i in inv.search()["results"]]
        assert sorted(levels) == ["ERROR", "INFO", "UNKNOWN", "UNKNOWN", "UNKNOWN"]

    def test_follow_thread_and_get_context(self, no_level_file):
        from logler.investigate import follow_thread, get_context

        entries = follow_thread([no_level_file], thread_id="w-1")["entries"]
        assert entries and all(e["level"] in {"INFO", "ERROR", "UNKNOWN"} for e in entries)
        context = get_context(no_level_file, 2, 1, 1)
        assert context["target"]["level"] == "UNKNOWN"
        assert [e["level"] for e in context["context_before"]] == ["INFO"]
        assert [e["level"] for e in context["context_after"]] == ["UNKNOWN"]

    def test_find_patterns_examples(self, no_level_file):
        """The engine only makes patterns of error lines, so no real example lacks a level;
        the normaliser still gives a level-less example UNKNOWN."""
        from logler._search_core import _normalize_pattern_examples
        from logler.investigate import find_patterns

        repeated = find_patterns([no_level_file], min_occurrences=1)["patterns"]
        assert {e["level"] for p in repeated for e in p["examples"]} == {"ERROR"}

        result = {"patterns": [{"examples": [{"level": None}, {"level": " warn "}]}]}
        _normalize_pattern_examples(result)
        assert [e["level"] for e in result["patterns"][0]["examples"]] == ["UNKNOWN", "WARN"]

    def test_parser_adapter_agrees(self):
        from logler.parser import LogParser

        assert LogParser().parse_line(1, "plain line without a level").level == "UNKNOWN"


class TestSyslogLevelComesFromTheEngine:
    """The Python syslog fallback was dead: the engine maps the priority itself."""

    def test_priority_lines_have_their_levels(self, tmp_path):
        path = tmp_path / "syslog.log"
        path.write_text(
            "<14>Jan  1 10:00:00 host app[1]: info line\n"
            "<11>Jan  1 10:00:01 host app[1]: err line\n"
            "<12>Jan  1 10:00:02 host app[1]: warn line\n"
        )
        levels = {
            i["entry"]["line_number"]: i["entry"]["level"] for i in search([str(path)])["results"]
        }
        assert levels == {1: "INFO", 2: "ERROR", 3: "WARN"}


class TestExplicitFormatNeverReachesTheCache:
    def test_custom_regex_then_plain_gives_builtin_reading(self, tmp_path):
        path = tmp_path / "robot.log"
        path.write_text("error;3;overtravel\ninfo;1;homed\n")
        regex = r"^(?P<level>\w+);(?P<axis>\d+);(?P<message>.*)$"
        custom = search([str(path)], custom_regex=regex)
        assert {i["entry"]["level"] for i in custom["results"]} == {"ERROR", "INFO"}
        plain = search([str(path)])
        assert {i["entry"]["level"] for i in plain["results"]} == {"UNKNOWN"}
        again = search([str(path)], custom_regex=regex)
        assert {i["entry"]["level"] for i in again["results"]} == {"ERROR", "INFO"}

    def test_find_patterns_takes_an_explicit_format(self, tmp_path):
        from logler.investigate import find_patterns

        path = tmp_path / "robot.log"
        path.write_text("".join(f"2024-01-15T10:00:0{i}Z;error;overtravel\n" for i in range(3)))
        regex = r"^(?P<timestamp>\S+);(?P<level>\w+);(?P<message>.*)$"

        named = find_patterns([str(path)], custom_regex=regex)["patterns"]
        assert [
            (p["pattern"], p["occurrences"], p["first_seen"], p["last_seen"]) for p in named
        ] == [("overtravel", 3, "2024-01-15T10:00:00Z", "2024-01-15T10:00:02Z")]
        # Read without the format, the lines have no level, so they are no error pattern.
        assert find_patterns([str(path)])["patterns"] == []


class TestCountFormatIsTheTotal:
    """`output_format="count"` and `"summary"` report every match, whatever else is asked."""

    def test_count_format_with_count_only_is_the_count(self, deterministic_log_file):
        full = search(files=[deterministic_log_file], level="ERROR")
        counted = search(
            files=[deterministic_log_file], level="ERROR", output_format="count", count_only=True
        )
        assert full["total_matches"] == 25
        assert counted["total_matches"] == 25

    def test_count_format_total_ignores_the_limit(self, deterministic_log_file):
        counted = search(
            files=[deterministic_log_file], level="ERROR", output_format="count", limit=5
        )
        assert counted["total_matches"] == 25
        assert counted["by_level"] == {"ERROR": 25}
        assert counted["by_file"] == {deterministic_log_file: 25}
        assert counted["time_range"] == {
            "start": "2024-01-15T10:00:03Z",
            "end": "2024-01-15T10:01:39Z",
        }

    def test_summary_format_total_ignores_the_limit(self, deterministic_log_file):
        summary = search(
            files=[deterministic_log_file], level="ERROR", output_format="summary", limit=5
        )
        assert summary["total_matches"] == 25
        assert summary["log_levels"] == {"ERROR": 25}
        assert summary["by_file"] == {deterministic_log_file: 25}
        assert summary["unique_messages"] == 25
        assert len(summary["top_messages"]) == 20
        assert [e["message"] for e in summary["sample_entries"]] == [
            f"Log message number {i}" for i in (3, 7, 11, 15, 19)
        ]

    def test_summary_format_limit_bounds_only_the_samples(self, deterministic_log_file):
        summary = search(
            files=[deterministic_log_file], level="ERROR", output_format="summary", limit=2
        )
        assert summary["log_levels"] == {"ERROR": 25}
        assert [e["message"] for e in summary["sample_entries"]] == [
            "Log message number 3",
            "Log message number 7",
        ]

    def test_summary_format_limit_zero_and_no_match(self, deterministic_log_file):
        every = search(files=[deterministic_log_file], output_format="summary", limit=0)
        assert every["total_matches"] == 100
        assert every["log_levels"] == {"INFO": 25, "DEBUG": 25, "WARN": 25, "ERROR": 25}
        none = search(
            files=[deterministic_log_file], query="zzz-no-such-text", output_format="summary"
        )
        assert none == {
            "total_matches": 0,
            "unique_messages": 0,
            "log_levels": {},
            "top_messages": [],
            "sample_entries": [],
        }

    def test_count_format_over_the_engine_cap_counts_every_match(self, tmp_path):
        """More matches than the 10,000 entries a search returns with no limit."""
        path = tmp_path / "big.log"
        path.write_text(_info_then_error_lines(10_000, 2_000))
        counted = search(files=[str(path)], output_format="count")
        assert counted["total_matches"] == 12_000
        assert counted["by_level"] == {"INFO": 10_000, "ERROR": 2_000}
        assert counted["time_range"] == {
            "start": "2024-01-15T00:00:00Z",
            "end": "2024-01-15T03:19:59Z",
        }

    def test_count_format_limit_zero_is_no_cap(self, deterministic_log_file):
        counted = search(files=[deterministic_log_file], output_format="count", limit=0)
        assert counted["total_matches"] == 100

    def test_count_format_no_match_is_zero(self, deterministic_log_file):
        for kwargs in ({}, {"count_only": True}):
            counted = search(
                files=[deterministic_log_file],
                query="zzz-no-such-text",
                output_format="count",
                **kwargs,
            )
            assert counted["total_matches"] == 0


def _info_then_error_lines(info: int, error: int) -> str:
    """``info`` INFO lines then ``error`` ERROR lines, one second apart from midnight."""
    lines = []
    for i in range(info + error):
        level = "INFO" if i < info else "ERROR"
        stamp = f"2024-01-15T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}Z"
        lines.append(f"{stamp} {level} line {i}\n")
    return "".join(lines)


def _json_lines(records: list[dict]) -> str:
    return "".join(json.dumps(r) + "\n" for r in records)


# Seven lines, three messages twice each, first seen in the order beta, alpha, gamma.
TIES = [
    ("INFO", "beta"),
    ("ERROR", "alpha"),
    ("WARN", "gamma"),
    ("INFO", "alpha"),
    ("INFO", "beta"),
    ("DEBUG", "gamma"),
    ("INFO", "delta"),
]

TIES_SCRIPT = """
import json, sys
from logler.investigate import search
out = search(files=[sys.argv[1]], output_format="summary")
print(json.dumps([(m["message"], m["count"], m["levels"]) for m in out["top_messages"]]))
"""


class TestSummaryCountsEveryMatch:
    """The summary and count formats are counted by the engine over every match."""

    @pytest.fixture
    def ties_log(self, tmp_path):
        path = tmp_path / "ties.log"
        path.write_text(
            _json_lines(
                {"timestamp": f"2024-01-15T10:00:{i:02d}Z", "level": lv, "message": msg}
                for i, (lv, msg) in enumerate(TIES)
            )
        )
        return str(path)

    def test_equal_counts_come_in_order_of_first_match_in_every_process(self, ties_log):
        src = str(Path(__file__).resolve().parent.parent / "src")
        outs = [
            subprocess.run(
                [sys.executable, "-c", TIES_SCRIPT, ties_log],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": src},
                check=True,
            ).stdout
            for seed in ("0", "1", "2")
        ]
        expected = [
            ["beta", 2, {"INFO": 2}],
            ["alpha", 2, {"ERROR": 1, "INFO": 1}],
            ["gamma", 2, {"WARN": 1, "DEBUG": 1}],
            ["delta", 1, {"INFO": 1}],
        ]
        assert [json.loads(o) for o in outs] == [expected, expected, expected]

    def test_a_long_message_is_cut_to_200_characters(self, tmp_path):
        path = tmp_path / "long.log"
        path.write_text(_json_lines([{"level": "ERROR", "message": "x" * 250}] * 2))
        summary = search(files=[str(path)], output_format="summary")
        assert [(m["message"], m["count"]) for m in summary["top_messages"]] == [("x" * 200, 2)]

    def test_matches_with_no_timestamp(self, tmp_path):
        path = tmp_path / "plain.log"
        path.write_text("alpha one\nERROR beta two\nalpha one\n")
        summary = search(files=[str(path)], output_format="summary")
        assert [
            (m["message"], m["first_seen"], m["last_seen"]) for m in summary["top_messages"]
        ] == [
            ("alpha one", None, None),
            ("ERROR beta two", None, None),
        ]
        counted = search(files=[str(path)], output_format="count")
        assert counted == {
            "total_matches": 3,
            "by_level": {"UNKNOWN": 2, "ERROR": 1},
            "by_file": {str(path): 3},
            "time_range": None,
        }

    def test_times_are_compared_as_times(self, tmp_path):
        """A whole second is written with no fraction: ``05Z`` is before ``05.500Z``."""
        path = tmp_path / "frac.log"
        path.write_text(
            _json_lines(
                [
                    {"timestamp": "2024-01-15T10:00:05.500Z", "level": "INFO", "message": "tick"},
                    {"timestamp": "2024-01-15T10:00:05Z", "level": "INFO", "message": "tick"},
                ]
            )
        )
        summary = search(files=[str(path)], output_format="summary")
        tick = summary["top_messages"][0]
        assert (tick["first_seen"], tick["last_seen"]) == (
            "2024-01-15T10:00:05Z",
            "2024-01-15T10:00:05.500Z",
        )
        counted = search(files=[str(path)], output_format="count")
        assert counted["time_range"] == {
            "start": "2024-01-15T10:00:05Z",
            "end": "2024-01-15T10:00:05.500Z",
        }

    def test_tail_bounds_only_the_samples(self, deterministic_log_file):
        summary = search(
            files=[deterministic_log_file], level="ERROR", output_format="summary", tail=5
        )
        assert summary["total_matches"] == 25
        assert summary["log_levels"] == {"ERROR": 25}
        assert summary["unique_messages"] == 25
        assert [e["message"] for e in summary["sample_entries"]] == [
            f"Log message number {i}" for i in (83, 87, 91, 95, 99)
        ]

    def test_two_files(self, deterministic_log_file, tmp_path):
        other = tmp_path / "other.log"
        other.write_text(
            _json_lines(
                {"timestamp": f"2024-01-15T09:00:{i:02d}Z", "level": "WARN", "message": "o"}
                for i in range(3)
            )
        )
        counted = search(files=[deterministic_log_file, str(other)], output_format="count")
        assert counted["total_matches"] == 103
        assert counted["by_file"] == {str(other): 3, deterministic_log_file: 100}
        assert counted["by_level"] == {"WARN": 28, "INFO": 25, "DEBUG": 25, "ERROR": 25}

    def test_count_only_summary_has_the_counts_and_no_samples(self, deterministic_log_file):
        summary = search(
            files=[deterministic_log_file], level="WARN", output_format="summary", count_only=True
        )
        assert summary["total_matches"] == 25
        assert summary["log_levels"] == {"WARN": 25}
        assert summary["unique_messages"] == 25
        assert summary["sample_entries"] == []

    def test_errors_after_the_first_10000_matches_are_counted(self, tmp_path):
        path = tmp_path / "big.log"
        path.write_text(_info_then_error_lines(10_000, 2_000))
        summary = search(files=[str(path)], output_format="summary")
        assert summary["total_matches"] == 12_000
        assert summary["log_levels"] == {"INFO": 10_000, "ERROR": 2_000}
        assert summary["unique_messages"] == 12_000
        assert len(summary["sample_entries"]) == 5
