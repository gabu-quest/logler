"""Tests for the --db flag on `logler llm search`."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

EXIT_SUCCESS = 0
EXIT_NO_RESULTS = 1
EXIT_USER_ERROR = 2


def run_llm_command(args, timeout=60):
    """Run a logler llm command and return result."""
    cmd = [".venv/bin/python", "-m", "logler.cli", "llm"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path(__file__).parent.parent),
    )
    return result


@pytest.fixture()
def qler_test_db(tmp_path: Path) -> str:
    """Create a temp SQLite DB with sqler-style tables and sample data."""
    db_path = str(tmp_path / "test_qler.db")
    conn = sqlite3.connect(db_path)

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

    jobs = [
        (
            '{"task_name":"send_email","queue":"default","ulid":"01H1","correlation_id":"corr-123","created_at":"2024-01-15T10:00:00Z"}',
            "success",
            0,
            1,
        ),
        (
            '{"task_name":"process_image","queue":"media","ulid":"01H2","correlation_id":"corr-456","created_at":"2024-01-15T10:01:00Z"}',
            "failed",
            5,
            3,
        ),
        (
            '{"task_name":"generate_report","queue":"default","ulid":"01H3","correlation_id":"corr-789","created_at":"2024-01-15T10:02:00Z"}',
            "pending",
            0,
            0,
        ),
    ]
    conn.executemany(
        "INSERT INTO jobs (data, status, priority, attempt_count) VALUES (?, ?, ?, ?)",
        jobs,
    )
    conn.commit()
    conn.close()
    return db_path


class TestSearchDbFlag:
    def test_search_db_flag(self, qler_test_db: str):
        """--db returns results from the database."""
        result = run_llm_command(["search", "--db", qler_test_db])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["summary"]["total_matches"] >= 3

    def test_search_db_level_filter(self, qler_test_db: str):
        """--db --level ERROR filters correctly."""
        result = run_llm_command(["search", "--db", qler_test_db, "--level", "ERROR"])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["summary"]["total_matches"] >= 1
        for entry in output["results"]:
            assert entry["level"] == "ERROR"

    def test_search_db_correlation(self, qler_test_db: str):
        """--db --correlation filters by correlation ID."""
        result = run_llm_command(["search", "--db", qler_test_db, "--correlation", "corr-123"])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["summary"]["total_matches"] >= 1
        for entry in output["results"]:
            assert entry.get("correlation_id") == "corr-123"

    def test_no_files_no_db_error(self):
        """Exit code 2 when neither FILES nor --db provided."""
        result = run_llm_command(["search"])
        assert result.returncode == EXIT_USER_ERROR
