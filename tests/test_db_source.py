"""Tests for logler.db_source — sqler database to JSONL conversion."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from logler.db_source import (
    DbTableMapping,
    _auto_detect_mappings,
    _build_entry,
    _merge_sqler_row,
    _normalize_timestamp,
    _read_sqler_table,
    _safe_format,
    db_to_jsonl,
    qler_attempt_mapping,
    qler_job_mapping,
)


# ---------------------------------------------------------------------------
# Shared fixture: temp SQLite with sqler schema matching qler's actual tables
# ---------------------------------------------------------------------------


@pytest.fixture()
def qler_test_db(tmp_path: Path) -> str:
    """Create a temp SQLite DB with sqler-style tables matching qler's actual schema.

    qler_jobs promoted columns: ulid, status, queue_name, priority, eta, lease_expires_at
    qler_job_attempts promoted columns: ulid, job_ulid, status
    Non-promoted fields live in the ``data`` JSON blob.
    """
    db_path = str(tmp_path / "test_qler.db")
    conn = sqlite3.connect(db_path)

    # qler_jobs table (sqler schema: _id, data, _version + promoted columns)
    conn.execute(
        """
        CREATE TABLE qler_jobs (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            data JSON NOT NULL,
            _version INTEGER NOT NULL DEFAULT 1,
            ulid TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            queue_name TEXT NOT NULL DEFAULT 'default',
            priority INTEGER NOT NULL DEFAULT 0,
            eta INTEGER NOT NULL DEFAULT 0,
            lease_expires_at INTEGER
        )
    """
    )

    # Epoch timestamps (seconds since unix epoch)
    base_ts = 1705312800  # 2024-01-15T10:00:00Z

    # Insert 10 jobs with mixed statuses
    # Data blob has non-promoted fields: task, attempts, correlation_id, created_at, etc.
    jobs = [
        # (data_json, ulid, status, queue_name, priority)
        (
            json.dumps({"task": "send_email", "attempts": 1, "correlation_id": "corr-001", "created_at": base_ts}),
            "01H1", "completed", "default", 0,
        ),
        (
            json.dumps({"task": "send_email", "attempts": 1, "correlation_id": "corr-002", "created_at": base_ts + 60}),
            "01H2", "completed", "default", 0,
        ),
        (
            json.dumps({"task": "process_image", "attempts": 3, "correlation_id": "corr-003", "created_at": base_ts + 120}),
            "01H3", "failed", "media", 5,
        ),
        (
            json.dumps({"task": "generate_report", "attempts": 0, "correlation_id": "corr-004", "created_at": base_ts + 180}),
            "01H4", "pending", "default", 0,
        ),
        (
            json.dumps({"task": "send_email", "attempts": 1, "correlation_id": "corr-005", "created_at": base_ts + 240}),
            "01H5", "running", "default", 0,
        ),
        (
            json.dumps({"task": "cleanup_temp", "attempts": 1, "created_at": base_ts + 300}),
            "01H6", "completed", "maintenance", -1,
        ),
        (
            json.dumps({"task": "process_image", "attempts": 3, "correlation_id": "corr-007", "created_at": base_ts + 360}),
            "01H7", "failed", "media", 5,
        ),
        (
            json.dumps({"task": "sync_data", "attempts": 1, "correlation_id": "corr-008", "created_at": base_ts + 420}),
            "01H8", "completed", "default", 10,
        ),
        (
            json.dumps({"task": "send_notification", "attempts": 0, "correlation_id": "corr-009", "created_at": base_ts + 480}),
            "01H9", "cancelled", "default", 0,
        ),
        (
            json.dumps({"task": "process_image", "attempts": 5, "correlation_id": "corr-010", "created_at": base_ts + 540}),
            "01HA", "failed", "media", 5,
        ),
    ]
    conn.executemany(
        "INSERT INTO qler_jobs (data, ulid, status, queue_name, priority) VALUES (?, ?, ?, ?, ?)",
        jobs,
    )

    # qler_job_attempts table
    conn.execute(
        """
        CREATE TABLE qler_job_attempts (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            data JSON NOT NULL,
            _version INTEGER NOT NULL DEFAULT 1,
            ulid TEXT UNIQUE NOT NULL,
            job_ulid TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running'
        )
    """
    )

    attempts = [
        # (data_json, ulid, job_ulid, status)
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-1", "started_at": base_ts + 1}),
            "A001", "01H1", "completed",
        ),
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-2", "started_at": base_ts + 61}),
            "A002", "01H2", "completed",
        ),
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-1", "started_at": base_ts + 121, "error": "OOM", "failure_kind": "exception"}),
            "A003", "01H3", "failed",
        ),
        (
            json.dumps({"attempt_number": 2, "worker_id": "w-2", "started_at": base_ts + 150, "error": "OOM", "failure_kind": "exception"}),
            "A004", "01H3", "failed",
        ),
        (
            json.dumps({"attempt_number": 3, "worker_id": "w-1", "started_at": base_ts + 180, "error": "OOM", "failure_kind": "exception"}),
            "A005", "01H3", "failed",
        ),
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-3", "started_at": base_ts + 241}),
            "A006", "01H5", "running",
        ),
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-1", "started_at": base_ts + 301}),
            "A007", "01H6", "completed",
        ),
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-2", "started_at": base_ts + 361, "error": "timeout", "failure_kind": "lease_expired"}),
            "A008", "01H7", "lease_expired",
        ),
        (
            json.dumps({"attempt_number": 2, "worker_id": "w-1", "started_at": base_ts + 390, "error": "timeout", "failure_kind": "lease_expired"}),
            "A009", "01H7", "lease_expired",
        ),
        (
            json.dumps({"attempt_number": 3, "worker_id": "w-3", "started_at": base_ts + 420, "error": "timeout", "failure_kind": "exception"}),
            "A010", "01H7", "failed",
        ),
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-2", "started_at": base_ts + 421}),
            "A011", "01H8", "completed",
        ),
        (
            json.dumps({"attempt_number": 1, "worker_id": "w-1", "started_at": base_ts + 541, "error": "crash", "failure_kind": "exception"}),
            "A012", "01HA", "failed",
        ),
    ]
    conn.executemany(
        "INSERT INTO qler_job_attempts (data, ulid, job_ulid, status) VALUES (?, ?, ?, ?)",
        attempts,
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def generic_test_db(tmp_path: Path) -> str:
    """Create a DB with a non-qler table for generic mapping tests."""
    db_path = str(tmp_path / "generic.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE events (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            data JSON NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """
    )
    conn.execute(
        "INSERT INTO events (data, status) VALUES (?, ?)",
        (
            '{"name":"deploy","created_at":"2024-01-15T12:00:00Z","correlation_id":"dep-1"}',
            "active",
        ),
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestMergeSqlerRow:
    def test_read_basic_sqler_table(self):
        row = {"_id": 1, "data": '{"name":"alice","email":"a@b.com"}'}
        result = _merge_sqler_row(row, ["_id", "data"])
        assert result["name"] == "alice"
        assert result["email"] == "a@b.com"
        assert result["_id"] == 1

    def test_promoted_columns_precedence(self):
        """Promoted columns override values from JSON blob."""
        row = {
            "_id": 1,
            "data": '{"name":"alice","status":"old_value"}',
            "status": "new_value",
        }
        result = _merge_sqler_row(row, ["_id", "data", "status"])
        assert result["status"] == "new_value"
        assert result["name"] == "alice"

    def test_null_data_column(self):
        """Row with NULL data column doesn't crash."""
        row = {"_id": 1, "data": None, "status": "active"}
        result = _merge_sqler_row(row, ["_id", "data", "status"])
        assert result["_id"] == 1
        assert result["status"] == "active"
        assert "name" not in result

    def test_malformed_json_data(self):
        """Row with malformed JSON in data column falls back gracefully."""
        row = {"_id": 1, "data": "not-json{", "status": "ok"}
        result = _merge_sqler_row(row, ["_id", "data", "status"])
        assert result["_id"] == 1
        assert result["status"] == "ok"
        assert set(result.keys()) == {"_id", "status"}

    def test_json_array_data(self):
        """Row where data is a JSON array instead of object — array is ignored."""
        row = {"_id": 1, "data": "[1, 2, 3]"}
        result = _merge_sqler_row(row, ["_id", "data"])
        assert result["_id"] == 1
        assert set(result.keys()) == {"_id"}


class TestQlerMappings:
    def test_qler_job_mapping(self):
        m = qler_job_mapping()
        assert m.table == "qler_jobs"
        assert m.timestamp_format == "epoch"
        assert m.level_map["failed"] == "ERROR"
        assert m.level_map["completed"] == "INFO"
        assert "claimed" not in m.level_map
        assert "success" not in m.level_map
        assert "dead" not in m.level_map
        assert m.correlation_id_field == "correlation_id"
        assert "ulid" in m.extra_fields
        assert "task" in m.extra_fields
        assert "queue_name" in m.extra_fields
        assert "attempts" in m.extra_fields

    def test_qler_attempt_mapping(self):
        m = qler_attempt_mapping()
        assert m.table == "qler_job_attempts"
        assert m.timestamp_format == "epoch"
        assert m.level_field == "status"
        assert m.level_map["failed"] == "ERROR"
        assert m.level_map["lease_expired"] == "WARN"
        assert m.level_map["completed"] == "INFO"
        assert m.correlation_id_field is None
        assert "job_ulid" in m.extra_fields
        assert "error" in m.extra_fields
        assert "failure_kind" in m.extra_fields


class TestDbToJsonl:
    def test_db_to_jsonl_format(self, qler_test_db: str):
        path = db_to_jsonl(qler_test_db)
        try:
            with open(path) as f:
                lines = f.readlines()

            assert len(lines) == 22  # 10 jobs + 12 attempts
            entry = json.loads(lines[0])
            assert entry["level"] in ("INFO", "WARN", "ERROR")
            assert entry["message"].startswith("[job]") or entry["message"].startswith("[attempt]")
            assert "T" in entry["timestamp"]
        finally:
            os.unlink(path)

    def test_db_to_jsonl_per_table_order(self, qler_test_db: str):
        """Entries are ordered per-table by _id (no cross-table sort)."""
        path = db_to_jsonl(qler_test_db)
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            assert len(entries) == 22

            # Group by thread_id (table name) and verify per-table ordering
            from itertools import groupby

            for _, group in groupby(entries, key=lambda e: e["thread_id"]):
                table_entries = list(group)
                timestamps = [e["timestamp"] for e in table_entries]
                assert timestamps == sorted(timestamps), (
                    "entries within a single table must be in timestamp order"
                )
        finally:
            os.unlink(path)

    def test_auto_detect_mappings(self, qler_test_db: str):
        conn = sqlite3.connect(qler_test_db)
        try:
            mappings = _auto_detect_mappings(conn)
            assert len(mappings) == 2
            table_names = {m.table for m in mappings}
            assert table_names == {"qler_jobs", "qler_job_attempts"}

            jobs_mapping = next(m for m in mappings if m.table == "qler_jobs")
            assert jobs_mapping.level_map["failed"] == "ERROR"
            assert jobs_mapping.level_map["completed"] == "INFO"

            attempts_mapping = next(m for m in mappings if m.table == "qler_job_attempts")
            assert attempts_mapping.level_map["failed"] == "ERROR"
            assert attempts_mapping.level_map["lease_expired"] == "WARN"
        finally:
            conn.close()

    def test_auto_detect_generic_table(self, generic_test_db: str):
        conn = sqlite3.connect(generic_test_db)
        try:
            mappings = _auto_detect_mappings(conn)
            assert len(mappings) == 1
            assert mappings[0].table == "events"
            assert mappings[0].service_name == "events"
        finally:
            conn.close()

    def test_empty_db_error(self, tmp_path: Path):
        db_path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db_path)
        conn.close()

        with pytest.raises(ValueError, match="No tables found"):
            db_to_jsonl(db_path)

    def test_readonly_access(self, qler_test_db: str):
        """DB is not modified by db_to_jsonl — verified by checksum."""
        import hashlib

        with open(qler_test_db, "rb") as f:
            checksum_before = hashlib.md5(f.read()).hexdigest()

        path = db_to_jsonl(qler_test_db)
        os.unlink(path)

        with open(qler_test_db, "rb") as f:
            checksum_after = hashlib.md5(f.read()).hexdigest()

        assert checksum_before == checksum_after

    def test_job_level_mapping(self, qler_test_db: str):
        """Failed jobs map to ERROR, cancelled to WARN."""
        path = db_to_jsonl(qler_test_db, [qler_job_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            level_counts: dict[str, int] = {}
            for e in entries:
                level_counts[e["level"]] = level_counts.get(e["level"], 0) + 1

            # 3 failed = 3 ERROR
            assert level_counts.get("ERROR", 0) == 3
            # 1 cancelled = 1 WARN
            assert level_counts.get("WARN", 0) == 1
            # 3 completed + 1 pending + 1 running = 5 INFO
            # cleanup_temp (completed) makes it 3 completed total + pending + running = 5
            # Wait: 01H1=completed, 01H2=completed, 01H4=pending, 01H5=running,
            # 01H6=completed, 01H8=completed = 4 completed + 1 pending + 1 running = 6 INFO
            assert level_counts.get("INFO", 0) == 6
        finally:
            os.unlink(path)

    def test_correlation_id_extracted(self, qler_test_db: str):
        path = db_to_jsonl(qler_test_db, [qler_job_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            with_corr = [e for e in entries if "correlation_id" in e]
            assert len(with_corr) == 9  # 9 of 10 jobs have correlation_id (cleanup_temp doesn't)
        finally:
            os.unlink(path)

    def test_epoch_timestamps_converted(self, qler_test_db: str):
        """Epoch integer timestamps are converted to ISO 8601 strings."""
        path = db_to_jsonl(qler_test_db, [qler_job_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            assert len(entries) == 10
            # First entry: base_ts=1705312800 -> 2024-01-15T10:00:00+00:00
            assert entries[0]["timestamp"] == "2024-01-15T10:00:00+00:00"
            # All entries should be ISO 8601
            for e in entries:
                assert "T" in e["timestamp"]
                assert "+" in e["timestamp"] or "Z" in e["timestamp"]
        finally:
            os.unlink(path)

    def test_attempt_status_mapping(self, qler_test_db: str):
        """Attempt statuses map to correct log levels."""
        path = db_to_jsonl(qler_test_db, [qler_attempt_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            assert len(entries) == 12
            level_counts: dict[str, int] = {}
            for e in entries:
                level_counts[e["level"]] = level_counts.get(e["level"], 0) + 1

            # 4 failed + 1 failed (01H7 attempt 3) + 1 failed (01HA) = 5 failed -> ERROR
            # Actually: A003=failed, A004=failed, A005=failed, A010=failed, A012=failed = 5 ERROR
            assert level_counts.get("ERROR", 0) == 5
            # A008=lease_expired, A009=lease_expired = 2 WARN
            assert level_counts.get("WARN", 0) == 2
            # A001=completed, A002=completed, A006=running, A007=completed, A011=completed = 5 INFO
            assert level_counts.get("INFO", 0) == 5
        finally:
            os.unlink(path)

    def test_explicit_mapping(self, qler_test_db: str):
        """Using explicit mappings works correctly."""
        mapping = DbTableMapping(
            table="qler_jobs",
            timestamp_field="created_at",
            timestamp_format="epoch",
            level_field=None,
            message_template="custom: {task}",
            service_name="test-svc",
        )
        path = db_to_jsonl(qler_test_db, [mapping])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            assert len(entries) == 10
            assert all(e["level"] == "INFO" for e in entries)
            assert all(e["service_name"] == "test-svc" for e in entries)
            assert all(e["message"].startswith("custom:") for e in entries)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Integration: Investigator + DB
# ---------------------------------------------------------------------------


class TestInvestigatorDbIntegration:
    def test_investigator_load_from_db(self, qler_test_db: str):
        """Full roundtrip: create DB -> load -> search ERROR -> find failed jobs."""
        from logler.investigate import Investigator

        inv = Investigator()
        inv.load_from_db(qler_test_db)

        results = inv.search(level="ERROR")
        entries = results["results"]
        # 3 failed jobs + 5 failed/expired attempts = 8 ERROR entries
        assert len(entries) == 8
        assert all(e["entry"]["level"] == "ERROR" for e in entries)

        inv.close()

    def test_search_db_convenience(self, qler_test_db: str):
        """search_db() works end-to-end."""
        from logler.investigate import search_db

        results = search_db(qler_test_db, level="ERROR")
        entries = results["results"]
        assert len(entries) == 8
        assert all(e["entry"]["level"] == "ERROR" for e in entries)

    def test_search_db_by_correlation(self, qler_test_db: str):
        from logler.investigate import search_db

        results = search_db(qler_test_db, correlation_id="corr-003")
        entries = results.get("results", [])
        # Only job entries have correlation_id; attempts don't (correlation_id_field=None)
        assert len(entries) == 1
        for item in entries:
            assert item["entry"].get("correlation_id") == "corr-003"

    def test_cleanup(self, qler_test_db: str):
        """Temp files are removed after close()."""
        from logler.investigate import Investigator

        inv = Investigator()
        inv.load_from_db(qler_test_db)

        temp_files = list(inv._db_temp_files)
        assert len(temp_files) == 1
        assert os.path.exists(temp_files[0])

        inv.close()
        assert not os.path.exists(temp_files[0])
        assert len(inv._db_temp_files) == 0

    def test_no_rows_error(self, tmp_path: Path):
        """ValueError when DB exists but all tables are empty."""
        db_path = str(tmp_path / "empty_tables.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE things (_id INTEGER PRIMARY KEY, data JSON NOT NULL)")
        conn.commit()
        conn.close()

        with pytest.raises(ValueError, match="No rows found"):
            db_to_jsonl(db_path)


# ---------------------------------------------------------------------------
# IMP-1: Table name validation
# ---------------------------------------------------------------------------


class TestTableNameValidation:
    """Explicit mappings with non-existent table names raise ValueError."""

    def test_nonexistent_table_raises(self, qler_test_db: str):
        """Completely unknown table name gives clear error."""
        mapping = DbTableMapping(
            table="nonexistent",
            timestamp_field="created_at",
            timestamp_format="iso",
            message_template="{nonexistent} row {_id}",
            service_name="test",
        )
        with pytest.raises(ValueError, match="Table 'nonexistent' not found"):
            db_to_jsonl(qler_test_db, mappings=[mapping])

    def test_typo_table_raises(self, qler_test_db: str):
        """Plausible typo (missing 's') gives clear error instead of silent empty."""
        mapping = DbTableMapping(
            table="qler_job",  # typo: should be qler_jobs
            timestamp_field="created_at",
            timestamp_format="iso",
            message_template="{qler_job} row {_id}",
            service_name="test",
        )
        with pytest.raises(ValueError, match="Table 'qler_job' not found"):
            db_to_jsonl(qler_test_db, mappings=[mapping])


# ---------------------------------------------------------------------------
# IMP-3: Temp file cleanup on error + context manager
# ---------------------------------------------------------------------------


class TestTempFileCleanup:
    """Temp files are cleaned up even when exceptions occur."""

    def test_db_to_jsonl_cleans_temp_on_write_error(self, qler_test_db: str, tmp_path, monkeypatch):
        """If json.dumps raises during JSONL write, temp file is deleted."""
        import tempfile as tmp_mod

        # Control where the temp file goes so we can assert precisely
        controlled_path = str(tmp_path / "should_be_deleted.jsonl")
        original_ntf = tmp_mod.NamedTemporaryFile

        def patched_ntf(**kwargs):
            kwargs.pop("suffix", None)
            kwargs.pop("delete", None)
            return open(controlled_path, kwargs.get("mode", "w"), encoding=kwargs.get("encoding", "utf-8"))

        # Patch NamedTemporaryFile to return a file at our controlled path
        mock_file = open(controlled_path, "w", encoding="utf-8")
        mock_file.close()

        call_count = 0
        original_dumps = json.dumps

        def failing_dumps(obj, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                raise RuntimeError("simulated serialization failure")
            return original_dumps(obj, **kwargs)

        monkeypatch.setattr(json, "dumps", failing_dumps)

        class FakeTemp:
            def __init__(self, **kwargs):
                self._f = open(controlled_path, "w", encoding="utf-8")
                self.name = controlled_path

            def write(self, data):
                return self._f.write(data)

            def close(self):
                self._f.close()

        monkeypatch.setattr(tmp_mod, "NamedTemporaryFile", FakeTemp)

        with pytest.raises(RuntimeError, match="simulated serialization failure"):
            db_to_jsonl(qler_test_db)

        assert not os.path.exists(controlled_path), "Temp file leaked after write error"

    def test_investigator_context_manager(self, qler_test_db: str):
        """Investigator as context manager cleans up temp files."""
        from logler.investigate import Investigator

        with Investigator() as inv:
            inv.load_from_db(qler_test_db)
            temp_files = list(inv._db_temp_files)
            assert len(temp_files) == 1
            assert os.path.exists(temp_files[0])

        # After exiting context, temp files are gone
        assert not os.path.exists(temp_files[0])

    def test_investigator_context_manager_on_exception(self, qler_test_db: str):
        """Temp files cleaned up even when exception inside context."""
        from logler.investigate import Investigator

        with pytest.raises(RuntimeError, match="boom"):
            with Investigator() as inv:
                inv.load_from_db(qler_test_db)
                temp_files = list(inv._db_temp_files)
                raise RuntimeError("boom")

        assert not os.path.exists(temp_files[0])


# ---------------------------------------------------------------------------
# Security: _RestrictedFormatter / _safe_format
# ---------------------------------------------------------------------------


class TestRestrictedFormatter:
    """The restricted formatter must reject attribute/index access in templates."""

    def test_rejects_attribute_access(self):
        """Template with dot-notation attribute access raises ValueError."""
        with pytest.raises(ValueError, match="Attribute/index access not allowed"):
            _safe_format("{key.__class__}", {"key": "hello"})

    def test_rejects_index_access(self):
        """Template with bracket-notation index access raises ValueError."""
        with pytest.raises(ValueError, match="Attribute/index access not allowed"):
            _safe_format("{key[0]}", {"key": "hello"})

    def test_rejects_deep_attribute_chain(self):
        """Template with deep attribute chain raises ValueError."""
        with pytest.raises(ValueError, match="Attribute/index access not allowed"):
            _safe_format("{key.__class__.__mro__}", {"key": "hello"})

    def test_missing_key_returns_placeholder(self):
        """Missing keys return literal {key} placeholder instead of raising."""
        result = _safe_format("{present} {missing}", {"present": "hi"})
        assert result == "hi {missing}"

    def test_normal_substitution_works(self):
        """Normal key substitution works correctly."""
        result = _safe_format("[job] {task} ({ulid}) status={status}", {
            "task": "send_email", "ulid": "01H1", "status": "completed"
        })
        assert result == "[job] send_email (01H1) status=completed"


# ---------------------------------------------------------------------------
# Edge cases: timestamp normalization and entry building
# ---------------------------------------------------------------------------


class TestNormalizeTimestamp:
    def test_epoch_seconds(self):
        """Standard epoch seconds are converted to ISO 8601."""
        result = _normalize_timestamp(1705312800, "epoch")
        assert result == "2024-01-15T10:00:00+00:00"

    def test_epoch_milliseconds(self):
        """Millisecond epoch timestamps (>1e12) are auto-divided by 1000."""
        result = _normalize_timestamp(1705312800000, "epoch")
        assert result == "2024-01-15T10:00:00+00:00"

    def test_iso_passthrough(self):
        """ISO format timestamps are passed through as strings."""
        result = _normalize_timestamp("2024-01-15T10:00:00Z", "iso")
        assert result == "2024-01-15T10:00:00Z"

    def test_invalid_epoch_returns_string(self):
        """Non-numeric epoch values fall back to str()."""
        result = _normalize_timestamp("not-a-number", "epoch")
        assert result == "not-a-number"


# ---------------------------------------------------------------------------
# Non-sqler table handling (fix 376157c)
# ---------------------------------------------------------------------------


class TestNonSqlerTableHandling:
    """Verify db_source handles databases containing non-sqler tables."""

    def test_auto_detect_skips_non_sqler_tables(self, tmp_path: Path):
        """Auto-detection skips tables without _id column."""
        db_path = str(tmp_path / "mixed.db")
        conn = sqlite3.connect(db_path)

        # sqler model table (has _id, data)
        conn.execute(
            """
            CREATE TABLE widgets (
                _id INTEGER PRIMARY KEY AUTOINCREMENT,
                data JSON NOT NULL,
                _version INTEGER NOT NULL DEFAULT 1,
                status TEXT DEFAULT 'active'
            )
            """
        )
        conn.execute(
            "INSERT INTO widgets (_id, data, status) VALUES (1, ?, 'active')",
            (json.dumps({"name": "gizmo", "created_at": "2024-01-15T10:00:00Z"}),),
        )

        # Non-sqler table (NO _id column)
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('version', '1.0')")
        conn.execute("INSERT INTO metadata VALUES ('env', 'prod')")

        conn.commit()
        conn.close()

        # Auto-detect should find only the sqler table
        conn = sqlite3.connect(db_path)
        try:
            mappings = _auto_detect_mappings(conn)
            assert len(mappings) == 1
            assert mappings[0].table == "widgets"
        finally:
            conn.close()

        # Full pipeline should produce entries only from the sqler table
        path = db_to_jsonl(db_path)
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]
            assert len(entries) == 1
            assert entries[0]["thread_id"] == "widgets"
            assert entries[0]["level"] == "ACTIVE"  # no level_map -> uppercased raw
            assert entries[0]["timestamp"] == "2024-01-15T10:00:00Z"  # iso passthrough
            assert entries[0]["service_name"] == "widgets"
        finally:
            os.unlink(path)

    def test_read_sqler_table_missing_id_uses_rowid(self, tmp_path: Path):
        """_read_sqler_table falls back to ORDER BY rowid when _id is absent."""
        db_path = str(tmp_path / "no_id.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE logs (ts TEXT, msg TEXT, level TEXT)"
        )
        conn.execute("INSERT INTO logs VALUES ('2024-01-15T10:00:00Z', 'first', 'INFO')")
        conn.execute("INSERT INTO logs VALUES ('2024-01-15T10:01:00Z', 'second', 'WARN')")
        conn.execute("INSERT INTO logs VALUES ('2024-01-15T10:02:00Z', 'third', 'ERROR')")
        conn.commit()

        conn.row_factory = sqlite3.Row

        mapping = DbTableMapping(
            table="logs",
            timestamp_field="ts",
            timestamp_format="iso",
            level_field="level",
            level_map=None,
            message_template="log: {msg}",
            correlation_id_field=None,
            service_name="test",
        )

        rows = _read_sqler_table(conn, mapping)
        conn.close()

        assert len(rows) == 3
        assert rows[0]["message"] == "log: first"
        assert rows[1]["message"] == "log: second"
        assert rows[2]["message"] == "log: third"
        assert rows[0]["level"] == "INFO"
        assert rows[1]["level"] == "WARN"
        assert rows[2]["level"] == "ERROR"

    def test_qler_schema_with_job_deps(self, tmp_path: Path):
        """Simulate real qler schema: qler_jobs + qler_job_attempts + qler_job_deps.

        qler_job_deps has only (parent_ulid, child_ulid) — no _id, no data,
        no _version. This is the exact table that triggered the original crash.
        """
        db_path = str(tmp_path / "qler_full.db")
        conn = sqlite3.connect(db_path)
        base_ts = 1705312800

        # qler_jobs (sqler model)
        conn.execute(
            """
            CREATE TABLE qler_jobs (
                _id INTEGER PRIMARY KEY AUTOINCREMENT,
                data JSON NOT NULL,
                _version INTEGER NOT NULL DEFAULT 1,
                ulid TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                queue_name TEXT NOT NULL DEFAULT 'default',
                priority INTEGER NOT NULL DEFAULT 0,
                eta INTEGER NOT NULL DEFAULT 0,
                lease_expires_at INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO qler_jobs (data, ulid, status) VALUES (?, ?, ?)",
            (json.dumps({"task": "parent_job", "created_at": base_ts, "correlation_id": "c1"}), "J001", "completed"),
        )
        conn.execute(
            "INSERT INTO qler_jobs (data, ulid, status) VALUES (?, ?, ?)",
            (json.dumps({"task": "child_job", "created_at": base_ts + 60, "correlation_id": "c2"}), "J002", "pending"),
        )

        # qler_job_attempts (sqler model)
        conn.execute(
            """
            CREATE TABLE qler_job_attempts (
                _id INTEGER PRIMARY KEY AUTOINCREMENT,
                data JSON NOT NULL,
                _version INTEGER NOT NULL DEFAULT 1,
                ulid TEXT UNIQUE NOT NULL,
                job_ulid TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running'
            )
            """
        )
        conn.execute(
            "INSERT INTO qler_job_attempts (data, ulid, job_ulid, status) VALUES (?, ?, ?, ?)",
            (json.dumps({"attempt_number": 1, "worker_id": "w-1", "started_at": base_ts + 1}), "A001", "J001", "completed"),
        )

        # qler_job_deps — the problematic table (NO _id, NO data, NO _version)
        conn.execute(
            """
            CREATE TABLE qler_job_deps (
                parent_ulid TEXT NOT NULL,
                child_ulid TEXT NOT NULL,
                PRIMARY KEY (parent_ulid, child_ulid)
            )
            """
        )
        conn.execute("INSERT INTO qler_job_deps VALUES ('J001', 'J002')")

        conn.commit()
        conn.close()

        # Auto-detect must skip qler_job_deps and not crash
        conn = sqlite3.connect(db_path)
        try:
            mappings = _auto_detect_mappings(conn)
            assert len(mappings) == 2
            table_names = {m.table for m in mappings}
            assert table_names == {"qler_jobs", "qler_job_attempts"}
        finally:
            conn.close()

        # Full pipeline: 2 jobs + 1 attempt = 3 entries
        path = db_to_jsonl(db_path)
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]
            assert len(entries) == 3

            job_entries = [e for e in entries if e["thread_id"] == "qler_jobs"]
            attempt_entries = [e for e in entries if e["thread_id"] == "qler_job_attempts"]
            assert len(job_entries) == 2
            assert len(attempt_entries) == 1

            # Verify job content
            assert job_entries[0]["message"] == "[job] parent_job (J001) status=completed"
            assert job_entries[0]["level"] == "INFO"
            assert job_entries[1]["message"] == "[job] child_job (J002) status=pending"
            assert job_entries[1]["level"] == "INFO"

            # Verify attempt content
            assert attempt_entries[0]["message"] == "[attempt] job=J001 attempt=1 status=completed"
            assert attempt_entries[0]["level"] == "INFO"
        finally:
            os.unlink(path)


    def test_multiple_non_sqler_tables_all_skipped(self, tmp_path: Path):
        """Multiple non-sqler tables are all skipped (continue, not break)."""
        db_path = str(tmp_path / "multi_non_sqler.db")
        conn = sqlite3.connect(db_path)

        # sqler model table
        conn.execute(
            "CREATE TABLE events (_id INTEGER PRIMARY KEY, data JSON NOT NULL, status TEXT)"
        )
        conn.execute(
            "INSERT INTO events (_id, data, status) VALUES (1, ?, 'active')",
            (json.dumps({"name": "deploy", "created_at": "2024-01-15T12:00:00Z"}),),
        )

        # Two non-sqler tables (no _id)
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('version', '1.0')")

        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)")
        conn.execute("INSERT INTO schema_migrations VALUES (1, '2024-01-01')")

        conn.commit()
        conn.close()

        conn = sqlite3.connect(db_path)
        try:
            mappings = _auto_detect_mappings(conn)
            assert len(mappings) == 1
            assert mappings[0].table == "events"
        finally:
            conn.close()

    def test_only_non_sqler_tables_raises(self, tmp_path: Path):
        """Database with only non-sqler tables raises ValueError."""
        db_path = str(tmp_path / "no_sqler.db")
        conn = sqlite3.connect(db_path)

        conn.execute("CREATE TABLE qler_job_deps (parent_ulid TEXT, child_ulid TEXT)")
        conn.execute("INSERT INTO qler_job_deps VALUES ('J001', 'J002')")

        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('version', '1.0')")

        conn.commit()
        conn.close()

        with pytest.raises(ValueError, match="No tables found"):
            db_to_jsonl(db_path)


# ---------------------------------------------------------------------------
# Fix 2: Streaming fetchmany in _read_sqler_table
# ---------------------------------------------------------------------------


class TestFetchmanyStreaming:
    """Verify _read_sqler_table batched reading produces correct output.

    The batch size is 1000, so we need >1000 rows to exercise multiple
    batches. We use 3500 rows across 2 tables to verify:
    - Exact row count survives batching
    - Row order is preserved (ORDER BY _id)
    - Per-table timestamps are ordered after db_to_jsonl
    - Entry content is correct at batch boundaries
    """

    TOTAL_JOBS = 2500
    TOTAL_ATTEMPTS = 1000
    TOTAL_ENTRIES = TOTAL_JOBS + TOTAL_ATTEMPTS  # 3500

    @pytest.fixture()
    def large_db(self, tmp_path: Path) -> str:
        """Create a DB with 2500 jobs + 1000 attempts (3500 total entries)."""
        db_path = str(tmp_path / "large.db")
        conn = sqlite3.connect(db_path)

        conn.execute(
            """
            CREATE TABLE qler_jobs (
                _id INTEGER PRIMARY KEY AUTOINCREMENT,
                data JSON NOT NULL,
                _version INTEGER NOT NULL DEFAULT 1,
                ulid TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                queue_name TEXT NOT NULL DEFAULT 'default',
                priority INTEGER NOT NULL DEFAULT 0,
                eta INTEGER NOT NULL DEFAULT 0,
                lease_expires_at INTEGER
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE qler_job_attempts (
                _id INTEGER PRIMARY KEY AUTOINCREMENT,
                data JSON NOT NULL,
                _version INTEGER NOT NULL DEFAULT 1,
                ulid TEXT UNIQUE NOT NULL,
                job_ulid TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running'
            )
            """
        )

        base_ts = 1705312800  # 2024-01-15T10:00:00Z
        statuses = ["completed", "completed", "completed", "failed", "pending"]

        # Insert 2500 jobs
        job_rows = []
        for i in range(self.TOTAL_JOBS):
            data = json.dumps({
                "task": f"task_{i}",
                "attempts": 1,
                "correlation_id": f"corr-{i:04d}",
                "created_at": base_ts + i,
            })
            job_rows.append((data, f"J{i:05d}", statuses[i % 5]))

        conn.executemany(
            "INSERT INTO qler_jobs (data, ulid, status) VALUES (?, ?, ?)",
            job_rows,
        )

        # Insert 1000 attempts
        attempt_rows = []
        for i in range(self.TOTAL_ATTEMPTS):
            data = json.dumps({
                "attempt_number": 1,
                "worker_id": f"w-{i % 4}",
                "started_at": base_ts + i,
            })
            attempt_rows.append((data, f"A{i:05d}", f"J{i:05d}", "completed"))

        conn.executemany(
            "INSERT INTO qler_job_attempts (data, ulid, job_ulid, status) VALUES (?, ?, ?, ?)",
            attempt_rows,
        )

        conn.commit()
        conn.close()
        return db_path

    def test_exact_entry_count(self, large_db: str):
        """db_to_jsonl produces exactly TOTAL_JOBS + TOTAL_ATTEMPTS entries."""
        path = db_to_jsonl(large_db)
        try:
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == self.TOTAL_ENTRIES
        finally:
            os.unlink(path)

    def test_per_table_timestamps_sorted_with_bounds(self, large_db: str):
        """Entries within each table are sorted by timestamp; bounds match expected values."""
        path = db_to_jsonl(large_db)
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]
            assert len(entries) == self.TOTAL_ENTRIES

            # Split into per-table groups (streamed contiguously)
            from itertools import groupby

            tables = {}
            for table_name, group in groupby(entries, key=lambda e: e["thread_id"]):
                tables[table_name] = list(group)

            assert set(tables.keys()) == {"qler_jobs", "qler_job_attempts"}

            # Jobs: 2500 entries, timestamps from base_ts+0 to base_ts+2499
            job_ts = [e["timestamp"] for e in tables["qler_jobs"]]
            assert len(job_ts) == self.TOTAL_JOBS
            assert job_ts == sorted(job_ts)
            assert job_ts[0] == "2024-01-15T10:00:00+00:00"
            assert job_ts[-1] == "2024-01-15T10:41:39+00:00"

            # Attempts: 1000 entries, timestamps from base_ts+0 to base_ts+999
            attempt_ts = [e["timestamp"] for e in tables["qler_job_attempts"]]
            assert len(attempt_ts) == self.TOTAL_ATTEMPTS
            assert attempt_ts == sorted(attempt_ts)
            assert attempt_ts[0] == "2024-01-15T10:00:00+00:00"
            assert attempt_ts[-1] == "2024-01-15T10:16:39+00:00"
        finally:
            os.unlink(path)

    def test_no_gaps_or_duplicates_across_batches(self, large_db: str):
        """Correlation IDs must be a contiguous sequence — catches off-by-one at any batch seam."""
        path = db_to_jsonl(large_db, [qler_job_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]
            assert len(entries) == self.TOTAL_JOBS

            # Exact sequence check: catches gaps, duplicates, and reordering
            seen_ids = [e["correlation_id"] for e in entries]
            expected_ids = [f"corr-{i:04d}" for i in range(self.TOTAL_JOBS)]
            assert seen_ids == expected_ids
        finally:
            os.unlink(path)

    def test_fetchmany_actually_called(self, large_db: str):
        """Verify _read_sqler_table uses fetchmany in multiple batches, not fetchall."""
        fetchmany_calls = []

        class SpyCursor:
            """Wraps a real cursor, tracking fetchmany calls."""

            def __init__(self, real_cursor):
                self._cursor = real_cursor

            def fetchone(self):
                return self._cursor.fetchone()

            def fetchall(self):
                return self._cursor.fetchall()

            def fetchmany(self, size=1):
                result = self._cursor.fetchmany(size)
                fetchmany_calls.append((size, len(result)))
                return result

            def __iter__(self):
                return iter(self._cursor)

        class SpyConnection:
            """Wraps a real connection, returning SpyCursors."""

            def __init__(self, real_conn):
                self._conn = real_conn

            def execute(self, sql, *args, **kwargs):
                cursor = self._conn.execute(sql, *args, **kwargs)
                return SpyCursor(cursor)

        real_conn = sqlite3.connect(large_db)
        real_conn.row_factory = sqlite3.Row
        spy_conn = SpyConnection(real_conn)
        try:
            rows = _read_sqler_table(spy_conn, qler_job_mapping())
            assert len(rows) == self.TOTAL_JOBS
            # ceil(2500/1000) = 3 data batches + 1 empty sentinel = 4 calls
            assert len(fetchmany_calls) == 4
            assert fetchmany_calls[0] == (1000, 1000)  # batch 1: full
            assert fetchmany_calls[1] == (1000, 1000)  # batch 2: full
            assert fetchmany_calls[2] == (1000, 500)   # batch 3: partial
            assert fetchmany_calls[3] == (1000, 0)     # sentinel: empty
        finally:
            real_conn.close()

    def test_level_distribution_large(self, large_db: str):
        """Level distribution is correct across batched reads."""
        path = db_to_jsonl(large_db, [qler_job_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]
            assert len(entries) == self.TOTAL_JOBS

            level_counts: dict[str, int] = {}
            for e in entries:
                level_counts[e["level"]] = level_counts.get(e["level"], 0) + 1

            # statuses cycle: completed, completed, completed, failed, pending
            # 3/5 completed=INFO, 1/5 failed=ERROR, 1/5 pending=INFO
            # So INFO = 4/5 * 2500 = 2000, ERROR = 1/5 * 2500 = 500
            assert level_counts["INFO"] == 2000
            assert level_counts["ERROR"] == 500
        finally:
            os.unlink(path)


class TestBuildEntryFallbacks:
    def test_missing_timestamp_uses_now(self):
        """Row with no timestamp field gets a generated timestamp."""
        mapping = DbTableMapping(
            table="test", timestamp_field="ts", message_template="row {_id}"
        )
        entry = _build_entry({"_id": 1}, mapping, 0)
        assert "T" in entry["timestamp"]
        assert "+" in entry["timestamp"]

    def test_bad_template_falls_back(self):
        """Template that raises ValueError falls back to generic message."""
        mapping = DbTableMapping(
            table="test",
            timestamp_field="ts",
            timestamp_format="iso",
            message_template="{field.__class__}",  # triggers restricted formatter
        )
        entry = _build_entry({"_id": 42, "ts": "2024-01-15T10:00:00Z", "field": "x"}, mapping, 0)
        assert entry["message"] == "test row 42"

    def test_no_level_map_uppercases_raw(self):
        """With level_map=None, raw level value is uppercased."""
        mapping = DbTableMapping(
            table="test",
            timestamp_field="ts",
            timestamp_format="iso",
            level_field="status",
            level_map=None,
            message_template="row {_id}",
        )
        entry = _build_entry({"_id": 1, "ts": "2024-01-15T10:00:00Z", "status": "warning"}, mapping, 0)
        assert entry["level"] == "WARNING"

    def test_no_level_field_defaults_info(self):
        """With level_field=None, level defaults to INFO."""
        mapping = DbTableMapping(
            table="test",
            timestamp_field="ts",
            timestamp_format="iso",
            level_field=None,
            message_template="row {_id}",
        )
        entry = _build_entry({"_id": 1, "ts": "2024-01-15T10:00:00Z"}, mapping, 0)
        assert entry["level"] == "INFO"
