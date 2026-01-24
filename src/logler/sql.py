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

    def __init__(self) -> None:
        """Create a new SQL engine with an in-memory database."""
        self.conn = duckdb.connect(":memory:")
        self._tables_loaded: list[str] = []

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

        # Insert entries from all indices
        for file_path, index in indices.items():
            entries = getattr(index, "entries", None)
            if entries is None:
                continue

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

                self.conn.execute(
                    "INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
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
                    ],
                )

        if "logs" not in self._tables_loaded:
            self._tables_loaded.append("logs")

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
            JSON string with schema information
        """
        # Use parameterized query to prevent SQL injection
        # PRAGMA doesn't support parameters, so we sanitize the table name
        safe_table = table.replace("'", "''")
        return self.query(f"PRAGMA table_info('{safe_table}')")
