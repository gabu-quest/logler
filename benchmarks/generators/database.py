"""Database generator — deterministic sqler SQLite databases for benchmarks.

Mirrors the LogGenerator pattern: seeded RNG, deterministic output,
``generate()`` returns data, ``write_db()`` writes to SQLite.
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path


class DatabaseGenerator:
    """Generates deterministic sqler-compatible SQLite databases for benchmarks.

    Produces a ``qler_jobs`` table with realistic status distributions,
    sequential timestamps with jitter, and deterministic ULIDs.
    """

    STATUSES = ["completed", "failed", "pending", "running", "cancelled"]
    STATUS_WEIGHTS = [0.65, 0.15, 0.10, 0.05, 0.05]

    TASKS = [
        "send_email",
        "process_payment",
        "generate_report",
        "sync_inventory",
        "resize_image",
        "send_notification",
        "cleanup_sessions",
        "reindex_search",
        "backup_database",
        "aggregate_metrics",
    ]

    QUEUES = ["default", "high", "low", "critical", "bulk"]

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.base_ts = 1705312800  # 2024-01-15T10:00:00Z

    def generate(self, num_rows: int) -> list[dict]:
        """Generate a list of sqler job rows as dicts.

        Each dict has the schema expected by ``qler_job_mapping()``:
        promoted columns (ulid, status, queue_name, priority, eta,
        lease_expires_at) plus a ``data`` JSON blob containing
        task, attempts, correlation_id, created_at.

        Args:
            num_rows: Number of job rows to generate.

        Returns:
            List of row dicts ready for ``write_db()``.
        """
        rows = []
        ts = float(self.base_ts)

        for i in range(num_rows):
            ts += self.rng.uniform(0.5, 5.0)
            status = self.rng.choices(self.STATUSES, weights=self.STATUS_WEIGHTS, k=1)[0]
            task = self.rng.choice(self.TASKS)
            queue = self.rng.choice(self.QUEUES)
            priority = self.rng.randint(0, 10)
            attempts = self.rng.randint(1, 5) if status in ("completed", "failed") else 0
            suffix = self.rng.randint(10000000, 99999999)
            ulid = f"{i:08d}{suffix}"

            data = {
                "task": task,
                "attempts": attempts,
                "correlation_id": f"corr-{i:06d}",
                "created_at": ts,
            }

            rows.append(
                {
                    "data": json.dumps(data),
                    "_version": 1,
                    "ulid": ulid,
                    "status": status,
                    "queue_name": queue,
                    "priority": priority,
                    "eta": 0,
                    "lease_expires_at": None,
                }
            )

        return rows

    def write_db(self, path: str | Path, rows: list[dict]) -> int:
        """Write rows to a sqler-compatible SQLite database.

        Creates the ``qler_jobs`` table with the expected schema and
        inserts all rows.

        Args:
            path: Path to the SQLite database file (created or overwritten).
            rows: List of row dicts from ``generate()``.

        Returns:
            Number of rows written.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing file to ensure clean state
        if path.exists():
            path.unlink()

        conn = sqlite3.connect(str(path))
        try:
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

            conn.executemany(
                """
                INSERT INTO qler_jobs (data, _version, ulid, status, queue_name, priority, eta, lease_expires_at)
                VALUES (:data, :_version, :ulid, :status, :queue_name, :priority, :eta, :lease_expires_at)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        return len(rows)
