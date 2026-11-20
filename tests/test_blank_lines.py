"""A line that is empty or holds only white space is not an entry, anywhere.

Line numbers still count it, so a number is the line of the file. White space is what
Python's ``str.strip()`` removes.
"""

import json
from io import StringIO

import pytest
from click.testing import CliRunner
from rich.console import Console

from logler.cli import main
from logler.investigate import Investigator, get_context, get_metadata, search
from logler.log_reader import CompleteLines, LogReader
from logler.parser import is_blank_line, read_entry_lines
from tests.conftest import invoke

A = b"2024-01-15T10:00:00Z INFO a\n"
B = b"2024-01-15T10:00:05Z INFO b\n"
# a, an empty line, three spaces, one tab, b: b is line 5
FIVE = A + b"\n   \n\t\n" + B


@pytest.fixture
def five(tmp_path):
    path = tmp_path / "five.log"
    path.write_bytes(FIVE)
    return str(path)


def _file(tmp_path, data: bytes) -> str:
    path = tmp_path / "x.log"
    path.write_bytes(data)
    return str(path)


def test_the_predicate_is_what_strip_removes():
    blank = ["", " ", "   ", "\t", "\r", "\x0b", "\x0c", "\x1c", "\x1f", "\xa0", "\u3000", "\u2003"]
    assert all(is_blank_line(text) for text in blank)
    assert all(text.strip() == "" for text in blank)
    assert not any(is_blank_line(text) for text in ["a", " a ", "\x00", "​", "0"])


def test_the_entry_lines_of_a_file_keep_the_numbers_of_the_file(five):
    assert list(read_entry_lines(five)) == [
        (1, "2024-01-15T10:00:00Z INFO a"),
        (5, "2024-01-15T10:00:05Z INFO b"),
    ]


class TestEngine:
    def test_search_finds_two_entries_on_lines_one_and_five(self, five):
        found = search([five], limit=10)
        assert found["total_matches"] == 2
        assert [r["entry"]["line_number"] for r in found["results"]] == [1, 5]
        assert [r["entry"]["message"] for r in found["results"]] == [
            "2024-01-15T10:00:00Z INFO a",
            "2024-01-15T10:00:05Z INFO b",
        ]

    def test_the_metadata_counts_five_lines_and_two_entries(self, five):
        (meta,) = get_metadata([five])
        assert (meta["lines"], meta["entry_count"]) == (5, 2)
        assert meta["log_levels"] == {"INFO": 2}

    def test_the_quick_summary_counts_five_lines_and_two_entries(self, five):
        from logler.helpers import quick_summary

        summary = quick_summary([five])
        assert (summary["total_lines"], summary["total_entries"]) == (5, 2)

    def test_context_is_counted_in_entries(self, five):
        context = get_context(five, 5, lines_before=1, lines_after=1)
        assert context["target"]["line_number"] == 5
        assert [e["line_number"] for e in context["context_before"]] == [1]
        assert context["context_after"] == []

    def test_search_context_is_counted_in_entries(self, five):
        found = search([five], query="b", context_lines=1, limit=10)
        (result,) = found["results"]
        assert [e["line_number"] for e in result["context_before"]] == [1]

    def test_sql_has_two_rows(self, five):
        inv = Investigator()
        inv.load_files([five])
        rows = inv.sql_query("SELECT line_number FROM logs ORDER BY line_number")
        assert rows == [{"line_number": 1}, {"line_number": 5}]

    def test_a_blank_line_between_two_entries_of_a_thread_changes_nothing(self, tmp_path):
        path = _file(
            tmp_path,
            b'{"timestamp":"2024-01-15T10:00:00Z","level":"INFO","message":"one","thread_id":"t"}\n'
            b"\n   \n"
            b'{"timestamp":"2024-01-15T10:00:01Z","level":"INFO","message":"two","thread_id":"t"}\n',
        )
        from logler.investigate import follow_thread

        result = follow_thread([path], thread_id="t")
        assert [(e["line_number"], e["message"]) for e in result["entries"]] == [
            (1, "one"),
            (4, "two"),
        ]
        assert result["total_entries"] == 2

    def test_a_blank_line_inside_a_stack_trace_keeps_the_other_numbers(self, tmp_path):
        path = _file(
            tmp_path,
            b"2024-01-15T10:00:00Z ERROR boom\nTraceback:\n  File x\n\n  File y\nValueError: z\n",
        )
        found = search([path], limit=10)
        assert [r["entry"]["line_number"] for r in found["results"]] == [1, 2, 3, 5, 6]


class TestHostileFiles:
    @pytest.mark.parametrize(
        "data",
        [b"\n", b"\n\n\n", b"   \n\t\n", b"  ", b"\r\n\r\n", b"\xc2\xa0\n", b"\xc2\xa0"],
    )
    def test_a_file_of_only_blank_lines_has_no_entries(self, tmp_path, data):
        path = _file(tmp_path, data)
        assert search([path], limit=10)["total_matches"] == 0
        assert get_metadata([path])[0]["entry_count"] == 0
        code, out, _ = invoke(["search", path])
        assert code == 1, out
        code, out, _ = invoke(["emit", path])
        assert (code, out) == (1, "")
        code, out, _ = invoke(["sql", "SELECT * FROM logs", "-f", path])
        assert json.loads(out)["results"] == []
        result = CliRunner().invoke(main, ["stats", path, "--json"])
        assert json.loads(result.stdout)["total"] == 0

    def test_it_ends_without_a_newline_or_in_three_newlines(self, tmp_path):
        for tail, count in ((b"b", 2), (b"b\n\n\n", 2)):
            path = _file(tmp_path, A + b"\n" + tail.replace(b"b", B.strip()))
            found = search([path], limit=10)
            assert [r["entry"]["line_number"] for r in found["results"]] == [1, 3]
            assert get_metadata([path])[0]["entry_count"] == count

    def test_crlf_line_ends_with_a_blank_line(self, tmp_path):
        path = _file(
            tmp_path, A.replace(b"\n", b"\r\n") + b"\r\n\r\r\n" + B.replace(b"\n", b"\r\n")
        )
        found = search([path], limit=10)
        assert [(r["entry"]["line_number"], r["entry"]["message"]) for r in found["results"]] == [
            (1, "2024-01-15T10:00:00Z INFO a"),
            (4, "2024-01-15T10:00:05Z INFO b"),
        ]

    def test_a_no_break_space_line_is_blank(self, tmp_path):
        path = _file(tmp_path, A + b"\xc2\xa0\n" + B)
        assert [r["entry"]["line_number"] for r in search([path], limit=10)["results"]] == [1, 3]
        assert [n for n, _ in read_entry_lines(path)] == [1, 3]


class TestLlmCommands:
    def test_the_commands_that_read_lines_themselves_count_two(self, five):
        _, out, _ = invoke(["emit", five])
        assert [json.loads(line)["line_number"] for line in out.splitlines()] == [1, 5]
        _, out, _ = invoke(["summarize", five])
        assert json.loads(out)["stats"]["total_entries"] == 2
        _, out, _ = invoke(["schema", five])
        assert json.loads(out)["total_entries"] == 2
        _, out, _ = invoke(["verify-pattern", five, "--pattern", "INFO"])
        assert json.loads(out)["statistics"]["total_entries"] == 2
        _, out, _ = invoke(["search", five])
        assert [r["line_number"] for r in json.loads(out)["results"]] == [1, 5]

    def test_schema_counts_the_sample_in_lines(self, tmp_path):
        """--sample-size is a number of lines of the file, blank ones too."""
        path = _file(tmp_path, A + b"\n\n" + B + B)
        _, out, _ = invoke(["schema", path, "--sample-size", "4"])
        assert json.loads(out)["total_entries"] == 2

    def test_the_sql_command_has_two_rows(self, five):
        code, out, _ = invoke(
            ["sql", "SELECT line_number FROM logs ORDER BY line_number", "-f", five]
        )
        assert code == 0
        data = json.loads(out)
        assert data["results"] == [{"line_number": 1}, {"line_number": 5}]
        assert data["total_entries"] == 2

    def test_format_test_tests_the_lines_that_are_entries(self, five):
        _, out, _ = invoke(["format", "test", "-f", five, "--regex", r"(?P<ts>\S+) .*"])
        data = json.loads(out)
        assert data["total_lines"] == 2
        assert [(r["line_number"], r["matched"]) for r in data["results"]] == [(1, True), (5, True)]

    def test_diff_counts_two(self, five):
        _, out, _ = invoke(
            [
                "diff",
                five,
                "--before-start",
                "2024-01-15T10:00:00",
                "--before-end",
                "2024-01-15T10:00:10",
                "--after-start",
                "2024-01-15T11:00:00",
                "--after-end",
                "2024-01-15T12:00:00",
            ]
        )
        assert json.loads(out)["comparison"]["before"]["total"] == 2


class TestHumanCommands:
    def test_stats_counts_two(self, five):
        result = CliRunner().invoke(main, ["stats", five, "--json"])
        assert json.loads(result.stdout)["total"] == 2

    def test_view_prints_two_entries_with_their_line_numbers(self, five):
        result = CliRunner().invoke(main, ["view", five, "--no-color"])
        assert result.exit_code == 0, result.output
        printed = [line.split() for line in result.output.splitlines() if "INFO" in line]
        assert [(p[0], p[-1]) for p in printed] == [("1", "a"), ("5", "b")]

    def test_the_follow_prints_nothing_for_a_blank_line(self, tmp_path):
        from logler.parser import LogParser
        from logler.terminal import TerminalViewer

        path = tmp_path / "follow.log"
        path.write_bytes(b"")
        viewer = TerminalViewer()
        buffer = StringIO()
        viewer.console = Console(file=buffer, width=100, color_system=None)
        parser = LogParser.for_file(str(path))
        with open(path, "rb") as f:
            growing = CompleteLines(f)
            with open(path, "ab") as out:
                out.write(b"\n   \n\t\n" + B)
            number = viewer._print_new_lines(growing, 0, None, None, None, parser)
        assert number == 4
        assert [line.split()[0] for line in buffer.getvalue().splitlines()] == ["4"]


class TestLogReader:
    def test_tail_search_and_read_skip_blank_lines(self, five):
        reader = LogReader(five)
        assert reader.tail(2) is not None
        assert list(reader.tail(2)) == [
            "2024-01-15T10:00:00Z INFO a",
            "2024-01-15T10:00:05Z INFO b",
        ]
        assert list(reader.tail(1)) == ["2024-01-15T10:00:05Z INFO b"]
        assert list(reader.read_lines()) == [
            "2024-01-15T10:00:00Z INFO a",
            "2024-01-15T10:00:05Z INFO b",
        ]
        assert list(reader.read_lines(reverse=True)) == [
            "2024-01-15T10:00:05Z INFO b",
            "2024-01-15T10:00:00Z INFO a",
        ]
        assert [n for n, _ in reader.search("INFO")] == [1, 5]

    def test_start_line_counts_the_lines_of_the_file_in_both_directions(self, tmp_path):
        path = _file(tmp_path, b"\n" + A + B + b"   \n")
        reader = LogReader(path)
        b_line, a_line = B.decode().strip(), A.decode().strip()
        # Line 1 is blank: skipping one line from the start skips it and no entry.
        assert list(reader.read_lines(start_line=1)) == [a_line, b_line]
        # The last line is blank: skipping one line from the end skips it and no entry.
        assert list(reader.read_lines(start_line=1, reverse=True)) == [b_line, a_line]
        assert list(reader.read_lines(start_line=2, reverse=True)) == [a_line]
        assert list(reader.read_lines(start_line=1, max_lines=1, reverse=True)) == [b_line]

    def test_the_followed_tail_skips_a_blank_line(self, tmp_path):
        path = _file(tmp_path, A + b"\n   \n" + B)
        lines = LogReader(path).tail(5, follow=True, sleep_interval=0)
        assert [next(lines), next(lines)] == [
            "2024-01-15T10:00:00Z INFO a",
            "2024-01-15T10:00:05Z INFO b",
        ]


class TestFormatDetection:
    def test_a_line_of_white_space_is_not_a_sample_line(self, tmp_path):
        from logler.format_detector import detect_format

        rows = [b'{"level":"info","msg":"m%d"}' % i for i in range(4)]
        (tmp_path / "plain").mkdir()
        (tmp_path / "spaced").mkdir()
        plain = _file(tmp_path / "plain", b"\n".join(rows) + b"\n")
        spaced = _file(tmp_path / "spaced", b"\n   \n\t\n\xc2\xa0\n".join(rows) + b"\n")
        want, got = detect_format(plain), detect_format(spaced)
        assert (got.format, got.sample_size, got.match_rate, got.mixed) == (
            want.format,
            4,
            want.match_rate,
            False,
        )
        assert got.sample_lines == want.sample_lines
