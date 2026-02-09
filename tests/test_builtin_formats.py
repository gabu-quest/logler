"""Tests for logler.builtin_formats - built-in log format library."""

from __future__ import annotations

import re

from logler.builtin_formats import (
    BUILTIN_FORMATS,
    get_builtin_format,
    get_builtin_formats,
    list_builtin_format_names,
)


# Sample log lines for each format (at least 3 per format where possible)
SAMPLE_LINES = {
    "nginx_access": [
        '192.168.1.1 - frank [10/Oct/2024:13:55:36 -0700] "GET /api/v1/users HTTP/1.1" 200 4523 "https://example.com" "Mozilla/5.0"',
        '10.0.0.5 - - [10/Oct/2024:13:55:37 -0700] "POST /login HTTP/1.1" 302 0 "-" "curl/7.68.0"',
        '172.16.0.100 - admin [10/Oct/2024:13:55:38 -0700] "DELETE /api/v1/sessions HTTP/1.1" 204 0 "-" "HTTPie/3.2"',
    ],
    "nginx_error": [
        "2024/10/10 13:55:36 [error] 1234#5678: *99 connect() failed (111: Connection refused)",
        "2024/10/10 13:55:37 [warn] 1234#5678: *100 upstream timed out",
        "2024/10/10 13:55:38 [notice] 1234#0: signal process started",
    ],
    "apache_access": [
        '192.168.1.1 - frank [10/Oct/2024:13:55:36 -0700] "GET /index.html HTTP/1.1" 200 4523',
        '10.0.0.5 - - [10/Oct/2024:13:55:37 -0700] "POST /submit HTTP/1.1" 302 -',
        '172.16.0.1 - admin [10/Oct/2024:13:55:38 -0700] "HEAD /health HTTP/1.1" 200 0',
    ],
    "apache_error": [
        "[Wed Oct 10 13:55:36.123456 2024] [core:error] [pid 1234] something went wrong",
        "[Wed Oct 10 13:55:37.654321 2024] [mpm_prefork:notice] [pid 1] Apache/2.4 configured",
        "[Wed Oct 10 13:55:38.000000 2024] [ssl:warn] [pid 5678] certificate expiring soon",
    ],
    "log4j": [
        "2024-10-10 13:55:36,123 ERROR [main] com.example.App - Database connection failed",
        "2024-10-10 13:55:37,456 INFO  [http-nio-8080-exec-1] com.example.UserController - User login",
        "2024-10-10 13:55:38,789 WARN  [scheduler-1] com.example.CacheManager - Cache miss rate high",
    ],
    "logback": [
        "2024-10-10 13:55:36.123 [main] ERROR com.example.App - Startup failed",
        "2024-10-10 13:55:37.456 [http-1] INFO  com.example.Api - Request received",
        "2024-10-10 13:55:38.789 [async-1] DEBUG com.example.Cache - Cache hit",
    ],
    "go_slog_text": [
        "time=2024-10-10T13:55:36Z level=ERROR msg=database connection failed",
        "time=2024-10-10T13:55:37Z level=INFO source=main.go:42 msg=server started on port 8080",
        "time=2024-10-10T13:55:38Z level=WARN msg=deprecated API called",
    ],
    "docker_json": [
        '{"log":"Starting application...","stream":"stdout","time":"2024-10-10T13:55:36.123Z"}',
        '{"log":"Error: connection refused","stream":"stderr","time":"2024-10-10T13:55:37.456Z"}',
        '{"log":"Request handled in 42ms","stream":"stdout","time":"2024-10-10T13:55:38.789Z"}',
    ],
    "syslog_bsd": [
        "Oct 10 13:55:36 webserver nginx[1234]: upstream timed out",
        "Oct 10 13:55:37 dbhost postgres[5678]: connection received from 10.0.0.1",
        "Oct  5 13:55:38 appserver app/worker[9012]: job completed",
    ],
    "systemd_journal": [
        "Oct 10 13:55:36 myhost sshd[1234]: Accepted publickey for user from 10.0.0.1",
        "Oct 10 13:55:37 myhost systemd[1]: Started Docker Service",
        "Oct 10 13:55:38 myhost kernel[0]: Out of memory: Killed process 1234",
    ],
    "python_logging": [
        "2024-10-10 13:55:36,123 ERROR root Something went wrong",
        "2024-10-10 13:55:37,456 INFO  django.request Request processed",
        "2024-10-10 13:55:38,789 DEBUG myapp.core Cache updated",
    ],
    "postgresql": [
        "2024-10-10 13:55:36.123 UTC [1234] ERROR: relation does not exist",
        "2024-10-10 13:55:37.456 UTC [5678] LOG: checkpoint starting: time",
        "2024-10-10 13:55:38.789 UTC [9012] WARNING: there is no transaction in progress",
    ],
    "mysql": [
        "2024-10-10T13:55:36.123456Z 1 [Warning] InnoDB: page_cleaner took too long",
        "2024-10-10T13:55:37.654321Z 2 [Note] Server hostname: localhost",
        "2024-10-10T13:55:38.000000Z 3 [Error] Table not found",
    ],
    "ruby_logger": [
        "I, [2024-10-10T13:55:36.123456 #1234]  INFO -- : Started GET /users",
        "E, [2024-10-10T13:55:37.654321 #5678] ERROR -- myapp: Unhandled exception",
        "W, [2024-10-10T13:55:38.000000 #9012]  WARN -- : Deprecated method called",
    ],
}


class TestBuiltinFormatsParseSampleLines:
    """Each built-in format must parse at least 3 realistic log lines."""

    def test_all_formats_have_samples(self) -> None:
        """Every built-in format has sample lines defined for testing."""
        for name in BUILTIN_FORMATS:
            assert name in SAMPLE_LINES, f"No sample lines for format {name!r}"

    def test_each_format_parses_its_samples(self) -> None:
        """Every format's regex matches all its sample lines with non-empty groups."""
        for name, fmt in BUILTIN_FORMATS.items():
            compiled = re.compile(fmt.regex)
            samples = SAMPLE_LINES[name]
            assert len(samples) >= 3, f"Format {name!r} needs at least 3 sample lines"

            for i, line in enumerate(samples):
                match = compiled.match(line)
                assert (
                    match is not None
                ), f"Format {name!r} failed to match sample line {i}: {line!r}"
                # Verify at least one named group captured something
                groups = match.groupdict()
                non_empty = {k: v for k, v in groups.items() if v is not None}
                assert non_empty, f"Format {name!r} matched line {i} but all groups are None"

    def test_message_group_captures_content(self) -> None:
        """Formats with a 'message' group capture actual message content."""
        for name, fmt in BUILTIN_FORMATS.items():
            compiled = re.compile(fmt.regex)
            if "message" not in compiled.groupindex:
                continue

            for line in SAMPLE_LINES[name]:
                match = compiled.match(line)
                if match:
                    msg = match.group("message")
                    assert (
                        msg is not None and len(msg) > 0
                    ), f"Format {name!r} has empty message for: {line!r}"


class TestBuiltinFormatRegistry:
    """Test the format lookup functions."""

    def test_get_builtin_formats_returns_all(self) -> None:
        """get_builtin_formats returns a copy with all defined formats."""
        formats = get_builtin_formats()
        assert len(formats) == len(BUILTIN_FORMATS)
        # Must be a copy, not the original
        formats["test"] = None  # type: ignore
        assert "test" not in BUILTIN_FORMATS

    def test_get_builtin_format_existing(self) -> None:
        """Looking up an existing format returns the FormatConfig."""
        fmt = get_builtin_format("nginx_access")
        assert fmt is not None
        assert "remote_addr" in fmt.regex

    def test_get_builtin_format_missing(self) -> None:
        """Looking up a non-existent format returns None."""
        assert get_builtin_format("nonexistent_format") is None

    def test_list_builtin_format_names_sorted(self) -> None:
        """list_builtin_format_names returns sorted names."""
        names = list_builtin_format_names()
        assert names == sorted(names)
        assert len(names) == len(BUILTIN_FORMATS)

    def test_all_formats_have_file_patterns(self) -> None:
        """Every built-in format has at least one file pattern."""
        for name, fmt in BUILTIN_FORMATS.items():
            assert len(fmt.file_patterns) > 0, f"Format {name!r} has no file_patterns"

    def test_all_formats_have_named_groups(self) -> None:
        """Every built-in format regex has named capture groups."""
        for name, fmt in BUILTIN_FORMATS.items():
            compiled = re.compile(fmt.regex)
            assert compiled.groupindex, f"Format {name!r} has no named capture groups"
