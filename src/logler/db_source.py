"""Read sqler SQLite databases as a logler data source.

Converts rows from sqler tables into JSONL that logler's Rust parser can
ingest. Works with any sqler database; auto-detects qler tables (``qler_jobs``,
``qler_job_attempts``) and applies smart defaults.

Example::

    from logler.db_source import db_to_jsonl

    # Auto-detect tables and mappings
    jsonl_path = db_to_jsonl("qler.db")

    # Use with Investigator
    from logler.investigate import Investigator
    inv = Investigator()
    inv.load_files([jsonl_path])
    results = inv.search(level="ERROR")
"""

from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import tempfile
import urllib.parse
from datetime import datetime, timezone
from typing import Optional


def _safe_identifier(name: str) -> str:
    """Return a safely double-quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


@dataclasses.dataclass
class DbTableMapping:
    """Describes how to map a sqler table into logler log entries.

    Each row becomes one JSON log entry. The mapping controls which columns
    become which log fields.

    Attributes:
        table: Table name in the database.
        timestamp_field: Column or JSON key to use as timestamp.
        timestamp_format: How to interpret the timestamp — ``"epoch"`` (unix
            seconds/ms) or ``"iso"`` (ISO 8601 string).
        level_field: Column or JSON key to map to log level. None to skip.
        level_map: Maps field values to log levels (e.g. ``{"failed": "ERROR"}``).
        message_template: Python format string for the log message. Has access
            to all row fields plus ``table_name`` and ``_id``.
        correlation_id_field: Column or JSON key for correlation ID. None to skip.
        extra_fields: Additional fields to include from the row.
        service_name: Service name to attach to all entries from this table.
        id_field: Column or JSON key to use as a unique identifier in messages.
    """

    table: str
    timestamp_field: str = "created_at"
    timestamp_format: str = "epoch"
    level_field: Optional[str] = "status"
    level_map: Optional[dict[str, str]] = None
    message_template: str = "{table_name} row {_id}"
    correlation_id_field: Optional[str] = "correlation_id"
    extra_fields: Optional[list[str]] = None
    service_name: Optional[str] = None
    id_field: Optional[str] = "ulid"


def qler_job_mapping() -> DbTableMapping:
    """Pre-built mapping for qler's ``qler_jobs`` table."""
    return DbTableMapping(
        table="qler_jobs",
        timestamp_field="created_at",
        timestamp_format="epoch",
        level_field="status",
        level_map={
            "pending": "INFO",
            "running": "INFO",
            "completed": "INFO",
            "failed": "ERROR",
            "cancelled": "WARN",
        },
        message_template="[job] {task} ({ulid}) status={status}",
        correlation_id_field="correlation_id",
        extra_fields=["queue_name", "priority", "attempts", "task", "ulid"],
        service_name="qler",
        id_field="ulid",
    )


def qler_attempt_mapping() -> DbTableMapping:
    """Pre-built mapping for qler's ``qler_job_attempts`` table."""
    return DbTableMapping(
        table="qler_job_attempts",
        timestamp_field="started_at",
        timestamp_format="epoch",
        level_field="status",
        level_map={
            "running": "INFO",
            "completed": "INFO",
            "failed": "ERROR",
            "lease_expired": "WARN",
        },
        message_template="[attempt] job={job_ulid} attempt={attempt_number} status={status}",
        correlation_id_field=None,
        extra_fields=[
            "job_ulid",
            "attempt_number",
            "worker_id",
            "status",
            "error",
            "failure_kind",
        ],
        service_name="qler",
        id_field="ulid",
    )


def db_to_jsonl(
    db_path: str,
    mappings: Optional[list[DbTableMapping]] = None,
) -> str:
    """Convert a sqler database to a temporary JSONL file.

    Opens the database read-only, reads tables according to the provided
    mappings (or auto-detects if None), and writes sorted JSONL to a
    temporary file.

    Args:
        db_path: Path to the SQLite database file.
        mappings: Table mappings. Auto-detected if None.

    Returns:
        Path to the temporary JSONL file. Caller is responsible for cleanup.

    Raises:
        ValueError: If the database has no tables or is empty.
    """
    safe_path = urllib.parse.quote(os.path.abspath(db_path), safe="/")
    uri = f"file:{safe_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        if mappings is None:
            mappings = _auto_detect_mappings(conn)

        if not mappings:
            raise ValueError(f"No tables found in database: {db_path}")

        all_entries: list[dict] = []
        for mapping in mappings:
            rows = _read_sqler_table(conn, mapping)
            all_entries.extend(rows)

        if not all_entries:
            raise ValueError(f"No rows found in database: {db_path}")

        # Sort by timestamp
        all_entries.sort(key=lambda e: e.get("timestamp", ""))

        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".jsonl",
            delete=False,
            encoding="utf-8",
        )
        try:
            for entry in all_entries:
                tmp.write(json.dumps(entry) + "\n")
        except Exception:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise
        finally:
            tmp.close()

        return tmp.name
    finally:
        conn.close()


def _read_sqler_table(
    conn: sqlite3.Connection,
    mapping: DbTableMapping,
) -> list[dict]:
    """Read all rows from a sqler table and convert to log entries."""
    # Validate table exists (parameterized query — safe from injection)
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (mapping.table,),
    ).fetchone()
    if exists is None:
        raise ValueError(f"Table '{mapping.table}' not found in database")

    # Discover columns
    cursor = conn.execute(f"PRAGMA table_info({_safe_identifier(mapping.table)})")
    columns = [row[1] for row in cursor.fetchall()]

    if not columns:
        return []

    # Read rows ordered by _id
    cursor = conn.execute(f"SELECT * FROM {_safe_identifier(mapping.table)} ORDER BY _id")
    rows = cursor.fetchall()

    entries = []
    for idx, row in enumerate(rows):
        row_dict = dict(row)
        # Merge promoted columns with JSON data blob
        all_fields = _merge_sqler_row(row_dict, columns)
        entry = _build_entry(all_fields, mapping, idx)
        entries.append(entry)

    return entries


def _merge_sqler_row(row_dict: dict, columns: list[str]) -> dict:
    """Merge a sqler row's promoted columns with its JSON data blob.

    sqler stores non-promoted fields in a ``data`` JSON column and
    promoted fields as real columns. This function merges both into
    a single flat dict. Promoted columns take precedence over JSON keys.
    """
    result = {}

    # Parse JSON data blob
    data_raw = row_dict.get("data")
    if data_raw:
        try:
            parsed = json.loads(data_raw)
            if isinstance(parsed, dict):
                result.update(parsed)
        except (json.JSONDecodeError, TypeError):
            pass

    # Overlay promoted columns (they take precedence)
    for col in columns:
        if col not in ("data",) and row_dict.get(col) is not None:
            result[col] = row_dict[col]

    return result


def _build_entry(
    all_fields: dict,
    mapping: DbTableMapping,
    row_idx: int,
) -> dict:
    """Build a logler-compatible log entry dict from merged row fields."""
    entry: dict = {}

    # Timestamp
    ts_raw = all_fields.get(mapping.timestamp_field)
    if ts_raw is not None:
        entry["timestamp"] = _normalize_timestamp(ts_raw, mapping.timestamp_format)
    else:
        entry["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

    # Level
    if mapping.level_field:
        raw_level = str(all_fields.get(mapping.level_field, ""))
        if mapping.level_map:
            entry["level"] = mapping.level_map.get(raw_level, "INFO")
        else:
            entry["level"] = raw_level.upper() or "INFO"
    else:
        entry["level"] = "INFO"

    # Message
    try:
        template_vars = {**all_fields, "table_name": mapping.table}
        entry["message"] = mapping.message_template.format_map(_SafeFormatDict(template_vars))
    except (KeyError, ValueError):
        entry["message"] = f"{mapping.table} row {all_fields.get('_id', row_idx)}"

    # Correlation ID
    if mapping.correlation_id_field:
        cid = all_fields.get(mapping.correlation_id_field)
        if cid is not None:
            entry["correlation_id"] = str(cid)

    # Service name
    if mapping.service_name:
        entry["service_name"] = mapping.service_name

    # Thread ID — use table name as pseudo-thread for grouping
    entry["thread_id"] = mapping.table

    # Extra fields
    if mapping.extra_fields:
        for field in mapping.extra_fields:
            val = all_fields.get(field)
            if val is not None:
                entry[field] = val

    return entry


def _normalize_timestamp(raw, fmt: str) -> str:
    """Convert a raw timestamp value to ISO 8601 string."""
    if fmt == "iso":
        return str(raw)
    elif fmt == "epoch":
        try:
            ts = float(raw)
            # Auto-detect milliseconds vs seconds
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            return str(raw)
    return str(raw)


def _auto_detect_mappings(conn: sqlite3.Connection) -> list[DbTableMapping]:
    """Auto-detect table mappings from a sqler database.

    Known qler tables get their specific mappings. Unknown tables get a
    generic mapping.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = [row[0] for row in cursor.fetchall()]

    mappings = []
    for table in tables:
        if table == "qler_jobs":
            mappings.append(qler_job_mapping())
        elif table == "qler_job_attempts":
            mappings.append(qler_attempt_mapping())
        else:
            # Generic mapping for unknown sqler tables
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_safe_identifier(table)})").fetchall()]
            # Try to guess reasonable defaults
            ts_field = "created_at"
            if "created_at" not in columns:
                ts_field = "timestamp" if "timestamp" in columns else "created_at"

            has_status = "status" in columns
            has_correlation = "correlation_id" in columns

            mappings.append(
                DbTableMapping(
                    table=table,
                    timestamp_field=ts_field,
                    timestamp_format="iso",
                    level_field="status" if has_status else None,
                    level_map=None,
                    message_template=f"{{{table}}} row {{_id}}",
                    correlation_id_field="correlation_id" if has_correlation else None,
                    service_name=table,
                )
            )

    return mappings


class _SafeFormatDict(dict):
    """A dict subclass that returns {key} for missing keys in format_map."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
