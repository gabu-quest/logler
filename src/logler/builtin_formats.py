"""
Built-in log format definitions for common log formats.

These are available as a base library that users can reference or override
in their .logler/formats.yaml config files.
"""

from __future__ import annotations

from typing import Dict, Optional

from .config import FormatConfig


def _fmt(
    regex: str,
    timestamp_format: Optional[str] = None,
    file_patterns: Optional[list[str]] = None,
) -> FormatConfig:
    """Shorthand to create a FormatConfig."""
    return FormatConfig(
        regex=regex,
        timestamp_format=timestamp_format,
        file_patterns=file_patterns or [],
    )


# =============================================================================
# Built-in Format Definitions
# =============================================================================

BUILTIN_FORMATS: Dict[str, FormatConfig] = {
    # ---- Web Servers ----
    "nginx_access": _fmt(
        regex=(
            r"(?P<remote_addr>[\d.]+) - (?P<remote_user>\S+) "
            r'\[(?P<timestamp>[^\]]+)\] "(?P<method>\w+) (?P<path>\S+) \S+" '
            r"(?P<status>\d+) (?P<body_bytes>\d+) "
            r'"(?P<referer>[^"]*)" "(?P<message>[^"]*)"'
        ),
        timestamp_format="%d/%b/%Y:%H:%M:%S %z",
        file_patterns=["access.log", "access.log.*", "nginx_access*.log"],
    ),
    "nginx_error": _fmt(
        regex=(
            r"(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) "
            r"\[(?P<level>\w+)\] (?P<pid>\d+)#(?P<tid>\d+): "
            r"(?P<message>.*)"
        ),
        timestamp_format="%Y/%m/%d %H:%M:%S",
        file_patterns=["error.log", "error.log.*", "nginx_error*.log"],
    ),
    "apache_access": _fmt(
        regex=(
            r"(?P<remote_addr>[\d.]+) \S+ \S+ "
            r'\[(?P<timestamp>[^\]]+)\] "(?P<method>\w+) (?P<path>\S+) \S+" '
            r"(?P<status>\d+) (?P<body_bytes>\d+|-)"
        ),
        timestamp_format="%d/%b/%Y:%H:%M:%S %z",
        file_patterns=["apache_access*.log", "httpd-access*.log"],
    ),
    "apache_error": _fmt(
        regex=(
            r"\[(?P<timestamp>[^\]]+)\] \[(?P<module>\w+):(?P<level>\w+)\] "
            r"\[pid (?P<pid>\d+)\] (?P<message>.*)"
        ),
        file_patterns=["apache_error*.log", "httpd-error*.log"],
    ),
    # ---- Java / JVM ----
    "log4j": _fmt(
        regex=(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
            r"(?P<level>\w+)\s+"
            r"\[(?P<thread_id>[^\]]+)\] "
            r"(?P<logger>\S+) - (?P<message>.*)"
        ),
        timestamp_format="%Y-%m-%d %H:%M:%S,%f",
        file_patterns=["*.log4j", "log4j*.log"],
    ),
    "logback": _fmt(
        regex=(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) "
            r"\[(?P<thread_id>[^\]]+)\] "
            r"(?P<level>\w+)\s+"
            r"(?P<logger>\S+) - (?P<message>.*)"
        ),
        timestamp_format="%Y-%m-%d %H:%M:%S.%f",
        file_patterns=["logback*.log"],
    ),
    # ---- Go ----
    "go_slog_text": _fmt(
        regex=(
            r"time=(?P<timestamp>\S+) "
            r"level=(?P<level>\w+) "
            r"(?:source=(?P<source>\S+) )?"
            r"msg=(?P<message>.*)"
        ),
        file_patterns=["*.slog", "slog*.log"],
    ),
    # ---- Docker ----
    "docker_json": _fmt(
        regex=(
            r'\{"log":"(?P<message>[^"]*)",'
            r'"stream":"(?P<stream>\w+)",'
            r'"time":"(?P<timestamp>[^"]+)"\}'
        ),
        file_patterns=["*-json.log"],
    ),
    # ---- System Logs ----
    "syslog_bsd": _fmt(
        regex=(
            r"(?P<timestamp>\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}) "
            r"(?P<hostname>\S+) "
            r"(?P<program>[\w/.-]+)(?:\[(?P<pid>\d+)\])?: "
            r"(?P<message>.*)"
        ),
        file_patterns=["syslog", "syslog.*", "messages", "messages.*"],
    ),
    "systemd_journal": _fmt(
        regex=(
            r"(?P<timestamp>\w{3} \d{2} \d{2}:\d{2}:\d{2}) "
            r"(?P<hostname>\S+) "
            r"(?P<unit>\S+)\[(?P<pid>\d+)\]: "
            r"(?P<message>.*)"
        ),
        file_patterns=["journal*.log"],
    ),
    # ---- Python ----
    "python_logging": _fmt(
        regex=(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
            r"(?P<level>\w+)\s+"
            r"(?P<logger>\S+) "
            r"(?P<message>.*)"
        ),
        timestamp_format="%Y-%m-%d %H:%M:%S,%f",
        file_patterns=["python*.log"],
    ),
    # ---- Databases ----
    "postgresql": _fmt(
        regex=(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \w+) "
            r"\[(?P<pid>\d+)\] "
            r"(?P<level>\w+): "
            r"(?P<message>.*)"
        ),
        timestamp_format="%Y-%m-%d %H:%M:%S.%f %Z",
        file_patterns=["postgresql*.log", "pg*.log"],
    ),
    "mysql": _fmt(
        regex=(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z) "
            r"(?P<thread_id>\d+) "
            r"\[(?P<level>\w+)\] "
            r"(?P<message>.*)"
        ),
        file_patterns=["mysql*.log", "mysqld*.log"],
    ),
    # ---- Ruby ----
    "ruby_logger": _fmt(
        regex=(
            r"(?P<level>[A-Z]), "
            r"\[(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+) "
            r"#(?P<pid>\d+)\]\s+"
            r"(?P<severity>\w+) -- (?P<logger>\S*): "
            r"(?P<message>.*)"
        ),
        file_patterns=["ruby*.log", "rails*.log"],
    ),
}


def get_builtin_formats() -> Dict[str, FormatConfig]:
    """Return all built-in format definitions."""
    return dict(BUILTIN_FORMATS)


def get_builtin_format(name: str) -> FormatConfig | None:
    """Look up a single built-in format by name."""
    return BUILTIN_FORMATS.get(name)


def list_builtin_format_names() -> list[str]:
    """Return sorted list of all built-in format names."""
    return sorted(BUILTIN_FORMATS.keys())
