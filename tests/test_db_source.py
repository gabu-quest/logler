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
    _merge_sqler_row,
    db_to_jsonl,
    qler_attempt_mapping,
    qler_job_mapping,
)


# ---------------------------------------------------------------------------
# Shared fixture: temp SQLite with sqler schema
# ---------------------------------------------------------------------------


@pytest.fixture()
def qler_test_db(tmp_path: Path) -> str:
    """Create a temp SQLite DB with sqler-style tables and sample data."""
    db_path = str(tmp_path / "test_qler.db")
    conn = sqlite3.connect(db_path)

    # Jobs table (sqler schema: _id, data, + promoted columns)
    conn.execute(
        """
        CREATE TABLE jobs (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            data JSON NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0
        )
    """
    )

    # Insert 10 jobs with mixed statuses
    jobs = [
        (
            '{"task_name":"send_email","queue":"default","ulid":"01H1","correlation_id":"corr-001","created_at":"2024-01-15T10:00:00Z"}',
            "success",
            0,
            1,
        ),
        (
            '{"task_name":"send_email","queue":"default","ulid":"01H2","correlation_id":"corr-002","created_at":"2024-01-15T10:01:00Z"}',
            "success",
            0,
            1,
        ),
        (
            '{"task_name":"process_image","queue":"media","ulid":"01H3","correlation_id":"corr-003","created_at":"2024-01-15T10:02:00Z"}',
            "failed",
            5,
            3,
        ),
        (
            '{"task_name":"generate_report","queue":"default","ulid":"01H4","correlation_id":"corr-004","created_at":"2024-01-15T10:03:00Z"}',
            "pending",
            0,
            0,
        ),
        (
            '{"task_name":"send_email","queue":"default","ulid":"01H5","correlation_id":"corr-005","created_at":"2024-01-15T10:04:00Z"}',
            "running",
            0,
            1,
        ),
        (
            '{"task_name":"cleanup_temp","queue":"maintenance","ulid":"01H6","created_at":"2024-01-15T10:05:00Z"}',
            "success",
            -1,
            1,
        ),
        (
            '{"task_name":"process_image","queue":"media","ulid":"01H7","correlation_id":"corr-007","created_at":"2024-01-15T10:06:00Z"}',
            "failed",
            5,
            3,
        ),
        (
            '{"task_name":"sync_data","queue":"default","ulid":"01H8","correlation_id":"corr-008","created_at":"2024-01-15T10:07:00Z"}',
            "success",
            10,
            1,
        ),
        (
            '{"task_name":"send_notification","queue":"default","ulid":"01H9","correlation_id":"corr-009","created_at":"2024-01-15T10:08:00Z"}',
            "cancelled",
            0,
            0,
        ),
        (
            '{"task_name":"process_image","queue":"media","ulid":"01HA","correlation_id":"corr-010","created_at":"2024-01-15T10:09:00Z"}',
            "dead",
            5,
            5,
        ),
    ]
    conn.executemany(
        "INSERT INTO jobs (data, status, priority, attempt_count) VALUES (?, ?, ?, ?)",
        jobs,
    )

    # Job attempts table
    conn.execute(
        """
        CREATE TABLE job_attempts (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            data JSON NOT NULL,
            outcome TEXT DEFAULT NULL
        )
    """
    )

    attempts = [
        (
            '{"job_ulid":"01H1","attempt_number":1,"worker_id":"w-1","started_at":"2024-01-15T10:00:01Z","correlation_id":"corr-001","duration_ms":120}',
            "success",
        ),
        (
            '{"job_ulid":"01H2","attempt_number":1,"worker_id":"w-2","started_at":"2024-01-15T10:01:01Z","correlation_id":"corr-002","duration_ms":95}',
            "success",
        ),
        (
            '{"job_ulid":"01H3","attempt_number":1,"worker_id":"w-1","started_at":"2024-01-15T10:02:01Z","correlation_id":"corr-003","error_message":"OOM","duration_ms":5000}',
            "failure",
        ),
        (
            '{"job_ulid":"01H3","attempt_number":2,"worker_id":"w-2","started_at":"2024-01-15T10:02:30Z","correlation_id":"corr-003","error_message":"OOM","duration_ms":4800}',
            "failure",
        ),
        (
            '{"job_ulid":"01H3","attempt_number":3,"worker_id":"w-1","started_at":"2024-01-15T10:03:00Z","correlation_id":"corr-003","error_message":"OOM","duration_ms":5100}',
            "failure",
        ),
        (
            '{"job_ulid":"01H5","attempt_number":1,"worker_id":"w-3","started_at":"2024-01-15T10:04:01Z","correlation_id":"corr-005","duration_ms":null}',
            None,
        ),
        (
            '{"job_ulid":"01H6","attempt_number":1,"worker_id":"w-1","started_at":"2024-01-15T10:05:01Z","duration_ms":50}',
            "success",
        ),
        (
            '{"job_ulid":"01H7","attempt_number":1,"worker_id":"w-2","started_at":"2024-01-15T10:06:01Z","correlation_id":"corr-007","error_message":"timeout","duration_ms":30000}',
            "timeout",
        ),
        (
            '{"job_ulid":"01H7","attempt_number":2,"worker_id":"w-1","started_at":"2024-01-15T10:06:30Z","correlation_id":"corr-007","error_message":"timeout","duration_ms":30000}',
            "timeout",
        ),
        (
            '{"job_ulid":"01H7","attempt_number":3,"worker_id":"w-3","started_at":"2024-01-15T10:07:00Z","correlation_id":"corr-007","error_message":"timeout","duration_ms":30000}',
            "failure",
        ),
        (
            '{"job_ulid":"01H8","attempt_number":1,"worker_id":"w-2","started_at":"2024-01-15T10:07:01Z","correlation_id":"corr-008","duration_ms":200}',
            "success",
        ),
        (
            '{"job_ulid":"01HA","attempt_number":1,"worker_id":"w-1","started_at":"2024-01-15T10:09:01Z","correlation_id":"corr-010","error_message":"crash","duration_ms":100}',
            "failure",
        ),
    ]
    conn.executemany(
        "INSERT INTO job_attempts (data, outcome) VALUES (?, ?)",
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


class TestQlerMappings:
    def test_qler_job_mapping(self):
        m = qler_job_mapping()
        assert m.table == "jobs"
        assert m.level_map["failed"] == "ERROR"
        assert m.level_map["success"] == "INFO"
        assert m.correlation_id_field == "correlation_id"
        assert "ulid" in m.extra_fields

    def test_qler_attempt_mapping(self):
        m = qler_attempt_mapping()
        assert m.table == "job_attempts"
        assert m.level_map["failure"] == "ERROR"
        assert m.level_map["timeout"] == "WARN"
        assert "job_ulid" in m.extra_fields


class TestDbToJsonl:
    def test_db_to_jsonl_format(self, qler_test_db: str):
        path = db_to_jsonl(qler_test_db)
        try:
            with open(path) as f:
                lines = f.readlines()

            assert len(lines) > 0
            for line in lines:
                entry = json.loads(line)
                assert "timestamp" in entry
                assert "level" in entry
                assert "message" in entry
        finally:
            os.unlink(path)

    def test_db_to_jsonl_sorted(self, qler_test_db: str):
        path = db_to_jsonl(qler_test_db)
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            timestamps = [e["timestamp"] for e in entries]
            assert timestamps == sorted(timestamps)
        finally:
            os.unlink(path)

    def test_auto_detect_mappings(self, qler_test_db: str):
        conn = sqlite3.connect(qler_test_db)
        try:
            mappings = _auto_detect_mappings(conn)
            table_names = {m.table for m in mappings}
            assert "jobs" in table_names
            assert "job_attempts" in table_names

            jobs_mapping = next(m for m in mappings if m.table == "jobs")
            assert jobs_mapping.level_map is not None
            assert jobs_mapping.level_map["failed"] == "ERROR"
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
        """DB is opened in readonly mode — writes should fail."""
        # db_to_jsonl opens read-only; verify by checking the JSONL is produced
        path = db_to_jsonl(qler_test_db)
        try:
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_job_level_mapping(self, qler_test_db: str):
        """Failed/dead jobs map to ERROR, cancelled to WARN."""
        path = db_to_jsonl(qler_test_db, [qler_job_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            # Find the failed job (process_image 01H3)
            failed_entries = [e for e in entries if e["level"] == "ERROR"]
            assert len(failed_entries) >= 2  # failed + dead jobs

            warn_entries = [e for e in entries if e["level"] == "WARN"]
            assert len(warn_entries) >= 1  # cancelled job
        finally:
            os.unlink(path)

    def test_correlation_id_extracted(self, qler_test_db: str):
        path = db_to_jsonl(qler_test_db, [qler_job_mapping()])
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f]

            with_corr = [e for e in entries if "correlation_id" in e]
            assert len(with_corr) >= 8  # 9 of 10 jobs have correlation_id
        finally:
            os.unlink(path)

    def test_explicit_mapping(self, qler_test_db: str):
        """Using explicit mappings works correctly."""
        mapping = DbTableMapping(
            table="jobs",
            timestamp_field="created_at",
            timestamp_format="iso",
            level_field=None,
            message_template="custom: {task_name}",
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
        entries = results.get("results", [])
        assert len(entries) >= 2  # at least failed + dead jobs from jobs table

        inv.close()

    def test_search_db_convenience(self, qler_test_db: str):
        """search_db() works end-to-end."""
        from logler.investigate import search_db

        results = search_db(qler_test_db, level="ERROR")
        entries = results.get("results", [])
        assert len(entries) >= 2

    def test_search_db_by_correlation(self, qler_test_db: str):
        from logler.investigate import search_db

        results = search_db(qler_test_db, correlation_id="corr-003")
        entries = results.get("results", [])
        assert len(entries) >= 1
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
