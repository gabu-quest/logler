"""Integration tests for which format parses a file.

``format_for_file`` is the one owner of that question: it finds .logler/formats.yaml from the
file's own directory and returns the first format whose file_patterns match the file's name.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from logler.config import format_for_file


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

    def test_config_that_cannot_be_loaded_gives_none(self, tmp_path: Path) -> None:
        """Broken YAML does not raise: the file reads with the built-in detection."""
        _write_config(tmp_path, "not: valid: yaml: {{{")
        log_file = tmp_path / "plc_001.log"
        log_file.write_text("test\n")

        assert format_for_file(str(log_file)) is None

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
