"""Tests for the --db flag on LLM CLI commands."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

EXIT_SUCCESS = 0
EXIT_NO_RESULTS = 1
EXIT_USER_ERROR = 2


def run_llm_command(args, timeout=60, env=None):
    """Run a logler llm command and return result."""
    cmd = [".venv/bin/python", "-m", "logler.cli", "llm"] + args
    run_env = None
    if env:
        run_env = {**os.environ, **env}
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path(__file__).parent.parent),
        env=run_env,
    )
    return result


@pytest.fixture()
def qler_test_db(tmp_path: Path) -> str:
    """Create a temp SQLite DB with qler_jobs table and sample data.

    3 jobs:
      - send_email: completed (INFO), corr-123
      - process_image: failed (ERROR), corr-456
      - generate_report: pending (INFO), corr-789
    """
    db_path = str(tmp_path / "test_qler.db")
    conn = sqlite3.connect(db_path)

    conn.execute(
        """
        CREATE TABLE qler_jobs (
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
            json.dumps(
                {
                    "task": "send_email",
                    "queue_name": "default",
                    "ulid": "01H1",
                    "correlation_id": "corr-123",
                    "created_at": 1705312800,
                }
            ),
            "completed",
            0,
            1,
        ),
        (
            json.dumps(
                {
                    "task": "process_image",
                    "queue_name": "media",
                    "ulid": "01H2",
                    "correlation_id": "corr-456",
                    "created_at": 1705312860,
                }
            ),
            "failed",
            5,
            3,
        ),
        (
            json.dumps(
                {
                    "task": "generate_report",
                    "queue_name": "default",
                    "ulid": "01H3",
                    "correlation_id": "corr-789",
                    "created_at": 1705312920,
                }
            ),
            "pending",
            0,
            0,
        ),
    ]
    conn.executemany(
        "INSERT INTO qler_jobs (data, status, priority, attempt_count) VALUES (?, ?, ?, ?)",
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
        assert output["summary"]["total_matches"] == 3
        messages = [e["message"] for e in output["results"]]
        assert any("send_email" in m for m in messages)
        assert any("process_image" in m for m in messages)

    def test_search_db_level_filter(self, qler_test_db: str):
        """--db --level ERROR filters correctly."""
        result = run_llm_command(["search", "--db", qler_test_db, "--level", "ERROR"])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["summary"]["total_matches"] == 1
        assert len(output["results"]) == 1
        assert output["results"][0]["level"] == "ERROR"

    def test_search_db_correlation(self, qler_test_db: str):
        """--db --correlation filters by correlation ID."""
        result = run_llm_command(
            ["search", "--db", qler_test_db, "--correlation", "corr-123"]
        )
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["summary"]["total_matches"] == 1
        assert output["results"][0]["correlation_id"] == "corr-123"

    def test_no_files_no_db_error(self):
        """Exit code 2 when neither FILES nor --db provided."""
        result = run_llm_command(["search"])
        assert result.returncode == EXIT_USER_ERROR


class TestDbFlagUniversal:
    """Test that --db works across multiple LLM CLI commands."""

    def test_schema_db(self, qler_test_db: str):
        """schema --db returns field info from database."""
        result = run_llm_command(["schema", "--db", qler_test_db])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["total_entries"] == 3
        assert output["files_analyzed"] == 1

    def test_ids_db(self, qler_test_db: str):
        """ids --db discovers IDs from database."""
        result = run_llm_command(["ids", "--db", qler_test_db])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert len(output.get("thread_ids", [])) >= 1

    def test_sample_db(self, qler_test_db: str):
        """sample --db returns entries from database."""
        result = run_llm_command(
            ["sample", "--db", qler_test_db, "--strategy", "head", "--size", "10"]
        )
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert len(output["entries"]) == 3

    def test_triage_db(self, qler_test_db: str):
        """triage --db assesses severity from database."""
        result = run_llm_command(["triage", "--db", qler_test_db])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["metrics"]["total_entries"] == 3
        assert output["metrics"]["error_count"] == 1

    def test_summarize_db(self, qler_test_db: str):
        """summarize --db produces summary from database."""
        result = run_llm_command(["summarize", "--db", qler_test_db])
        assert result.returncode == EXIT_SUCCESS
        output = json.loads(result.stdout)
        assert output["stats"]["total_entries"] == 3

    def test_detect_db(self, qler_test_db: str):
        """detect --db auto-detects format from database JSONL."""
        result = run_llm_command(["detect", "--db", qler_test_db])
        assert result.returncode == EXIT_SUCCESS

    def test_metrics_db(self, qler_test_db: str):
        """metrics --db extracts numeric values from database."""
        result = run_llm_command(["metrics", "--db", qler_test_db])
        assert result.returncode in (EXIT_SUCCESS, EXIT_NO_RESULTS)

    def test_templates_db(self, qler_test_db: str):
        """templates --db mines patterns from database."""
        result = run_llm_command(["templates", "--db", qler_test_db])
        assert result.returncode in (EXIT_SUCCESS, EXIT_NO_RESULTS)

    @pytest.mark.parametrize(
        "cmd",
        [
            ["schema"],
            ["ids"],
            ["sample"],
            ["triage"],
            ["summarize"],
            ["metrics"],
            ["detect"],
            ["templates"],
            ["verify-pattern", "--pattern", "test"],
            ["emit"],
            ["diff"],
        ],
    )
    def test_no_files_no_db_gives_exit_2(self, cmd):
        """Commands with argument-based FILES give exit 2 with no input."""
        result = run_llm_command(cmd)
        assert result.returncode == EXIT_USER_ERROR


class TestSessionDb:
    """Test --db support in session commands."""

    def test_session_create_db(self, qler_test_db: str, tmp_path: Path):
        """session create --db persists db_path in session JSON."""
        env = {"HOME": str(tmp_path)}
        result = run_llm_command(["session", "create", "--db", qler_test_db], env=env)
        assert result.returncode == EXIT_SUCCESS, result.stderr
        output = json.loads(result.stdout)
        assert output["status"] == "active"
        assert output["db_path"] == os.path.realpath(qler_test_db)
        assert output["files"] == []

    def test_session_create_no_files_no_db(self, tmp_path: Path):
        """session create with neither --files nor --db gives exit 2."""
        env = {"HOME": str(tmp_path)}
        result = run_llm_command(["session", "create"], env=env)
        assert result.returncode == EXIT_USER_ERROR

    def test_session_query_stored_db(self, qler_test_db: str, tmp_path: Path):
        """session query uses stored db_path from create."""
        env = {"HOME": str(tmp_path)}
        # Create session with --db
        create_result = run_llm_command(
            ["session", "create", "--db", qler_test_db], env=env
        )
        assert create_result.returncode == EXIT_SUCCESS, create_result.stderr
        session_id = json.loads(create_result.stdout)["session_id"]

        # Query without --db — should use stored db_path
        query_result = run_llm_command(
            ["session", "query", session_id], env=env
        )
        assert query_result.returncode == EXIT_SUCCESS, query_result.stderr
        output = json.loads(query_result.stdout)
        assert output["total_matches"] == 3
        assert len(output["results"]) == 3
        # Verify actual content from the fixture
        entries = [r.get("entry", r) for r in output["results"]]
        levels = [e["level"] for e in entries]
        assert "ERROR" in levels
        messages = [e["message"] for e in entries]
        assert any("process_image" in m for m in messages)

    def test_session_query_db_override(self, qler_test_db: str, tmp_path: Path):
        """session query --db overrides stored session files."""
        env = {"HOME": str(tmp_path)}
        # Create a session with a dummy log file containing a sentinel
        dummy_log = tmp_path / "dummy.log"
        dummy_log.write_text(
            '{"timestamp":"2024-01-15T10:00:00Z","level":"WARN","message":"DUMMY_SENTINEL"}\n'
        )
        create_result = run_llm_command(
            ["session", "create", "-f", str(dummy_log)], env=env
        )
        assert create_result.returncode == EXIT_SUCCESS, create_result.stderr
        session_id = json.loads(create_result.stdout)["session_id"]

        # Query with --db override — should include DB data + dummy file
        query_result = run_llm_command(
            ["session", "query", session_id, "--db", qler_test_db], env=env
        )
        assert query_result.returncode == EXIT_SUCCESS, query_result.stderr
        output = json.loads(query_result.stdout)
        # DB has 3 entries + dummy file has 1 = 4 total
        assert output["total_matches"] == 4
        entries = [r.get("entry", r) for r in output["results"]]
        messages = [e["message"] for e in entries]
        # DB entries present
        assert any("send_email" in m for m in messages)
        # Dummy file entry also present (override adds to session files)
        assert any("DUMMY_SENTINEL" in m for m in messages)

    def test_session_correlation_tracking(self, qler_test_db: str, tmp_path: Path):
        """session query tracks correlation IDs in session JSON."""
        env = {"HOME": str(tmp_path)}
        # Create session
        create_result = run_llm_command(
            ["session", "create", "--db", qler_test_db], env=env
        )
        assert create_result.returncode == EXIT_SUCCESS, create_result.stderr
        session_id = json.loads(create_result.stdout)["session_id"]

        # Query to populate correlations
        run_llm_command(["session", "query", session_id], env=env)

        # Read session JSON to verify correlation_ids were stored
        session_file = tmp_path / ".logler" / "sessions" / f"{session_id}.json"
        with open(session_file) as f:
            session_data = json.load(f)
        # qler_test_db has 3 jobs with correlation IDs: corr-123, corr-456, corr-789
        assert len(session_data["correlation_ids"]) == 3
        assert "corr-123" in session_data["correlation_ids"]
        assert "corr-456" in session_data["correlation_ids"]
        assert "corr-789" in session_data["correlation_ids"]

    def test_session_list_shows_db_info(self, qler_test_db: str, tmp_path: Path):
        """session list shows has_db and correlation_count."""
        env = {"HOME": str(tmp_path)}
        # Create + query to get correlations
        create_result = run_llm_command(
            ["session", "create", "--db", qler_test_db], env=env
        )
        assert create_result.returncode == EXIT_SUCCESS, create_result.stderr
        session_id = json.loads(create_result.stdout)["session_id"]
        run_llm_command(["session", "query", session_id], env=env)

        # List sessions
        list_result = run_llm_command(["session", "list"], env=env)
        assert list_result.returncode == EXIT_SUCCESS, list_result.stderr
        output = json.loads(list_result.stdout)
        assert len(output["sessions"]) == 1
        sess = output["sessions"][0]
        assert sess["has_db"] is True
        assert sess["correlation_count"] == 3

    def test_session_query_missing_session(self, tmp_path: Path):
        """Querying a nonexistent session returns exit 2."""
        env = {"HOME": str(tmp_path)}
        result = run_llm_command(["session", "query", "sess_doesnotexist"], env=env)
        assert result.returncode == EXIT_USER_ERROR
        error = json.loads(result.stdout)
        assert "sess_doesnotexist" in error["error"]

    def test_session_list_file_session_has_db_false(self, tmp_path: Path):
        """File-backed session shows has_db=False."""
        env = {"HOME": str(tmp_path)}
        dummy = tmp_path / "dummy.log"
        dummy.write_text(
            '{"timestamp":"2024-01-15T10:00:00Z","level":"INFO","message":"x"}\n'
        )
        run_llm_command(["session", "create", "-f", str(dummy)], env=env)
        result = run_llm_command(["session", "list"], env=env)
        assert result.returncode == EXIT_SUCCESS
        sessions = json.loads(result.stdout)["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["has_db"] is False
        assert sessions[0]["correlation_count"] == 0
