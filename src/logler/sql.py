"""SQL query engine for advanced log investigation using DuckDB.

This module provides SQL query capabilities over log data using DuckDB's
in-memory database. It replaces the previous Rust-based SQL implementation
to avoid the long build times from bundled DuckDB compilation.
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import duckdb

from ._search_core import level_text
from .metrics import extract_numeric_fields
from .parser import format_time, without_leap_second

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_LOGS_COLUMNS = (
    ("file", "TEXT"),
    ("line_number", "INTEGER"),
    ("timestamp", "TIMESTAMP"),
    ("level", "TEXT"),
    ("message", "TEXT"),
    ("thread_id", "TEXT"),
    ("correlation_id", "TEXT"),
    ("trace_id", "TEXT"),
    ("span_id", "TEXT"),
    ("raw", "TEXT"),
)

_METRICS_COLUMNS = (
    ("file", "TEXT"),
    ("line_number", "INTEGER"),
    ("timestamp", "TIMESTAMP"),
    ("field_name", "TEXT"),
    ("value", "DOUBLE"),
    ("unit", "TEXT"),
)


def _create_table(conn: duckdb.DuckDBPyConnection, name: str, columns: tuple) -> None:
    ddl = ", ".join(f"{col} {kind}" for col, kind in columns)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({ddl})")


# Characters per bulk load: the temp CSV holds this much and at most one row more. Each
# load costs DuckDB around a tenth of a second, so the chunk is large: a log of half a
# million ordinary lines goes in at once.
_CHUNK_CHARS = 256_000_000
# DuckDB's default ``max_line_size``, in bytes.
_CSV_LINE_LIMIT = 2_000_000


def _bulk_insert(
    conn: duckdb.DuckDBPyConnection, name: str, columns: tuple, path: str, longest_row: int
) -> None:
    """Append a headerless CSV to a table (DuckDB parses it in C++: ~230x faster than
    ``executemany``).

    The dialect is spelled out, so DuckDB reads the file the way ``csv.writer`` wrote it and
    guesses nothing from the rows: left to guess the line end, it refuses a file where a
    field holds a bare carriage return. ``longest_row`` (in characters, at most four bytes
    each) raises the line limit for a row longer than DuckDB allows by default."""
    spec = ", ".join(f"'{col}': '{kind}'" for col, kind in columns)
    limit = max(_CSV_LINE_LIMIT, 4 * longest_row)
    conn.execute(
        f"INSERT INTO {name} SELECT * FROM read_csv('{path}', header=false, nullstr='', "
        f"auto_detect=false, delim=',', quote='\"', escape='\"', new_line='\\n', "
        f"max_line_size={limit}, columns={{{spec}}})"
    )


class _Staged:
    """One table's rows on their way in: written to a temp CSV and bulk-loaded every
    ``_CHUNK_CHARS`` characters, so the file never holds more than one chunk."""

    def __init__(
        self, conn: duckdb.DuckDBPyConnection, name: str, columns: tuple, path: str
    ) -> None:
        self._conn = conn
        self._name = name
        self._columns = columns
        self._path = path
        self._out: Any = None
        self._writerow: Any = None
        self._chars = 0
        self._longest = 0
        self.rows = 0

    def add(self, row: list) -> None:
        if self._out is None:
            self._out = open(self._path, "w", newline="", encoding="utf-8")  # noqa: SIM115 - opened on the first row, closed by abandon()
            self._writerow = csv.writer(self._out, lineterminator="\n").writerow
        # writerow returns what the file's write returns: the row's length in characters.
        written = self._writerow(row)
        if written > self._longest:
            self._longest = written
        self.rows += 1
        self._chars += written
        if self._chars >= _CHUNK_CHARS:
            self.flush()

    def flush(self) -> None:
        """Load the rows written since the last load."""
        if self._out is None:
            return
        self.abandon()
        _bulk_insert(self._conn, self._name, self._columns, self._path, self._longest)
        self._chars = 0
        self._longest = 0

    def abandon(self) -> None:
        """Close the file without loading it."""
        if self._out is not None:
            self._out.close()
            self._out = None


def _json_value(value: Any) -> Any:
    """A query result value as JSON holds it: a time is written the way an entry's time is,
    also inside a list or a struct. A ``TIMESTAMP`` carries no zone and the load stores UTC;
    a time that carries its zone keeps its instant."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return format_time(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


class SqlEngine:
    """SQL query engine for log investigation.

    Loads log entries into an in-memory DuckDB database (a ``logs`` and a ``metrics``
    table) and provides SQL query capabilities for advanced analysis.

    Not thread-safe — create one instance per thread.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Create a new SQL engine.

        Args:
            db_path: Optional path for a disk-backed DuckDB database.
                     Defaults to in-memory (``":memory:"``).
        """
        self.conn: duckdb.DuckDBPyConnection | None = duckdb.connect(db_path or ":memory:")
        # External access is locked lazily before the first user SQL —
        # load_entries() needs filesystem access for the bulk CSV load.
        self._external_access_locked = False

    def _lock_external_access(self) -> duckdb.DuckDBPyConnection:
        """Disable filesystem access. One-way — cannot be re-enabled.

        Returns the open connection; raises ``RuntimeError`` once the engine is closed.
        """
        if self.conn is None:
            raise RuntimeError("SqlEngine has been closed")
        if not self._external_access_locked:
            self.conn.execute("SET enable_external_access = false")
            self._external_access_locked = True
        return self.conn

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    @staticmethod
    def reads_only_logs(sql: str) -> bool:
        """True when DuckDB's own parser says the query reads the ``logs`` table and nothing
        else. A caller that loads for this one query can then leave the metrics table out
        (``load_entries(..., metrics=False)``), which is close to half the load's time. Any
        doubt (no table named, another table, a query the parser refuses) is ``False``.

        The query is read on a throwaway connection with file access off. To name a query's
        tables DuckDB opens a file or URL the query reads, and the caller asks before the
        load, when the engine's own connection must still read its temp CSVs."""
        probe = duckdb.connect(":memory:", config={"enable_external_access": "false"})
        try:
            names = probe.get_table_names(sql)
        except duckdb.Error:
            return False
        finally:
            probe.close()
        return {name.lower() for name in names} == {"logs"}

    def load_entries(self, entries: Iterable[Mapping[str, Any]], *, metrics: bool = True) -> int:
        """Load log entries into the ``logs`` and ``metrics`` tables, reading them once.

        Each entry is a dict in the shape the Rust index gives: ``file``, ``line_number``,
        ``timestamp`` (RFC 3339 text or None), ``level``, ``message``, ``thread_id``,
        ``correlation_id``, ``trace_id``, ``span_id``, ``raw`` and ``fields``. Entries are
        written to temp CSVs as they come and loaded a chunk at a time, so none is held
        after its row is written and the temp files stay one chunk long.

        A leap second (``23:59:60``) is stored as the last second of its minute.

        The metrics table enables queries like::

            SELECT field_name, AVG(value), MAX(value) FROM metrics GROUP BY field_name
            SELECT m.*, l.message FROM metrics m JOIN logs l
                ON m.file = l.file AND m.line_number = l.line_number WHERE m.value > 1000

        ``metrics=False`` leaves the metrics table out altogether: not filled and not
        created, so a query that reaches for it fails instead of reading an empty table.

        Must be called before the first query: the CSV load needs filesystem access.

        Returns:
            The number of rows added to ``logs``.
        """
        if self.conn is None:
            raise RuntimeError("SqlEngine has been closed")
        _create_table(self.conn, "logs", _LOGS_COLUMNS)
        if metrics:
            _create_table(self.conn, "metrics", _METRICS_COLUMNS)

        with tempfile.TemporaryDirectory() as tmpdir:
            logs = _Staged(self.conn, "logs", _LOGS_COLUMNS, os.path.join(tmpdir, "logs.csv"))
            numbers = _Staged(
                self.conn, "metrics", _METRICS_COLUMNS, os.path.join(tmpdir, "metrics.csv")
            )
            try:
                for entry in entries:
                    timestamp = entry.get("timestamp")
                    if timestamp:
                        timestamp = without_leap_second(timestamp)
                    logs.add(
                        [
                            entry.get("file"),
                            entry.get("line_number"),
                            timestamp,
                            level_text(entry.get("level")),
                            entry.get("message"),
                            entry.get("thread_id"),
                            entry.get("correlation_id"),
                            entry.get("trace_id"),
                            entry.get("span_id"),
                            entry.get("raw"),
                        ]
                    )
                    if not metrics:
                        continue
                    for name, points in extract_numeric_fields([entry]).items():
                        for point in points:
                            # A point's time is its entry's.
                            numbers.add(
                                [
                                    point.file,
                                    point.line_number,
                                    timestamp,
                                    name,
                                    point.value,
                                    point.unit,
                                ]
                            )
                logs.flush()
                numbers.flush()
            finally:
                logs.abandon()
                numbers.abandon()

        return logs.rows

    def execute(self, sql: str) -> tuple[list[str], list[dict[str, Any]]]:
        """Run a query; return its column names and its rows as dicts of JSON values.

        Raises ``duckdb.Error`` for a SQL error.
        """
        conn = self._lock_external_access()
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = [
            {col: _json_value(value) for col, value in zip(columns, row, strict=False)}
            for row in result.fetchall()
        ]
        return columns, rows

    def query(self, sql: str) -> str:
        """Execute a SQL query and return results as JSON.

        Args:
            sql: SQL query string to execute

        Returns:
            JSON string containing array of result objects
        """
        return json.dumps(self.execute(sql)[1])

    def get_tables(self) -> list[str]:
        """Get available tables.

        Returns:
            List of table names
        """
        conn = self._lock_external_access()
        result = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
        return [row[0] for row in result.fetchall()]

    def get_schema(self, table: str) -> str:
        """Get table schema as JSON.

        Args:
            table: Name of table to get schema for

        Returns:
            JSON string with schema information, or empty array for
            invalid/nonexistent tables.
        """
        self._lock_external_access()
        if not re.fullmatch(r"[A-Za-z_]\w*", table):
            return json.dumps([])
        try:
            return self.query(f"PRAGMA table_info('{table}')")
        except Exception:
            return json.dumps([])
