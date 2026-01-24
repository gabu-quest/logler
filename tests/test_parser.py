"""Tests for the new parser implementation."""

from datetime import datetime, timezone

from logler.parser import LogEntry, LogParser


def test_parse_json_entry():
    parser = LogParser()
    line = '{"timestamp": "2024-01-01T12:00:00Z", "level": "info", "message": "Test message", "thread": "worker-1", "correlation_id": "abc123", "trace_id": "feedfacefeedface", "span_id": "cafebabe", "service": "auth", "extra": {"user": 42}}'

    entry = parser.parse_line(1, line)

    assert isinstance(entry, LogEntry)
    assert entry.line_number == 1
    assert entry.timestamp == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert entry.level == "INFO"
    assert entry.message == "Test message"
    assert entry.thread_id == "worker-1"
    assert entry.correlation_id == "abc123"
    assert entry.trace_id == "feedfacefeedface"
    assert entry.span_id == "cafebabe"
    assert entry.service_name == "auth"
    assert entry.fields["extra"] == {"user": 42}


def test_parse_plain_entry_extracts_metadata():
    parser = LogParser()
    line = "2024-01-02 13:14:15 INFO [thread-9] correlation_id=xyz trace_id=abcdabcdabcdabcd span_id=1234123412341234 Message text"

    entry = parser.parse_line(5, line)

    assert entry.line_number == 5
    assert entry.timestamp == datetime(2024, 1, 2, 13, 14, 15)
    assert entry.level == "INFO"
    assert entry.thread_id == "thread-9"
    assert entry.correlation_id == "xyz"
    assert entry.trace_id == "abcdabcdabcdabcd"
    assert entry.span_id == "1234123412341234"
    assert "Message text" in entry.message


def test_parse_invalid_json_falls_back_to_plain():
    parser = LogParser()
    bad_json = '{"timestamp": "2024-01-01"'  # missing closing brace

    entry = parser.parse_line(2, bad_json)

    assert entry.line_number == 2
    assert entry.message == bad_json
    assert entry.level == "UNKNOWN"


def test_plain_entry_without_metadata_uses_raw_message():
    parser = LogParser()
    line = "Just a simple line without metadata"

    entry = parser.parse_line(3, line)

    assert entry.message == line
    assert entry.level == "UNKNOWN"


def test_service_name_propagates_from_json():
    parser = LogParser()
    line = '{"timestamp":"2024-01-01T00:00:00Z","level":"INFO","service":"payments","message":"ok"}'
    entry = parser.parse_line(1, line)
    assert entry.service_name == "payments"
    assert entry.level == "INFO"
    assert entry.timestamp is not None
