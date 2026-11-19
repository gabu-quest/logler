"""Tests for relative and absolute --after/--before time bounds."""

import json

import pytest

from tests.conftest import invoke


@pytest.fixture
def three_hour_correlated_log(tmp_path):
    """The same three lines, each carrying correlation_id=req-1."""
    path = tmp_path / "corr.log"
    path.write_text(
        "2024-01-15T08:00:00Z ERROR [w-1] correlation_id=req-1 early\n"
        "2024-01-15T10:00:00Z ERROR [w-1] correlation_id=req-1 middle\n"
        "2024-01-15T12:00:00Z ERROR [w-1] correlation_id=req-1 late\n"
    )
    return str(path)


def _lines_summarize(stdout):
    return [e["line"] for e in json.loads(stdout)["errors"]]


def _lines_emit(stdout):
    return [json.loads(line)["line_number"] for line in stdout.splitlines()]


def _lines_sample(stdout):
    return [e["line_number"] for e in json.loads(stdout)["entries"]]


def _lines_correlate(stdout):
    return [e["line_number"] for e in json.loads(stdout)["timeline"]]


# (flag, bound, line numbers kept): a bound is inclusive; one without a zone is UTC.
TIME_BOUND_CASES = [
    ("--after", "2024-01-15T09:00:00Z", [2, 3]),
    ("--before", "2024-01-15T09:00:00Z", [1]),
    ("--after", "2024-01-15T09:00:00", [2, 3]),
    ("--before", "2024-01-15T09:00:00", [1]),
    ("--after", "2024-01-15T10:00:00Z", [2, 3]),
    ("--before", "2024-01-15T10:00:00Z", [1, 2]),
    ("--after", "2024-01-14T00:00:00Z", [1, 2, 3]),
    ("--before", "2024-01-14T00:00:00Z", []),
    ("--after", "2024-01-16T00:00:00Z", []),
    ("--before", "2024-01-16T00:00:00Z", [1, 2, 3]),
]


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


class TestTimeBoundsCompareTimes:
    """A bound on a line-reading command is compared as a time, not as text."""

    @pytest.mark.parametrize("flag,bound,expected", TIME_BOUND_CASES)
    def test_summarize(self, three_hour_log, flag, bound, expected):
        code, stdout, _ = invoke(["summarize", three_hour_log, flag, bound])
        assert _lines_summarize(stdout) == expected
        assert json.loads(stdout)["stats"]["total_entries"] == len(expected)
        assert code == (0 if expected else 1)

    @pytest.mark.parametrize("flag,bound,expected", TIME_BOUND_CASES)
    def test_emit(self, three_hour_log, flag, bound, expected):
        _, stdout, _ = invoke(["emit", three_hour_log, flag, bound])
        assert _lines_emit(stdout) == expected

    @pytest.mark.parametrize("flag,bound,expected", TIME_BOUND_CASES)
    def test_sample(self, three_hour_log, flag, bound, expected):
        _, stdout, _ = invoke(
            ["sample", three_hour_log, "--strategy", "head", "--size", "10", flag, bound]
        )
        assert _lines_sample(stdout) == expected

    @pytest.mark.parametrize("flag,bound,expected", TIME_BOUND_CASES)
    def test_correlate(self, three_hour_correlated_log, flag, bound, expected):
        _, stdout, _ = invoke(["correlate", "req-1", "-f", three_hour_correlated_log, flag, bound])
        assert _lines_correlate(stdout) == expected

    def test_a_line_in_another_zone_is_placed_by_its_instant(self, tmp_path):
        path = tmp_path / "zones.log"
        path.write_text(
            "2024-01-15T11:30:00+02:00 ERROR half past nine in UTC\n"
            "2024-01-15T10:00:00Z ERROR ten in UTC\n"
        )
        _, stdout, _ = invoke(["summarize", str(path), "--after", "2024-01-15T09:45:00Z"])
        assert _lines_summarize(stdout) == [2]

    def test_diff_reads_a_bound_without_a_zone_as_utc(self, three_hour_log):
        code, stdout, _ = invoke(
            [
                "diff",
                three_hour_log,
                "--before-start",
                "2024-01-15T07:00:00",
                "--before-end",
                "2024-01-15T09:00:00",
                "--after-start",
                "2024-01-15T09:30:00",
                "--after-end",
                "2024-01-15T13:00:00",
            ]
        )
        assert code == 0
        comparison = json.loads(stdout)["comparison"]
        assert (comparison["before"]["total"], comparison["after"]["total"]) == (1, 2)
        assert (comparison["before"]["start"], comparison["after"]["end"]) == (
            "2024-01-15T07:00:00Z",
            "2024-01-15T13:00:00Z",
        )

    @pytest.fixture
    def log_with_an_untimed_line(self, tmp_path):
        """08:00, 10:00 and 12:00, then a line with a level and no time (line 4)."""
        path = tmp_path / "untimed.log"
        path.write_text(
            "2024-01-15T08:00:00Z ERROR [w-1] correlation_id=req-1 early\n"
            "2024-01-15T10:00:00Z ERROR [w-1] correlation_id=req-1 middle\n"
            "2024-01-15T12:00:00Z ERROR [w-1] correlation_id=req-1 late\n"
            "ERROR [w-1] correlation_id=req-1 no time on this line\n"
        )
        return str(path)

    @pytest.mark.parametrize(
        "args,lines",
        [
            (
                ["search", "{f}", "--compact"],
                lambda out: sorted(r["ln"] for r in json.loads(out)["results"]),
            ),
            (["summarize", "{f}"], _lines_summarize),
            (["emit", "{f}"], _lines_emit),
            (["sample", "{f}", "--strategy", "head", "--size", "10"], _lines_sample),
            (["correlate", "req-1", "-f", "{f}"], lambda out: sorted(_lines_correlate(out))),
        ],
        ids=["search", "summarize", "emit", "sample", "correlate"],
    )
    def test_a_line_with_no_time_is_kept_under_a_bound_as_search_keeps_it(
        self, log_with_an_untimed_line, args, lines
    ):
        args = [a.replace("{f}", log_with_an_untimed_line) for a in args]
        _, stdout, _ = invoke(args + ["--after", "2024-01-15T09:00:00Z"])
        assert lines(stdout) == [2, 3, 4]


class TestOneSpellingOfATime:
    """Every entry time in every command's JSON is what `search` prints for the line."""

    @pytest.fixture
    def precision_log(self, tmp_path):
        """A whole-second, a millisecond and a microsecond time (lines 1, 2, 3)."""
        path = tmp_path / "precision.log"
        path.write_text(
            "2024-01-15 10:00:00 INFO whole\n"
            "2024-01-15 10:00:00.123 INFO millis\n"
            "2024-01-15 10:00:00.123456 INFO micros\n"
        )
        return str(path)

    def _search_times(self, path):
        _, stdout, _ = invoke(["search", path, "--compact"])
        return {e["ln"]: e["ts"] for e in json.loads(stdout)["results"]}

    def test_search_spelling_is_the_reference(self, precision_log):
        assert self._search_times(precision_log) == {
            1: "2024-01-15T10:00:00Z",
            2: "2024-01-15T10:00:00.123Z",
            3: "2024-01-15T10:00:00.123456Z",
        }

    def test_emit_matches_search(self, precision_log):
        _, stdout, _ = invoke(["emit", precision_log])
        got = {e["line_number"]: e["timestamp"] for e in map(json.loads, stdout.splitlines())}
        assert got == self._search_times(precision_log)

    def test_emit_compact_matches_search(self, precision_log):
        _, stdout, _ = invoke(["emit", precision_log, "--compact"])
        got = {e["ln"]: e["ts"] for e in map(json.loads, stdout.splitlines())}
        assert got == self._search_times(precision_log)

    def test_summarize_time_range_is_first_and_last_in_that_spelling(self, precision_log):
        _, stdout, _ = invoke(["summarize", precision_log])
        assert json.loads(stdout)["stats"]["time_range"] == {
            "start": "2024-01-15T10:00:00Z",
            "end": "2024-01-15T10:00:00.123456Z",
        }

    def test_schema_time_range_is_in_that_spelling(self, precision_log):
        _, stdout, _ = invoke(["schema", precision_log])
        assert json.loads(stdout)["time_range"] == {
            "earliest": "2024-01-15T10:00:00Z",
            "latest": "2024-01-15T10:00:00.123456Z",
        }

    def test_verify_pattern_first_and_last_match_are_in_that_spelling(self, precision_log):
        _, stdout, _ = invoke(["verify-pattern", precision_log, "--pattern", "INFO"])
        stats = json.loads(stdout)["statistics"]
        assert (stats["first_match"], stats["last_match"]) == (
            "2024-01-15T10:00:00Z",
            "2024-01-15T10:00:00.123456Z",
        )

    def test_correlate_events_anchor_time_is_in_that_spelling(self, tmp_path):
        path = tmp_path / "events.log"
        path.write_text(
            "2024-01-15T10:00:14Z INFO motor slowing\n"
            "2024-01-15T10:00:15Z ERROR motor stalled\n"
            "2024-01-15T10:00:16Z INFO motor restarting\n"
        )
        _, stdout, _ = invoke(
            ["correlate-events", "-f", str(path), "--trigger-level", "ERROR", "--window", "3s"]
        )
        assert [c["anchor_timestamp"] for c in json.loads(stdout)["clusters"]] == [
            "2024-01-15T10:00:15Z"
        ]
