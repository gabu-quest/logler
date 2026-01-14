"""
BRUTAL PARSER TESTS - No Mercy Edition

These tests exist to break the parser in every conceivable way.
If your parser survives this gauntlet, it might be production-ready.
"""

import pytest
import json
from logler.parser import LogParser


class TestMalformedJSON:
    """JSON parsing must not crash on garbage input."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_truncated_json_mid_key(self, parser):
        """JSON cut off mid-key name"""
        entry = parser.parse_line(1, '{"timesta')
        assert entry.level == "UNKNOWN"
        assert entry.message == '{"timesta'

    def test_truncated_json_mid_value(self, parser):
        """JSON cut off mid-value"""
        entry = parser.parse_line(1, '{"message": "hello wor')
        assert entry.message == '{"message": "hello wor'

    def test_truncated_json_mid_unicode_escape(self, parser):
        """JSON cut off mid-unicode escape sequence"""
        entry = parser.parse_line(1, '{"message": "test\\u00')
        assert entry.line_number == 1

    def test_nested_unclosed_braces(self, parser):
        """Deeply nested unclosed braces"""
        entry = parser.parse_line(1, '{"a":{"b":{"c":{"d":')
        assert entry.level == "UNKNOWN"

    def test_json_with_trailing_garbage(self, parser):
        """Valid JSON followed by garbage"""
        entry = parser.parse_line(1, '{"message": "ok"}garbage after')
        # Should fall back to plain text since json.loads will fail
        assert entry.line_number == 1

    def test_json_with_null_bytes(self, parser):
        """JSON with null bytes embedded"""
        entry = parser.parse_line(1, '{"message": "test\x00null\x00bytes"}')
        assert entry.line_number == 1

    def test_json_with_control_characters(self, parser):
        """JSON with unescaped control characters"""
        entry = parser.parse_line(1, '{"message": "line1\nline2\ttab"}')
        assert entry.line_number == 1

    def test_json_number_overflow(self, parser):
        """JSON with absurdly large numbers"""
        huge_num = "9" * 500
        entry = parser.parse_line(1, f'{{"count": {huge_num}}}')
        assert entry.line_number == 1

    def test_json_deeply_nested_arrays(self, parser):
        """JSON with deeply nested arrays"""
        nested = "[" * 100 + "1" + "]" * 100
        entry = parser.parse_line(1, f'{{"data": {nested}}}')
        assert entry.line_number == 1

    def test_json_duplicate_keys(self, parser):
        """JSON with duplicate keys (last wins in Python)"""
        entry = parser.parse_line(1, '{"message": "first", "message": "second"}')
        # Python json.loads takes the last value
        assert "second" in entry.message or entry.level == "UNKNOWN"

    def test_json_unicode_key(self, parser):
        """JSON with unicode key names"""
        entry = parser.parse_line(1, '{"時間": "2024-01-01", "メッセージ": "テスト"}')
        assert entry.line_number == 1

    def test_json_empty_object(self, parser):
        """Empty JSON object"""
        entry = parser.parse_line(1, "{}")
        assert entry.level == "UNKNOWN"
        assert entry.message == "{}"

    def test_json_empty_string_values(self, parser):
        """JSON with empty string values"""
        entry = parser.parse_line(1, '{"message": "", "level": "", "thread": ""}')
        assert entry.line_number == 1

    def test_json_null_values(self, parser):
        """JSON with null values for all fields"""
        entry = parser.parse_line(1, '{"message": null, "level": null, "timestamp": null}')
        assert entry.line_number == 1

    def test_json_boolean_as_string_field(self, parser):
        """JSON with boolean where string expected"""
        entry = parser.parse_line(1, '{"message": true, "level": false}')
        assert entry.line_number == 1

    def test_json_array_as_message(self, parser):
        """JSON with array as message"""
        entry = parser.parse_line(1, '{"message": ["part1", "part2"]}')
        assert entry.line_number == 1

    def test_json_object_as_message(self, parser):
        """JSON with object as message"""
        entry = parser.parse_line(1, '{"message": {"nested": "value"}}')
        assert entry.line_number == 1

    def test_json_scientific_notation_timestamp(self, parser):
        """JSON with scientific notation where timestamp expected"""
        entry = parser.parse_line(1, '{"timestamp": 1.7e12, "message": "test"}')
        assert entry.line_number == 1


class TestTimestampEdgeCases:
    """Timestamps are a minefield. Test every trap."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_timestamp_missing_year(self, parser):
        """Timestamp without year"""
        entry = parser.parse_line(1, "01-15 10:30:00 INFO Test")
        assert entry.level == "INFO"

    def test_timestamp_two_digit_year(self, parser):
        """Two-digit year format"""
        entry = parser.parse_line(1, "24-01-15 10:30:00 INFO Test")
        # Should fail to parse as ISO, level still extracted
        assert entry.level == "INFO"

    def test_timestamp_american_format(self, parser):
        """American date format MM/DD/YYYY"""
        entry = parser.parse_line(1, "01/15/2024 10:30:00 ERROR Failed")
        assert entry.level == "ERROR"

    def test_timestamp_european_format(self, parser):
        """European date format DD/MM/YYYY"""
        entry = parser.parse_line(1, "15/01/2024 10:30:00 ERROR Failed")
        assert entry.level == "ERROR"

    def test_timestamp_epoch_seconds(self, parser):
        """Unix epoch in seconds"""
        entry = parser.parse_line(1, "1705320000 INFO Epoch seconds")
        assert entry.level == "INFO"

    def test_timestamp_epoch_milliseconds(self, parser):
        """Unix epoch in milliseconds"""
        entry = parser.parse_line(1, "1705320000000 INFO Epoch millis")
        assert entry.level == "INFO"

    def test_timestamp_with_microseconds(self, parser):
        """Timestamp with microsecond precision"""
        entry = parser.parse_line(1, "2024-01-15T10:30:00.123456Z INFO Test")
        assert entry.timestamp is not None
        assert entry.level == "INFO"

    def test_timestamp_with_nanoseconds(self, parser):
        """Timestamp with nanosecond precision"""
        entry = parser.parse_line(1, "2024-01-15T10:30:00.123456789Z INFO Test")
        assert entry.level == "INFO"

    def test_timestamp_positive_offset(self, parser):
        """Timestamp with positive timezone offset"""
        entry = parser.parse_line(1, "2024-01-15T10:30:00+05:30 INFO Test")
        assert entry.timestamp is not None

    def test_timestamp_negative_offset(self, parser):
        """Timestamp with negative timezone offset"""
        entry = parser.parse_line(1, "2024-01-15T10:30:00-08:00 INFO Test")
        assert entry.timestamp is not None

    def test_timestamp_offset_without_colon(self, parser):
        """Timezone offset without colon"""
        entry = parser.parse_line(1, "2024-01-15T10:30:00+0530 INFO Test")
        assert entry.level == "INFO"

    def test_timestamp_z_suffix(self, parser):
        """Explicit Z (Zulu/UTC) suffix"""
        entry = parser.parse_line(1, '{"timestamp": "2024-01-15T10:30:00Z", "level": "INFO"}')
        assert entry.timestamp is not None
        assert entry.timestamp.tzinfo is not None

    def test_timestamp_space_separator(self, parser):
        """Space separator instead of T"""
        entry = parser.parse_line(1, "2024-01-15 10:30:00 INFO Test")
        assert entry.timestamp is not None
        assert entry.level == "INFO"

    def test_timestamp_leap_second(self, parser):
        """Leap second (60 seconds)"""
        entry = parser.parse_line(1, "2024-06-30T23:59:60Z INFO Leap second")
        # Python may or may not accept :60, but shouldn't crash
        assert entry.level == "INFO"

    def test_timestamp_february_29_leap_year(self, parser):
        """Feb 29 in leap year"""
        entry = parser.parse_line(1, "2024-02-29T10:30:00Z INFO Leap day")
        assert entry.timestamp is not None

    def test_timestamp_february_29_non_leap_year(self, parser):
        """Feb 29 in non-leap year (invalid)"""
        entry = parser.parse_line(1, "2023-02-29T10:30:00Z INFO Invalid date")
        # Should not crash, timestamp might be None
        assert entry.level == "INFO"

    def test_timestamp_future_year(self, parser):
        """Far future timestamp"""
        entry = parser.parse_line(1, "2999-12-31T23:59:59Z INFO Future")
        assert entry.level == "INFO"

    def test_timestamp_past_year(self, parser):
        """Historical timestamp"""
        entry = parser.parse_line(1, "1970-01-01T00:00:00Z INFO Epoch start")
        assert entry.timestamp is not None

    def test_timestamp_negative_year(self, parser):
        """BCE date (negative year)"""
        entry = parser.parse_line(1, "-0044-03-15T12:00:00 INFO Beware the Ides")
        assert entry.level == "INFO"

    def test_json_timestamp_as_number(self, parser):
        """Timestamp as epoch number in JSON"""
        entry = parser.parse_line(1, '{"timestamp": 1705320000, "message": "test"}')
        assert entry.line_number == 1


class TestLogLevelEdgeCases:
    """Log level extraction edge cases."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    @pytest.mark.parametrize(
        "level_str,expected",
        [
            ("TRACE", "TRACE"),
            ("trace", "TRACE"),
            ("Trace", "TRACE"),
            ("DEBUG", "DEBUG"),
            ("debug", "DEBUG"),
            ("INFO", "INFO"),
            ("INFORMATION", "INFORMATION"),
            ("WARN", "WARN"),
            ("WARNING", "WARNING"),
            ("warn", "WARN"),
            ("ERROR", "ERROR"),
            ("ERR", "ERR"),
            ("error", "ERROR"),
            ("FATAL", "FATAL"),
            ("fatal", "FATAL"),
            ("CRITICAL", "CRITICAL"),
            ("CRIT", "CRIT"),
        ],
    )
    def test_level_case_variations(self, parser, level_str, expected):
        """Test all level case variations"""
        entry = parser.parse_line(1, f"2024-01-01T00:00:00Z {level_str} Message")
        assert entry.level == expected

    def test_level_embedded_in_word(self, parser):
        """Level embedded in another word shouldn't match incorrectly"""
        entry = parser.parse_line(1, "INFORMATION about DEBUGGING the ERROR in WARNING systems")
        # Should pick the first valid level
        assert entry.level in ["INFORMATION", "DEBUG", "ERROR", "WARN"]

    def test_level_in_message_not_prefix(self, parser):
        """Level word in message body"""
        entry = parser.parse_line(1, "Something happened ERROR occurred")
        assert entry.level == "ERROR"

    def test_no_level_present(self, parser):
        """No log level in line at all"""
        entry = parser.parse_line(1, "2024-01-01T00:00:00Z Just a message")
        assert entry.level == "UNKNOWN"

    def test_syslog_priority_emergency(self, parser):
        """Syslog priority 0 - Emergency"""
        entry = parser.parse_line(1, "<0>Jan 15 10:30:00 host process: Emergency!")
        # Parser uses regex, should at least not crash
        assert entry.line_number == 1

    def test_syslog_priority_error(self, parser):
        """Syslog priority 3 - Error"""
        entry = parser.parse_line(1, "<3>Jan 15 10:30:00 host process: Error occurred")
        assert entry.line_number == 1

    def test_syslog_priority_info(self, parser):
        """Syslog priority 6 - Info"""
        entry = parser.parse_line(1, "<14>Jan 15 10:30:00 host process: Info message")
        assert entry.line_number == 1

    def test_json_level_variations(self, parser):
        """Different JSON key names for level"""
        for key in ["level", "severity", "loglevel", "lvl"]:
            entry = parser.parse_line(1, f'{{"{key}": "error", "message": "test"}}')
            assert entry.level == "ERROR"


class TestIDExtractionEdgeCases:
    """Thread ID, correlation ID, trace ID, span ID extraction tests."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_thread_id_with_hyphens(self, parser):
        """Thread ID with hyphens"""
        entry = parser.parse_line(1, "2024-01-01T00:00:00Z INFO [main-worker-1] Message")
        assert entry.thread_id == "main-worker-1"

    def test_thread_id_with_underscores(self, parser):
        """Thread ID with underscores"""
        entry = parser.parse_line(1, "2024-01-01T00:00:00Z INFO [worker_pool_3] Message")
        assert entry.thread_id == "worker_pool_3"

    def test_thread_id_numeric(self, parser):
        """Purely numeric thread ID"""
        entry = parser.parse_line(1, "2024-01-01T00:00:00Z INFO tid=12345 Message")
        assert entry.thread_id == "12345"

    def test_thread_id_uuid_format(self, parser):
        """Thread ID in UUID format"""
        entry = parser.parse_line(1, "thread=a1b2c3d4-e5f6-7890-abcd-ef1234567890 INFO Message")
        assert entry.thread_id is not None

    def test_correlation_id_various_formats(self, parser):
        """Different correlation ID key formats"""
        # Only test formats that the plain text parser regex supports
        # (see LogParser.PATTERNS["correlation_id"])
        supported_variants = [
            "correlation_id=abc123",
            "correlation-id=abc123",
            "request_id=abc123",
            "req_id=abc123",
        ]
        for variant in supported_variants:
            entry = parser.parse_line(1, f"2024-01-01T00:00:00Z INFO {variant} Message")
            assert entry.correlation_id is not None, f"Failed for: {variant}"

        # CamelCase variants may not be supported in plain text - test they don't crash
        camel_variants = [
            "correlationId=abc123",
            "requestId=abc123",
        ]
        for variant in camel_variants:
            entry = parser.parse_line(1, f"2024-01-01T00:00:00Z INFO {variant} Message")
            # May or may not extract - just verify no crash
            assert entry.line_number == 1

    def test_trace_id_16_hex(self, parser):
        """16-character hex trace ID"""
        entry = parser.parse_line(1, "trace_id=abcd1234abcd1234 INFO Message")
        assert entry.trace_id == "abcd1234abcd1234"

    def test_trace_id_32_hex(self, parser):
        """32-character hex trace ID (W3C format)"""
        entry = parser.parse_line(1, "trace_id=abcd1234abcd1234efgh5678efgh5678 INFO Message")
        assert entry.trace_id is not None

    def test_span_id_8_hex(self, parser):
        """8-character hex span ID"""
        entry = parser.parse_line(1, "span_id=abcd1234 INFO Message")
        assert entry.span_id == "abcd1234"

    def test_span_id_16_hex(self, parser):
        """16-character hex span ID"""
        entry = parser.parse_line(1, "span_id=abcd1234abcd1234 INFO Message")
        assert entry.span_id == "abcd1234abcd1234"

    def test_all_ids_in_one_line(self, parser):
        """All ID types in single line"""
        line = "2024-01-01T00:00:00Z INFO [worker-1] correlation_id=req-123 trace_id=abcd1234abcd1234 span_id=efef5678 Database query"
        entry = parser.parse_line(1, line)
        assert entry.thread_id == "worker-1"
        assert entry.correlation_id == "req-123"
        assert entry.trace_id == "abcd1234abcd1234"
        assert entry.span_id == "efef5678"

    def test_ids_in_json(self, parser):
        """All ID types in JSON"""
        line = json.dumps(
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "INFO",
                "thread_id": "worker-1",
                "correlation_id": "req-123",
                "trace_id": "abcd1234abcd1234",
                "span_id": "efef5678",
                "message": "Test",
            }
        )
        entry = parser.parse_line(1, line)
        assert entry.thread_id == "worker-1"
        assert entry.correlation_id == "req-123"
        assert entry.trace_id == "abcd1234abcd1234"
        assert entry.span_id == "efef5678"


class TestEncodingNightmares:
    """Encoding issues that cause real-world pain."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_utf8_message(self, parser):
        """Valid UTF-8 in message"""
        entry = parser.parse_line(1, "2024-01-01T00:00:00Z INFO こんにちは世界")
        assert "こんにちは" in entry.message

    def test_emoji_in_message(self, parser):
        """Emoji in log message"""
        entry = parser.parse_line(1, "2024-01-01T00:00:00Z INFO Deployment successful 🚀✅")
        assert "🚀" in entry.message

    def test_mixed_scripts(self, parser):
        """Mixed scripts: Latin, Cyrillic, Chinese, Arabic"""
        entry = parser.parse_line(1, "INFO Hello Привет 你好 مرحبا")
        assert entry.level == "INFO"

    def test_rtl_text(self, parser):
        """Right-to-left text (Arabic/Hebrew)"""
        entry = parser.parse_line(1, "INFO مرحبا بالعالم")
        assert entry.level == "INFO"

    def test_zero_width_characters(self, parser):
        """Zero-width characters that are invisible"""
        entry = parser.parse_line(1, "INFO Test\u200bMessage\u200cWith\u200dZero\ufeffWidth")
        assert entry.level == "INFO"

    def test_combining_characters(self, parser):
        """Unicode combining characters"""
        entry = parser.parse_line(1, "INFO Café résumé naïve")
        assert entry.level == "INFO"

    def test_mathematical_symbols(self, parser):
        """Mathematical and technical symbols"""
        entry = parser.parse_line(1, "INFO Result: x² + y² = r² → ∞")
        assert entry.level == "INFO"

    def test_private_use_area(self, parser):
        """Private Use Area characters"""
        entry = parser.parse_line(1, "INFO Custom: \ue000\ue001\uf000")
        assert entry.level == "INFO"


class TestExtremeInputs:
    """Edge cases that push boundaries."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_empty_string(self, parser):
        """Empty string input"""
        entry = parser.parse_line(1, "")
        assert entry.line_number == 1
        assert entry.message == ""

    def test_whitespace_only(self, parser):
        """Only whitespace"""
        entry = parser.parse_line(1, "   \t\n  ")
        assert entry.line_number == 1

    def test_single_character(self, parser):
        """Single character"""
        entry = parser.parse_line(1, "x")
        assert entry.message == "x"

    def test_very_long_line(self, parser):
        """Very long line (100KB)"""
        long_line = "INFO " + "x" * 100000
        entry = parser.parse_line(1, long_line)
        assert entry.level == "INFO"
        assert len(entry.message) == len(long_line)

    def test_many_fields_json(self, parser):
        """JSON with many fields"""
        data = {"timestamp": "2024-01-01T00:00:00Z", "level": "INFO", "message": "test"}
        data.update({f"field_{i}": f"value_{i}" for i in range(1000)})
        entry = parser.parse_line(1, json.dumps(data))
        assert entry.level == "INFO"
        assert len(entry.fields) >= 1000

    def test_deeply_nested_json(self, parser):
        """Deeply nested JSON structure"""
        data = {"timestamp": "2024-01-01T00:00:00Z", "level": "INFO", "message": "test"}
        nested = data
        for i in range(50):
            nested["child"] = {"level_" + str(i): i}
            nested = nested["child"]
        entry = parser.parse_line(1, json.dumps(data))
        assert entry.level == "INFO"

    def test_line_number_zero(self, parser):
        """Line number zero"""
        entry = parser.parse_line(0, "INFO Test")
        assert entry.line_number == 0

    def test_line_number_negative(self, parser):
        """Negative line number"""
        entry = parser.parse_line(-1, "INFO Test")
        assert entry.line_number == -1

    def test_line_number_huge(self, parser):
        """Very large line number"""
        entry = parser.parse_line(10**12, "INFO Test")
        assert entry.line_number == 10**12

    def test_repeated_timestamps(self, parser):
        """Multiple timestamps in one line"""
        entry = parser.parse_line(1, "2024-01-01T00:00:00Z 2024-01-02T00:00:00Z INFO Confusing")
        # Should pick one
        assert entry.timestamp is not None
        assert entry.level == "INFO"

    def test_timestamp_in_message(self, parser):
        """Timestamp that's part of the message, not a log timestamp"""
        entry = parser.parse_line(1, "INFO Scheduled for 2024-06-15T09:00:00Z")
        assert entry.level == "INFO"
        # May or may not extract the embedded timestamp


class TestRealWorldGarbage:
    """Real garbage that appears in production logs."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_binary_data_mixed_with_text(self, parser):
        """Binary garbage mixed with readable text"""
        entry = parser.parse_line(1, "INFO \x89PNG\r\n\x1a\n binary data here")
        assert entry.line_number == 1

    def test_stack_trace_multiline_as_single(self, parser):
        """Java stack trace that got mangled into single line"""
        entry = parser.parse_line(
            1,
            "ERROR java.lang.NullPointerException\tat com.example.Foo.bar(Foo.java:42)\tat com.example.Main.main(Main.java:10)",
        )
        assert entry.level == "ERROR"

    def test_json_log_with_embedded_json(self, parser):
        """JSON log containing escaped JSON in message"""
        inner = json.dumps({"user_id": 123, "action": "login"})
        outer = json.dumps(
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "INFO",
                "message": f"Received payload: {inner}",
            }
        )
        entry = parser.parse_line(1, outer)
        assert entry.level == "INFO"
        assert "Received payload" in entry.message

    def test_kubernetes_pod_log_format(self, parser):
        """Kubernetes-style log prefix"""
        entry = parser.parse_line(
            1, "2024-01-15T10:30:00.123456789Z stdout F INFO Application started"
        )
        assert entry.level == "INFO"

    def test_docker_compose_prefix(self, parser):
        """Docker compose log prefix"""
        entry = parser.parse_line(1, "web_1    | 2024-01-15T10:30:00Z INFO Server listening")
        assert entry.level == "INFO"

    def test_systemd_journal_format(self, parser):
        """Systemd journal output format"""
        entry = parser.parse_line(1, "Jan 15 10:30:00 hostname myapp[1234]: INFO Application event")
        assert entry.level == "INFO"

    def test_nginx_access_log(self, parser):
        """nginx access log format"""
        entry = parser.parse_line(
            1,
            '192.168.1.1 - - [15/Jan/2024:10:30:00 +0000] "GET /api/health HTTP/1.1" 200 15 "-" "curl/7.68.0"',
        )
        assert entry.line_number == 1

    def test_apache_error_log(self, parser):
        """Apache error log format"""
        entry = parser.parse_line(
            1,
            "[Mon Jan 15 10:30:00.123456 2024] [error] [pid 1234] [client 192.168.1.1:54321] ModSecurity: Access denied",
        )
        assert entry.level in ["ERROR", "UNKNOWN"]

    def test_python_logging_default(self, parser):
        """Python logging default format"""
        entry = parser.parse_line(1, "INFO:myapp.module:This is the message")
        assert entry.level == "INFO"

    def test_go_zap_production(self, parser):
        """Go Zap logger production format"""
        line = '{"level":"info","ts":1705320000.123,"caller":"main.go:42","msg":"server started","port":8080}'
        entry = parser.parse_line(1, line)
        assert entry.level == "INFO"

    def test_rust_tracing_format(self, parser):
        """Rust tracing crate format"""
        entry = parser.parse_line(
            1, "2024-01-15T10:30:00.123456Z  INFO myapp::server: Listening on 0.0.0.0:8080"
        )
        assert entry.level == "INFO"

    def test_elixir_logger_format(self, parser):
        """Elixir/Erlang logger format"""
        entry = parser.parse_line(1, "10:30:00.123 [info] Application myapp started")
        assert entry.level == "INFO"


class TestServiceNameExtraction:
    """Service name extraction for distributed tracing."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_service_name_in_json(self, parser):
        """Service name from JSON field"""
        for field in ["service", "service_name", "serviceName"]:
            entry = parser.parse_line(1, f'{{"{field}": "auth-service", "message": "test"}}')
            assert entry.service_name == "auth-service"

    def test_service_name_with_version(self, parser):
        """Service name with version suffix"""
        entry = parser.parse_line(1, '{"service": "api-gateway-v2", "message": "test"}')
        assert entry.service_name == "api-gateway-v2"

    def test_service_name_with_env(self, parser):
        """Service name with environment suffix"""
        entry = parser.parse_line(1, '{"service": "payment-service-prod", "message": "test"}')
        assert entry.service_name == "payment-service-prod"


class TestFieldStorage:
    """Extra fields storage in entry.fields."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    def test_extra_fields_preserved(self, parser):
        """Non-standard fields stored in entry.fields"""
        line = json.dumps(
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "INFO",
                "message": "test",
                "user_id": 42,
                "request_path": "/api/users",
                "response_time_ms": 150.5,
            }
        )
        entry = parser.parse_line(1, line)
        assert entry.fields["user_id"] == 42
        assert entry.fields["request_path"] == "/api/users"
        assert entry.fields["response_time_ms"] == 150.5

    def test_nested_extra_fields(self, parser):
        """Nested objects in extra fields"""
        line = json.dumps(
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "INFO",
                "message": "test",
                "context": {
                    "user": {"id": 42, "name": "alice"},
                    "request": {"method": "POST", "path": "/api/orders"},
                },
            }
        )
        entry = parser.parse_line(1, line)
        assert entry.fields["context"]["user"]["id"] == 42

    def test_array_extra_fields(self, parser):
        """Array values in extra fields"""
        line = json.dumps(
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "level": "INFO",
                "message": "test",
                "tags": ["production", "critical", "payment"],
                "errors": [{"code": 1, "msg": "err1"}, {"code": 2, "msg": "err2"}],
            }
        )
        entry = parser.parse_line(1, line)
        assert entry.fields["tags"] == ["production", "critical", "payment"]
        assert len(entry.fields["errors"]) == 2
