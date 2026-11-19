"""Tests for the `logler llm sql` command."""

import json
import os
import tempfile

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

    LOGS_COLUMNS = [
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
        """A line ends at "\\n" or "\\r\\n" and nothing else is trimmed or skipped: a blank
        line and a line of spaces are rows, trailing spaces stay, and a carriage return
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
        assert command["total_entries"] == 6
        assert [(r["line_number"], r["raw"]) for r in api] == [
            (1, "2024-01-15T10:00:00Z INFO one"),
            (2, None),
            (3, "   "),
            (4, "2024-01-15T10:00:01Z INFO two  "),
            (5, "2024-01-15T10:00:02Z INFO 10%\r20%"),
            (6, "2024-01-15T10:00:03Z INFO last, no newline\r"),
        ]
