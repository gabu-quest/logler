"""``query`` and ``exclude_query``: one regex each, matched without regard to letter case,
over the whole line as it is written in the file and the message read from it."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from logler.cache import clear_cache
from logler.cli import main
from logler.investigate import Investigator, search

JSON_LOG = (
    '{"time":"2024-01-15T10:00:00Z","level":"error","msg":"payment failed",'
    '"err":"connection refused","order":"A-17"}\n'
    '{"time":"2024-01-15T10:00:01Z","level":"info","msg":"payment ok","order":"A-18"}\n'
    '{"time":"2024-01-15T10:00:02Z","level":"info","msg":"connection refused by peer"}\n'
)

PLAIN_LOG = (
    "2024-01-15T10:00:00Z INFO [w-1] connection refused by peer\n"
    "2024-01-15T10:00:01Z INFO [w-1] Timeout waiting for lock\n"
    "2024-01-15T10:00:02Z ERROR [w-2] user 42 logged in\n"
)

# Three JSON lines as json.dumps writes them by default: a quote in the message is \", and
# text outside ASCII is \uXXXX. Line 1 says: user said "no". Line 2: 日本語. Line 3: viel ärger.
ESCAPED_LOG = (
    '{"time":"2024-01-15T10:00:00Z","level":"info","msg":"user said \\"no\\"","n":1}\n'
    '{"time":"2024-01-15T10:00:01Z","level":"info","msg":"\\u65e5\\u672c\\u8a9e","n":2}\n'
    '{"time":"2024-01-15T10:00:02Z","level":"info","msg":"viel \\u00e4rger","n":3}\n'
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _write(tmp_path: Path, text: str, name: str = "app.log") -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _lines(path: str, **kwargs) -> list[int]:
    result = search([path], limit=0, context_lines=0, **kwargs)
    return [item["entry"]["line_number"] for item in result["results"]]


class TestOneRegexOverTheWholeLine:
    def test_a_value_in_another_json_field_is_found(self, tmp_path):
        path = _write(tmp_path, JSON_LOG)
        assert _lines(path, query="A-17") == [1]

    def test_a_phrase_in_a_field_beside_the_message_is_found(self, tmp_path):
        path = _write(tmp_path, JSON_LOG)
        assert _lines(path, query="connection refused") == [1, 3]

    def test_a_pattern_that_matches_a_key_name_matches_every_json_line(self, tmp_path):
        path = _write(tmp_path, JSON_LOG)
        assert _lines(path, query="level") == [1, 2, 3]

    def test_plain_text_without_regex_characters_finds_the_lines_that_hold_it(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="refused") == [1]

    def test_no_word_fallback(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="connection timeout") == []
        assert _lines(path, query="user \\d+ gone") == []

    def test_alternation_asks_for_either(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="timeout|refused") == [1, 2]

    def test_a_regex_character_class_matches(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="user \\d+") == [3]

    def test_letter_case_is_ignored(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="TIMEOUT WAITING") == [2]
        assert _lines(path, query="timeout waiting") == [2]

    def test_a_leading_inline_flag_of_the_user_wins(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="(?-i)timeout") == []
        assert _lines(path, query="(?-i)Timeout") == [2]

    def test_non_ascii_case_is_ignored(self, tmp_path):
        path = _write(tmp_path, "2024-01-15T10:00:00Z INFO [w] viel ärger hier\n")
        assert _lines(path, query="ÄRGER") == [1]

    def test_an_empty_query_is_no_filter(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="") == [1, 2, 3]

    def test_a_line_that_is_not_utf8_is_searched(self, tmp_path):
        path = tmp_path / "bytes.log"
        path.write_bytes(
            b"2024-01-15T10:00:00Z INFO [w] caf\xe9 broken\n2024-01-15T10:00:01Z INFO [w] fine\n"
        )
        assert _lines(str(path), query="broken") == [1]
        assert _lines(str(path), query="fine") == [2]

    def test_the_query_and_the_filters_both_apply(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, query="refused|user", level="ERROR") == [3]


class TestTheMessageAsItIsRead:
    """A JSON line holds its message with escapes; a pattern also finds the text they stand for."""

    def test_a_quoted_word_in_a_json_message_is_found(self, tmp_path):
        path = _write(tmp_path, ESCAPED_LOG)
        assert _lines(path, query='said "no"') == [1]

    def test_text_a_json_line_holds_as_unicode_escapes_is_found(self, tmp_path):
        path = _write(tmp_path, ESCAPED_LOG)
        assert _lines(path, query="日本語") == [2]
        assert _lines(path, query="ÄRGER") == [3]

    def test_the_line_as_written_is_still_found(self, tmp_path):
        path = _write(tmp_path, ESCAPED_LOG)
        assert _lines(path, query=r"\\u65e5") == [2]
        assert _lines(path, query='"n":[12]') == [1, 2]

    def test_an_anchor_holds_at_the_start_of_the_line_or_of_the_message(self, tmp_path):
        path = _write(tmp_path, ESCAPED_LOG)
        assert _lines(path, query="^user said") == [1]
        assert _lines(path, query=r"^\{") == [1, 2, 3]

    def test_exclude_query_leaves_out_a_line_whose_message_matches(self, tmp_path):
        path = _write(tmp_path, ESCAPED_LOG)
        assert _lines(path, exclude_query='said "no"') == [2, 3]
        assert _lines(path, exclude_query="日本語") == [1, 3]


class TestExcludeQuery:
    def test_letter_case_is_ignored(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, exclude_query="timeout") == [1, 3]
        assert _lines(path, exclude_query="TIMEOUT") == [1, 3]

    def test_it_looks_at_the_whole_line(self, tmp_path):
        path = _write(tmp_path, JSON_LOG)
        assert _lines(path, exclude_query="order") == [3]
        assert _lines(path, exclude_query="A-17") == [2, 3]

    def test_a_leading_inline_flag_of_the_user_wins(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        assert _lines(path, exclude_query="(?-i)timeout") == [1, 2, 3]

    def test_it_combines_with_the_query(self, tmp_path):
        path = _write(tmp_path, JSON_LOG)
        assert _lines(path, query="connection refused", exclude_query="A-17") == [3]


class TestResultOrderAndScore:
    def test_every_result_of_a_query_scores_one_and_comes_in_time_order(self, tmp_path):
        path = _write(
            tmp_path,
            "2024-01-15T10:00:05Z INFO [w] job done\n"
            "2024-01-15T10:00:01Z INFO [w] job\n"
            "2024-01-15T10:00:03Z INFO [w] job done and more words\n"
            "2024-01-15T10:00:04Z INFO [w] other\n",
        )
        result = search([path], query="job", limit=0, context_lines=0)
        assert [i["entry"]["line_number"] for i in result["results"]] == [2, 3, 1]
        assert [i["relevance_score"] for i in result["results"]] == [1.0, 1.0, 1.0]
        assert result["total_matches"] == 3


class TestInvalidPattern:
    def test_a_bad_query_raises_value_error_with_the_reason(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        with pytest.raises(ValueError) as info:
            search([path], query="(")
        assert str(info.value) == 'Invalid query pattern "(": unclosed group'

    def test_a_bad_exclude_query_raises_value_error_with_the_reason(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        with pytest.raises(ValueError) as info:
            search([path], exclude_query="[")
        assert str(info.value) == 'Invalid exclude pattern "[": unclosed character class'

    def test_the_investigator_method_raises_the_same(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        inv = Investigator()
        inv.load_files([path])
        with pytest.raises(ValueError) as info:
            inv.search(query="(")
        assert str(info.value) == 'Invalid query pattern "(": unclosed group'

    def test_llm_search_bad_query_is_exit_2(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        result = CliRunner().invoke(main, ["llm", "search", path, "--query", "("])
        assert result.exit_code == 2, result.output
        assert json.loads(result.output) == {
            "error": 'Invalid query pattern "(": unclosed group',
            "code": 2,
        }

    def test_llm_search_bad_exclude_query_is_exit_2(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        result = CliRunner().invoke(main, ["llm", "search", path, "--exclude-query", "["])
        assert result.exit_code == 2, result.output
        assert json.loads(result.output) == {
            "error": 'Invalid exclude pattern "[": unclosed character class',
            "code": 2,
        }

    def test_llm_emit_bad_query_is_exit_2(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        result = CliRunner().invoke(main, ["llm", "emit", path, "--query", "("])
        assert result.exit_code == 2, result.output
        assert json.loads(result.output) == {
            "error": 'Invalid query pattern "(": missing ), unterminated subpattern at position 0',
            "code": 2,
        }

    def test_llm_emit_bad_exclude_query_is_exit_2(self, tmp_path):
        path = _write(tmp_path, PLAIN_LOG)
        result = CliRunner().invoke(main, ["llm", "emit", path, "--exclude-query", "["])
        assert result.exit_code == 2, result.output
        assert json.loads(result.output) == {
            "error": 'Invalid exclude pattern "[": unterminated character set at position 0',
            "code": 2,
        }


class TestHostilePatterns:
    def test_a_pattern_of_ten_thousand_characters(self, tmp_path):
        path = _write(
            tmp_path,
            f"2024-01-15T10:00:00Z INFO [w] {'x' * 10_000}\n2024-01-15T10:00:01Z INFO [w] x\n",
        )
        assert _lines(path, query="x" * 10_000) == [1]
        assert _lines(path, exclude_query="x" * 10_000) == [2]

    def test_a_nested_quantifier_on_a_long_line_returns_in_bounded_time(self, tmp_path):
        path = _write(tmp_path, f"2024-01-15T10:00:00Z INFO [w] {'a' * 100_000}b\n")
        started = time.perf_counter()
        assert _lines(path, query="(a+)+$") == []
        assert _lines(path, exclude_query="(a+)+$") == [1]
        assert time.perf_counter() - started < 5


class TestSearchAndEmitAgree:
    @pytest.mark.parametrize(
        "pattern",
        [
            "A-17",
            "connection refused",
            "CONNECTION",
            "level",
            "payment (ok|failed)",
            "zzz",
            "peer$",
        ],
    )
    @pytest.mark.parametrize("flag", ["--query", "--exclude-query"])
    def test_the_same_pattern_gives_the_same_lines(self, tmp_path, pattern, flag):
        path = _write(tmp_path, JSON_LOG)
        found = _lines(path, **{flag[2:].replace("-", "_"): pattern})
        result = CliRunner().invoke(main, ["llm", "emit", path, flag, pattern, "--compact"])
        emitted = [json.loads(line)["ln"] for line in result.output.splitlines()]
        assert emitted == found

    @pytest.mark.parametrize(
        ("pattern", "lines"),
        [('said "no"', [1]), ("日本語", [2]), ("^viel", [3]), (r"\\u00e4", [3])],
    )
    def test_both_read_the_message_as_well_as_the_line(self, tmp_path, pattern, lines):
        path = _write(tmp_path, ESCAPED_LOG)
        assert _lines(path, query=pattern) == lines
        result = CliRunner().invoke(main, ["llm", "emit", path, "--query", pattern, "--compact"])
        assert [json.loads(line)["ln"] for line in result.output.splitlines()] == lines
