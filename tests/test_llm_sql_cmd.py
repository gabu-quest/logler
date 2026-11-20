"""Tests for the `logler llm sql` command."""

import json
import os
import tempfile
from typing import ClassVar

import pytest

from tests.conftest import EXIT_SUCCESS, EXIT_USER_ERROR, invoke, run_llm_command


class TestSqlCommandSecurity:
    """Verify the logler llm sql command blocks DuckDB filesystem functions."""

    def test_sql_blocks_read_csv_auto(self, sample_log_file):
        """read_csv_auto must be blocked — prevents host file reads."""
        result = run_llm_command(
            [
                "sql",
                "SELECT * FROM read_csv_auto('/etc/passwd')",
                "-f",
                sample_log_file,
            ]
        )
        assert result.returncode == EXIT_USER_ERROR
        data = json.loads(result.stdout)
        assert "error" in data
        assert "file system operations are disabled" in data["error"].lower()

    def test_sql_blocks_copy_to(self, sample_log_file):
        """COPY ... TO must be blocked — prevents data exfiltration."""
        result = run_llm_command(
            [
                "sql",
                "COPY logs TO '/tmp/exfil.csv'",
                "-f",
                sample_log_file,
            ]
        )
        assert result.returncode == EXIT_USER_ERROR
        data = json.loads(result.stdout)
        assert "error" in data
        assert "file system operations are disabled" in data["error"].lower()


class TestSqlCommandBatching:
    """Verify the sql command handles large files via batched inserts."""

    def test_sql_large_file_batched(self):
        """Generate >5000 entries, run sql, verify correct total_entries count."""

        n_entries = 6_000
        lines = []
        for i in range(n_entries):
            ts = f"2024-01-15T10:00:{i % 60:02d}.{i:03d}Z"
            level = "INFO" if i % 5 != 0 else "ERROR"
            lines.append(f"{ts} {level} [worker-{i % 4}] Message number {i}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            log_path = f.name

        try:
            result = run_llm_command(
                [
                    "sql",
                    "SELECT COUNT(*) as cnt FROM logs",
                    "-f",
                    log_path,
                ]
            )
            assert result.returncode == EXIT_SUCCESS, result.stderr
            data = json.loads(result.stdout)
            assert data["total_entries"] == n_entries
            assert data["row_count"] == 1
            assert data["results"][0]["cnt"] == n_entries
        finally:
            os.unlink(log_path)

    def test_sql_count_by_level(self):
        """Batched insert preserves all fields correctly (level grouping)."""

        # 100 INFO + 50 ERROR = 150 entries
        lines = []
        for i in range(100):
            lines.append(f"2024-01-15T10:00:00.{i:03d}Z INFO [w-1] info msg {i}")
        for i in range(50):
            lines.append(f"2024-01-15T10:00:01.{i:03d}Z ERROR [w-2] error msg {i}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            log_path = f.name

        try:
            result = run_llm_command(
                [
                    "sql",
                    "SELECT level, COUNT(*) as cnt FROM logs GROUP BY level ORDER BY level",
                    "-f",
                    log_path,
                ]
            )
            assert result.returncode == EXIT_SUCCESS, result.stderr
            data = json.loads(result.stdout)
            assert data["total_entries"] == 150
            rows = {r["level"]: r["cnt"] for r in data["results"]}
            assert rows["ERROR"] == 50
            assert rows["INFO"] == 100
        finally:
            os.unlink(log_path)


class TestSqlOneLogsTable:
    """`logler llm sql` and `Investigator.sql_query` read one `logs` table and one `metrics`."""

    LOGS_COLUMNS: ClassVar[list[str]] = [
        "file",
        "line_number",
        "timestamp",
        "level",
        "message",
        "thread_id",
        "correlation_id",
        "trace_id",
        "span_id",
        "raw",
    ]

    @pytest.fixture
    def four_line_log(self, tmp_path):
        """Line 1 and 2: a time and a level; line 3: a time, no level; line 4: neither."""
        path = tmp_path / "four.log"
        path.write_text(
            "2024-01-15T10:00:00Z INFO first\n"
            "2024-01-15T10:00:01Z ERROR second\n"
            "2024-01-15T10:00:02Z third\n"
            "fourth\n"
        )
        return str(path)

    @pytest.fixture
    def two_numbers_log(self, tmp_path):
        """Three JSON lines, each with two numeric fields (x and y): 6 metrics rows."""
        path = tmp_path / "numbers.log"
        path.write_text(
            '{"timestamp": "2024-01-15T10:00:00Z", "level": "INFO", "message": "a", "x": 1, "y": 2}\n'
            '{"timestamp": "2024-01-15T10:00:01Z", "level": "INFO", "message": "b", "x": 3, "y": 4}\n'
            '{"timestamp": "2024-01-15T10:00:02Z", "level": "INFO", "message": "c", "x": 5, "y": 6}\n'
        )
        return str(path)

    @staticmethod
    def _command(query, path):
        code, out, _ = invoke(["sql", query, "-f", path])
        assert code == 0, out
        return json.loads(out)

    @staticmethod
    def _api(query, path):
        from logler.investigate import Investigator

        inv = Investigator()
        inv.load_files([path])
        return inv.sql_query(query)

    def test_a_time_with_a_zone_is_a_result_value(self, four_line_log):
        """DuckDB imports pytz to hand back a time that carries a zone: `now()` is one."""
        result = self._command("SELECT now() AS t", four_line_log)

        assert result["columns"] == ["t"]
        assert len(result["results"]) == 1
        value = result["results"][0]["t"]
        assert isinstance(value, str)
        assert value.endswith("Z")

    def test_select_star_is_the_same_through_both_doors(self, four_line_log):
        query = "SELECT * FROM logs ORDER BY line_number"

        command = self._command(query, four_line_log)
        api = self._api(query, four_line_log)

        assert command["columns"] == self.LOGS_COLUMNS
        assert command["results"] == api
        assert [r["line_number"] for r in api] == [1, 2, 3, 4]
        assert [r["timestamp"] for r in api] == [
            "2024-01-15T10:00:00Z",
            "2024-01-15T10:00:01Z",
            "2024-01-15T10:00:02Z",
            None,
        ]
        assert [r["file"] for r in api] == [four_line_log] * 4

    @pytest.mark.parametrize("bound", ["2024-01-15 09:00:00", "2024-01-15T09:00:00Z"])
    def test_a_time_filter_compares_times(self, three_hour_log, bound):
        data = self._command(
            f"SELECT count(*) AS n FROM logs WHERE timestamp > '{bound}'", three_hour_log
        )

        assert data["results"] == [{"n": 2}]

    def test_a_line_with_no_level_is_unknown_through_both_doors(self, four_line_log):
        query = "SELECT level, count(*) AS n FROM logs GROUP BY level ORDER BY level"

        command = self._command(query, four_line_log)["results"]
        api = self._api(query, four_line_log)

        assert command == api
        assert api == [
            {"level": "ERROR", "n": 1},
            {"level": "INFO", "n": 1},
            {"level": "UNKNOWN", "n": 2},
        ]

    def test_the_metrics_table_is_the_same_through_both_doors(self, two_numbers_log):
        query = "SELECT field_name, count(*) AS n FROM metrics GROUP BY field_name ORDER BY 1"

        command = self._command(query, two_numbers_log)["results"]
        api = self._api(query, two_numbers_log)

        assert command == api
        assert api == [{"field_name": "x", "n": 3}, {"field_name": "y", "n": 3}]
        assert self._command("SELECT count(*) AS n FROM metrics", two_numbers_log)["results"] == [
            {"n": 6}
        ]

    @pytest.mark.parametrize(
        ("query", "lines_read_for_metrics"),
        [
            ("SELECT count(*) AS n FROM logs", 0),
            ("SELECT count(*) AS n FROM metrics", 3),
            ("SHOW TABLES", 3),
        ],
    )
    def test_a_query_that_reads_only_logs_does_not_pay_for_metrics(
        self, two_numbers_log, monkeypatch, query, lines_read_for_metrics
    ):
        import logler.sql

        real = logler.sql.extract_numeric_fields
        lines = []

        def counting(entries):
            lines.extend(entries)
            return real(entries)

        monkeypatch.setattr(logler.sql, "extract_numeric_fields", counting)

        code, out, _ = invoke(["sql", query, "-f", two_numbers_log])

        assert code == 0, out
        assert len(lines) == lines_read_for_metrics

    def test_a_leap_second_is_the_last_second_of_its_minute_through_both_doors(self, tmp_path):
        """Second 60 is a real time a SQL TIMESTAMP cannot hold: the line loads as second 59,
        in `logs` and in `metrics`, and the lines around it load too."""
        path = tmp_path / "leap.log"
        path.write_text(
            '{"timestamp": "2016-12-31T23:59:59Z", "level": "INFO", "message": "a", "x": 1}\n'
            '{"timestamp": "2016-12-31T23:59:60Z", "level": "INFO", "message": "b", "x": 2}\n'
            '{"timestamp": "2017-01-01T00:00:00Z", "level": "INFO", "message": "c", "x": 3}\n'
        )
        times = ["2016-12-31T23:59:59Z", "2016-12-31T23:59:59Z", "2017-01-01T00:00:00Z"]

        for table in ("logs", "metrics"):
            query = f"SELECT line_number, timestamp FROM {table} ORDER BY line_number"

            command = self._command(query, str(path))["results"]
            api = self._api(query, str(path))

            assert command == api
            assert api == [
                {"line_number": n, "timestamp": time} for n, time in enumerate(times, start=1)
            ]

    def test_the_same_lines_through_both_doors(self, tmp_path):
        """A line ends at "\\n" or "\\r\\n" and nothing else is trimmed: a blank line and
        a line of spaces are no rows but keep their numbers, trailing spaces stay, and a carriage return
        inside a line (a progress display) is part of that line."""
        path = tmp_path / "lines.log"
        path.write_bytes(
            b"2024-01-15T10:00:00Z INFO one\n"
            b"\n"
            b"   \n"
            b"2024-01-15T10:00:01Z INFO two  \r\n"
            b"2024-01-15T10:00:02Z INFO 10%\r20%\n"
            b"2024-01-15T10:00:03Z INFO last, no newline\r"
        )
        query = "SELECT line_number, raw FROM logs ORDER BY line_number"

        command = self._command(query, str(path))
        api = self._api(query, str(path))

        assert command["results"] == api
        assert command["total_entries"] == 4
        assert [(r["line_number"], r["raw"]) for r in api] == [
            (1, "2024-01-15T10:00:00Z INFO one"),
            (4, "2024-01-15T10:00:01Z INFO two  "),
            (5, "2024-01-15T10:00:02Z INFO 10%\r20%"),
            (6, "2024-01-15T10:00:03Z INFO last, no newline\r"),
        ]

    @pytest.mark.parametrize(
        ("raw_bytes", "expected"),
        [
            (b"caf\xe9 here", "caf� here"),
            (b"a\x80b", "a�b"),
            (b"a\xe2\x82 b", "a� b"),
            (b"a\xc0\xafb", "a��b"),
            (b"a\xf5b", "a�b"),
            (b"a\x00b", "a\x00b"),
        ],
    )
    def test_a_byte_that_is_not_utf8_is_replaced_the_same_way_in_every_door(
        self, tmp_path, raw_bytes, expected
    ):
        """Bytes that are not UTF-8 do not fail the file: the line stays, the bad bytes are
        U+FFFD, and `search`, the API's SQL and `llm sql` (which cuts the file in Python) give
        the same line numbers and the same `raw`."""
        path = tmp_path / "bytes.log"
        path.write_bytes(
            b"2024-01-15T10:00:00Z INFO one\n2024-01-15T10:00:01Z INFO "
            + raw_bytes
            + b"\n2024-01-15T10:00:02Z INFO three\n"
        )
        expected_rows = [
            (1, "2024-01-15T10:00:00Z INFO one"),
            (2, "2024-01-15T10:00:01Z INFO " + expected),
            (3, "2024-01-15T10:00:02Z INFO three"),
        ]

        code, out, _ = invoke(["search", str(path)])
        assert code == 0, out
        found = [(r["line_number"], r["raw"]) for r in json.loads(out)["results"]]
        via_sql = [
            (r["line_number"], r["raw"])
            for r in self._api("SELECT line_number, raw FROM logs ORDER BY line_number", str(path))
        ]

        query = "SELECT line_number, raw FROM logs ORDER BY line_number"
        via_command = [
            (r["line_number"], r["raw"]) for r in self._command(query, str(path))["results"]
        ]

        assert sorted(found) == expected_rows
        assert via_sql == expected_rows
        assert via_command == expected_rows

    def test_a_character_cut_off_at_the_end_of_the_file_is_one_replacement(self, tmp_path):
        path = tmp_path / "cut.log"
        path.write_bytes(b"2024-01-15T10:00:00Z INFO one\n2024-01-15T10:00:01Z INFO end\xe2\x82")

        code, out, _ = invoke(["search", str(path)])
        assert code == 0, out
        found = sorted((r["line_number"], r["raw"]) for r in json.loads(out)["results"])
        via_sql = [
            (r["line_number"], r["raw"])
            for r in self._api("SELECT line_number, raw FROM logs ORDER BY line_number", str(path))
        ]

        expected_rows = [
            (1, "2024-01-15T10:00:00Z INFO one"),
            (2, "2024-01-15T10:00:01Z INFO end�"),
        ]
        query = "SELECT line_number, raw FROM logs ORDER BY line_number"
        via_command = [
            (r["line_number"], r["raw"]) for r in self._command(query, str(path))["results"]
        ]

        assert found == expected_rows
        assert via_sql == expected_rows
        assert via_command == expected_rows

    def test_a_byte_order_mark_is_not_part_of_line_one(self, tmp_path):
        """A JSON log saved with a BOM parses its first line as JSON, in both doors."""
        path = tmp_path / "bom.log"
        path.write_bytes(
            b"\xef\xbb\xbf"
            b'{"timestamp": "2024-01-15T10:00:00Z", "level": "ERROR", "message": "first"}\n'
            b'{"timestamp": "2024-01-15T10:00:01Z", "level": "INFO", "message": "second"}\n'
        )
        query = "SELECT line_number, level, message FROM logs ORDER BY line_number"

        assert self._api(query, str(path)) == [
            {"line_number": 1, "level": "ERROR", "message": "first"},
            {"line_number": 2, "level": "INFO", "message": "second"},
        ]
        code, out, _ = invoke(["search", str(path), "--level", "ERROR"])
        assert code == 0, out
        assert [r["message"] for r in json.loads(out)["results"]] == ["first"]

    def test_a_file_of_a_byte_order_mark_alone_has_no_lines(self, tmp_path):
        path = tmp_path / "bom_only.log"
        path.write_bytes(b"\xef\xbb\xbf")

        assert self._api("SELECT count(*) AS n FROM logs", str(path)) == [{"n": 0}]

    def test_read_lines_cuts_a_file_the_way_the_index_does(self, tmp_path):
        """The Python twin of the index's rule: a BOM is not part of line 1, a bad byte is
        U+FFFD, `\\r\\n` ends a line, a bare `\\r` stays, and a BOM alone is no line."""
        from logler.parser import read_lines

        path = tmp_path / "twin.log"
        path.write_bytes(b"\xef\xbb\xbfone\r\na\xe9b\nx\ry\n\ntail")
        assert list(read_lines(str(path))) == [
            (1, "one"),
            (2, "a�b"),
            (3, "x\ry"),
            (4, ""),
            (5, "tail"),
        ]

        path.write_bytes(b"\xef\xbb\xbf")
        assert list(read_lines(str(path))) == []
