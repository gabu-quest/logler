"""SQL query engine for advanced log investigation using DuckDB.

This module provides SQL query capabilities over log data using DuckDB's
in-memory database. It replaces the previous Rust-based SQL implementation
to avoid the long build times from bundled DuckDB compilation.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import duckdb

if TYPE_CHECKING:
    from collections.abc import Mapping

    from logler.investigate import LogIndex


class SqlEngine:
    """SQL query engine for log investigation.

    Loads log entries into an in-memory DuckDB database and provides
    SQL query capabilities for advanced analysis.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Create a new SQL engine.

        Args:
            db_path: Optional path for a disk-backed DuckDB database.
                     Defaults to in-memory (``":memory:"``).
        """
        self.conn = duckdb.connect(db_path or ":memory:")
        self.conn.execute("SET enable_external_access = false")
        self._tables_loaded: list[str] = []

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def load_files(self, indices: Mapping[str, LogIndex]) -> None:
        """Load log files into SQL tables.

        Creates a 'logs' table with all entries from the provided indices.

        Args:
            indices: Mapping of file paths to LogIndex objects
        """
        # Create logs table
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                file TEXT,
                line_number INTEGER,
                timestamp TIMESTAMP,
                level TEXT,
                message TEXT,
                thread_id TEXT,
                correlation_id TEXT,
                trace_id TEXT,
                span_id TEXT,
                raw TEXT
            )
        """
        )

        # Materialize entries once per file — avoids double-iteration if
        # index.entries is a one-shot iterable (generator / cursor).
        materialized: dict[str, list] = {}
        for file_path, index in indices.items():
            entries = list(getattr(index, "entries", None) or [])
            if entries:
                materialized[file_path] = entries

        # Insert entries from all indices in batches
        _BATCH_SIZE = 5000
        batch: list[tuple] = []
        insert_sql = "INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

        for file_path, entries in materialized.items():
            for entry in entries:
                # Handle timestamp - convert to string for DuckDB
                ts = getattr(entry, "timestamp", None)
                if ts is not None:
                    if isinstance(ts, datetime):
                        ts = ts.isoformat()
                    elif hasattr(ts, "to_rfc3339"):
                        ts = ts.to_rfc3339()

                # Handle level - convert enum to string
                level = getattr(entry, "level", None)
                if level is not None and hasattr(level, "value"):
                    level = level.value
                elif level is not None and not isinstance(level, str):
                    level = str(level)

                batch.append((
                    file_path,
                    getattr(entry, "line_number", None),
                    ts,
                    level,
                    getattr(entry, "message", None),
                    getattr(entry, "thread_id", None),
                    getattr(entry, "correlation_id", None),
                    getattr(entry, "trace_id", None),
                    getattr(entry, "span_id", None),
                    getattr(entry, "raw", None),
                ))
                if len(batch) >= _BATCH_SIZE:
                    self.conn.executemany(insert_sql, batch)
                    batch.clear()

        if batch:
            self.conn.executemany(insert_sql, batch)

        if "logs" not in self._tables_loaded:
            self._tables_loaded.append("logs")

        # Also populate metrics table from numeric extraction
        self._load_metrics(indices, materialized)

    def _load_metrics(
        self,
        indices: Mapping[str, LogIndex],
        materialized: dict[str, list] | None = None,
    ) -> None:
        """Extract numeric values from log entries and load into a metrics table.

        This enables SQL queries like:
            SELECT field_name, AVG(value), MAX(value) FROM metrics GROUP BY field_name
            SELECT m.*, l.message FROM metrics m JOIN logs l
                ON m.file = l.file AND m.line_number = l.line_number
                WHERE m.value > 1000

        Args:
            indices: Original indices mapping (used as fallback).
            materialized: Pre-materialized ``{path: [entry, ...]}`` from
                :meth:`load_files`.  When provided the entries are reused
                instead of re-iterating ``index.entries`` (which may be
                exhausted if it was a one-shot iterable).
        """
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                file TEXT,
                line_number INTEGER,
                timestamp TIMESTAMP,
                field_name TEXT,
                value DOUBLE,
                unit TEXT
            )
        """
        )

        from .metrics import extract_numeric_fields

        # Prefer pre-materialized entries; fall back to indices for
        # callers that invoke _load_metrics directly.
        source = materialized if materialized is not None else {
            fp: list(getattr(idx, "entries", None) or [])
            for fp, idx in indices.items()
        }

        for file_path, entries in source.items():
            if not entries:
                continue

            # Build entry dicts for the metrics extractor
            entry_dicts = []
            for entry in entries:
                ts = getattr(entry, "timestamp", None)
                if ts is not None:
                    if isinstance(ts, datetime):
                        ts = ts.isoformat()
                    elif hasattr(ts, "to_rfc3339"):
                        ts = ts.to_rfc3339()

                entry_dicts.append(
                    {
                        "file": file_path,
                        "line_number": getattr(entry, "line_number", None),
                        "timestamp": ts,
                        "message": getattr(entry, "message", None)
                        or getattr(entry, "raw", None)
                        or "",
                        "fields": getattr(entry, "fields", None) or {},
                    }
                )

            all_series = extract_numeric_fields(entry_dicts)

            _BATCH_SIZE = 5000
            batch: list[tuple] = []
            insert_sql = "INSERT INTO metrics VALUES (?, ?, ?, ?, ?, ?)"

            for field_name, points in all_series.items():
                for point in points:
                    batch.append((
                        point.file,
                        point.line_number,
                        point.timestamp,
                        field_name,
                        point.value,
                        point.unit,
                    ))
                    if len(batch) >= _BATCH_SIZE:
                        self.conn.executemany(insert_sql, batch)
                        batch.clear()

            if batch:
                self.conn.executemany(insert_sql, batch)

        if "metrics" not in self._tables_loaded:
            self._tables_loaded.append("metrics")

    def query(self, sql: str) -> str:
        """Execute a SQL query and return results as JSON.

        Args:
            sql: SQL query string to execute

        Returns:
            JSON string containing array of result objects
        """
        result = self.conn.execute(sql)
        columns = [desc[0] for desc in result.description]

        rows = []
        for row in result.fetchall():
            obj: dict[str, Any] = {}
            for i, col_name in enumerate(columns):
                value = row[i]
                # Convert datetime to ISO format string
                if isinstance(value, datetime):
                    value = value.isoformat()
                obj[col_name] = value
            rows.append(obj)

        return json.dumps(rows)

    def get_tables(self) -> list[str]:
        """Get available tables.

        Returns:
            List of table names
        """
        result = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return [row[0] for row in result.fetchall()]

    def get_schema(self, table: str) -> str:
        """Get table schema as JSON.

        Args:
            table: Name of table to get schema for

        Returns:
            JSON string with schema information, or empty array for
            invalid/nonexistent tables.
        """
        import re

        if not re.fullmatch(r"[A-Za-z_]\w*", table):
            return json.dumps([])
        try:
            return self.query(f"PRAGMA table_info('{table}')")
        except Exception:
            return json.dumps([])
