"""Integration tests for which format parses a file.

``format_for_file`` is the one owner of that question: it finds .logler/formats.yaml from the
file's own directory and returns the first format whose file_patterns match the file's name.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from logler.config import FormatFileError, format_for_file


def _write_config(tmp_path: Path, body: str) -> None:
    config_dir = tmp_path / ".logler"
    config_dir.mkdir()
    (config_dir / "formats.yaml").write_text(textwrap.dedent(body))


class TestFormatForFile:
    """format_for_file, one case per rule."""

    def test_returns_format_when_config_matches(self, tmp_path: Path) -> None:
        """A matching config gives that format."""
        _write_config(
            tmp_path,
            """\
            formats:
              plc:
                regex: '(?P<timestamp>[\\d/]+ [\\d:.]+) (?P<level>\\w+) (?P<message>.*)'
                file_patterns: ["plc_*.log"]
            """,
        )
        log_file = tmp_path / "plc_001.log"
        log_file.write_text("test\n")

        fmt = format_for_file(str(log_file))
        assert fmt is not None
        assert fmt.regex == "(?P<timestamp>[\\d/]+ [\\d:.]+) (?P<level>\\w+) (?P<message>.*)"
        assert fmt.file_patterns == ["plc_*.log"]

    def test_returns_none_when_no_config(self, tmp_path: Path) -> None:
        """No .logler/formats.yaml anywhere above the file gives None."""
        log_file = tmp_path / "app.log"
        log_file.write_text("test\n")

        assert format_for_file(str(log_file)) is None

    def test_returns_none_when_no_match(self, tmp_path: Path) -> None:
        """A config that names other files gives None."""
        _write_config(
            tmp_path,
            """\
            formats:
              plc:
                regex: '(?P<message>.+)'
                file_patterns: ["plc_*.log"]
            """,
        )
        log_file = tmp_path / "application.log"
        log_file.write_text("test\n")

        assert format_for_file(str(log_file)) is None

    def test_files_matching_different_formats_each_get_their_own(self, tmp_path: Path) -> None:
        """Two files that match different formats are not tied to one regex."""
        _write_config(
            tmp_path,
            """\
            formats:
              plc:
                regex: '(?P<plc_msg>.+)'
                file_patterns: ["plc_*.log"]
              sensor:
                regex: '(?P<sensor_msg>.+)'
                file_patterns: ["sensor_*.log"]
            """,
        )
        plc_file = tmp_path / "plc_001.log"
        plc_file.write_text("test\n")
        sensor_file = tmp_path / "sensor_temp.log"
        sensor_file.write_text("test\n")

        plc = format_for_file(str(plc_file))
        sensor = format_for_file(str(sensor_file))
        assert plc is not None
        assert plc.regex == "(?P<plc_msg>.+)"
        assert sensor is not None
        assert sensor.regex == "(?P<sensor_msg>.+)"

    def test_files_matching_the_same_format_both_get_it(self, tmp_path: Path) -> None:
        """Two files of one format get that format."""
        _write_config(
            tmp_path,
            """\
            formats:
              plc:
                regex: '(?P<plc_msg>.+)'
                file_patterns: ["plc_*.log"]
            """,
        )
        f1 = tmp_path / "plc_001.log"
        f1.write_text("test\n")
        f2 = tmp_path / "plc_002.log"
        f2.write_text("test\n")

        for log_file in (f1, f2):
            fmt = format_for_file(str(log_file))
            assert fmt is not None
            assert fmt.regex == "(?P<plc_msg>.+)"

    @pytest.mark.parametrize(
        ("body", "words"),
        [
            ("not: valid: yaml: {{{", "Invalid YAML"),
            ("- just\n- a list\n", "mapping"),
            (
                "formats:\n  plc:\n    file_patterns: ['*.log']\n",
                "formats.yaml: formats.plc.regex: Field required",
            ),
            ("formats:\n  plc:\n    regex: '(?P<m>[unclosed'\n", "plc"),
            # the Rust engine refuses this one, and the format does not name the log file
            (
                "formats:\n  other:\n    regex: '(?=x)(?P<m>.+)'\n    file_patterns: ['x_*.log']\n",
                "other",
            ),
        ],
        ids=["broken_yaml", "top_level_list", "no_regex", "python_regex", "rust_regex_unmatched"],
    )
    def test_a_config_that_cannot_be_used_is_an_error(
        self, tmp_path: Path, body: str, words: str
    ) -> None:
        """The error names the file and the problem, for a file no format names too."""
        _write_config(tmp_path, body)
        log_file = tmp_path / "app.log"
        log_file.write_text("test\n")

        with pytest.raises(FormatFileError) as raised:
            format_for_file(str(log_file))
        assert str(tmp_path / ".logler" / "formats.yaml") in str(raised.value)
        assert words in str(raised.value)

    def test_a_config_that_is_not_utf8_is_an_error(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "")
        (tmp_path / ".logler" / "formats.yaml").write_bytes(b"formats: \xff\xfe\n")

        with pytest.raises(FormatFileError, match="utf-8"):
            format_for_file(str(tmp_path / "app.log"))

    def test_an_empty_config_is_no_formats(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "")

        assert format_for_file(str(tmp_path / "app.log")) is None

    def test_a_broken_config_two_folders_up_is_an_error(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "not: valid: yaml: {{{")
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)

        with pytest.raises(FormatFileError, match="Invalid YAML"):
            format_for_file(str(deep / "app.log"))

    def test_a_kept_failure_is_raised_as_a_new_error_each_time(self, tmp_path: Path) -> None:
        """One error object raised again and again grows its traceback for the life of a server."""
        _write_config(tmp_path, "not: valid: yaml: {{{")
        raised = []
        for _ in range(2):
            with pytest.raises(FormatFileError) as info:
                format_for_file(str(tmp_path / "app.log"))
            raised.append(info.value)

        assert raised[0] is not raised[1]
        assert str(raised[0]) == str(raised[1])

    def test_a_fixed_config_is_read_by_the_next_call(self, tmp_path: Path) -> None:
        """A failure is kept per (mtime, size) of the file, not for the process."""
        _write_config(tmp_path, "not: valid: yaml: {{{")
        log_file = tmp_path / "plc_001.log"
        with pytest.raises(FormatFileError):
            format_for_file(str(log_file))

        config = tmp_path / ".logler" / "formats.yaml"
        config.write_text(
            "formats:\n  plc:\n    regex: '(?P<message>.+)'\n    file_patterns: ['plc_*.log']\n"
        )
        stat = config.stat()
        os.utime(config, (stat.st_atime + 10, stat.st_mtime + 10))

        fmt = format_for_file(str(log_file))
        assert fmt is not None and fmt.regex == "(?P<message>.+)"

    def test_unmatched_file_beside_a_matched_one(self, tmp_path: Path) -> None:
        """The unmatched file gets None and the matched file its format."""
        _write_config(
            tmp_path,
            """\
            formats:
              plc:
                regex: '(?P<plc_msg>.+)'
                file_patterns: ["plc_*.log"]
            """,
        )
        plc_file = tmp_path / "plc_001.log"
        plc_file.write_text("test\n")
        other_file = tmp_path / "random.txt"
        other_file.write_text("test\n")

        plc = format_for_file(str(plc_file))
        assert plc is not None
        assert plc.regex == "(?P<plc_msg>.+)"
        assert format_for_file(str(other_file)) is None
