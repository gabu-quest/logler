"""An all-zero trace, span or parent span id is no id (W3C trace context, B3, OpenTelemetry)."""

from __future__ import annotations

import json

import pytest

from logler.investigate import extract_ids
from logler.parser import LogParser

ZERO_TRACE = "0" * 32
ZERO_SPAN = "0" * 16


def _ids(entry):
    return (entry.trace_id, entry.span_id, entry.parent_span_id)


def test_json_zero_ids_are_none():
    line = json.dumps(
        {
            "message": "x",
            "trace_id": ZERO_TRACE,
            "span_id": ZERO_SPAN,
            "parent_span_id": ZERO_SPAN,
        }
    )
    assert _ids(LogParser().parse_line(1, line)) == (None, None, None)


def test_json_camel_case_zero_ids_are_none():
    line = json.dumps(
        {"message": "x", "traceId": ZERO_TRACE, "spanId": ZERO_SPAN, "parentSpanId": ZERO_SPAN}
    )
    assert _ids(LogParser().parse_line(1, line)) == (None, None, None)


def test_logfmt_zero_ids_are_none():
    line = (
        f'level=info msg="x" trace_id={ZERO_TRACE} span_id={ZERO_SPAN} parent_span_id={ZERO_SPAN}'
    )
    assert _ids(LogParser().parse_line(1, line)) == (None, None, None)


def test_plain_zero_ids_are_none():
    line = f"2024-01-02 13:14:15 INFO trace_id={ZERO_TRACE} span_id={ZERO_SPAN} Message text"
    assert _ids(LogParser().parse_line(1, line)) == (None, None, None)


def test_custom_group_zero_ids_are_none():
    regex = r"(?P<level>[A-Z]+)\|(?P<trace_id>\w+)\|(?P<span_id>\w+)\|(?P<parent_span_id>\w+)\|(?P<message>.+)"
    line = f"INFO|{ZERO_TRACE}|{ZERO_SPAN}|{ZERO_SPAN}|hello"
    entry = LogParser(custom_regex=regex).parse_line(1, line)
    assert entry.message == "hello"
    assert _ids(entry) == (None, None, None)


def test_a_zero_parent_under_a_real_span_leaves_the_span():
    line = json.dumps(
        {"message": "x", "trace_id": "ab" * 16, "span_id": "cd" * 8, "parent_span_id": ZERO_SPAN}
    )
    assert _ids(LogParser().parse_line(1, line)) == ("ab" * 16, "cd" * 8, None)


def test_a_zero_trace_id_of_the_other_length_is_none():
    line = json.dumps({"message": "x", "trace_id": ZERO_SPAN, "span_id": ZERO_TRACE})
    assert _ids(LogParser().parse_line(1, line)) == (None, None, None)


@pytest.mark.parametrize(
    "kept", ["0" * 8, "0", "0" * 15, "0" * 17, "0" * 31, "0" * 33, "0" * 15 + "1"]
)
def test_other_zero_looking_ids_are_kept(kept):
    line = json.dumps({"message": "x", "trace_id": kept, "span_id": kept, "parent_span_id": kept})
    assert _ids(LogParser().parse_line(1, line)) == (kept, kept, kept)


def test_lines_outside_any_span_are_no_trace(tmp_path):
    lines = [
        json.dumps({"message": f"idle {i}", "trace_id": ZERO_TRACE, "span_id": ZERO_SPAN})
        for i in range(100)
    ]
    lines.append(json.dumps({"message": "a", "trace_id": "a" * 32, "span_id": "1" * 16}))
    lines.append(json.dumps({"message": "b", "trace_id": "b" * 32, "span_id": "2" * 16}))
    path = tmp_path / "otel.log"
    path.write_text("\n".join(lines) + "\n")

    ids = extract_ids([str(path)])

    assert sorted(item["id"] for item in ids["trace_ids"]) == ["a" * 32, "b" * 32]
