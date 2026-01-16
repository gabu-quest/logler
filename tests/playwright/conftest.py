"""Playwright E2E test fixtures for logler web UI."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

# Add src to path for imports
ROOT = Path(__file__).parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _find_free_port() -> int:
    """Find a free port on localhost."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="session")
def server_url():
    """Start logler web server for E2E tests."""
    import uvicorn
    from logler.web.app import app

    port = _find_free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    # Start server in background thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to be ready
    base_url = f"http://127.0.0.1:{port}"
    import httpx

    for _ in range(100):  # 10 seconds max
        try:
            resp = httpx.get(base_url, timeout=0.5)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError("Server failed to start within 10 seconds")

    yield base_url

    # Cleanup
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def example_logs_dir() -> Path:
    """Path to example log files."""
    return ROOT / "examples" / "logs"


@pytest.fixture
def production_log(example_logs_dir) -> Path:
    """Production incident log file."""
    return example_logs_dir / "production_incident.log"


@pytest.fixture
def microservices_log(example_logs_dir) -> Path:
    """Microservices trace log file."""
    return example_logs_dir / "microservices_trace.log"


@pytest.fixture
def large_log(example_logs_dir) -> Path:
    """Large log file (10K entries)."""
    return example_logs_dir / "huge" / "massive_incident.log"


@pytest.fixture
def test_log_file(tmp_path) -> Path:
    """Create a test log file with predictable content."""
    log_file = tmp_path / "test.log"
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    entries = []
    for i in range(50):
        level = "ERROR" if i % 10 == 0 else "WARN" if i % 5 == 0 else "INFO"
        entries.append(
            {
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "level": level,
                "message": f"Test message {i}",
                "thread_id": f"worker-{i % 3}",
                "correlation_id": f"req-{i // 10:03d}",
            }
        )

    with open(log_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return log_file


@pytest.fixture
def multi_thread_log(tmp_path) -> Path:
    """Create a log file with multiple distinct threads."""
    log_file = tmp_path / "multi_thread.log"
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    entries = []
    threads = ["api-handler", "db-worker", "cache-manager", "queue-processor"]
    for i in range(40):
        thread = threads[i % len(threads)]
        level = "ERROR" if thread == "db-worker" and i > 30 else "INFO"
        entries.append(
            {
                "timestamp": (base_time + timedelta(milliseconds=i * 100)).isoformat(),
                "level": level,
                "message": f"{thread} processing request {i}",
                "thread_id": thread,
                "correlation_id": f"req-{i // 4:03d}",
            }
        )

    with open(log_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return log_file


@pytest.fixture
def hierarchy_log(tmp_path) -> Path:
    """Create a log file suitable for hierarchy testing."""
    log_file = tmp_path / "hierarchy.log"
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    entries = [
        {
            "timestamp": (base_time + timedelta(milliseconds=0)).isoformat(),
            "level": "INFO",
            "message": "Request started",
            "thread_id": "main",
            "correlation_id": "req-hierarchy-001",
            "span_id": "span-001",
        },
        {
            "timestamp": (base_time + timedelta(milliseconds=10)).isoformat(),
            "level": "INFO",
            "message": "Auth check",
            "thread_id": "auth",
            "correlation_id": "req-hierarchy-001",
            "span_id": "span-002",
            "parent_span_id": "span-001",
        },
        {
            "timestamp": (base_time + timedelta(milliseconds=50)).isoformat(),
            "level": "INFO",
            "message": "Database query",
            "thread_id": "db",
            "correlation_id": "req-hierarchy-001",
            "span_id": "span-003",
            "parent_span_id": "span-001",
        },
        {
            "timestamp": (base_time + timedelta(milliseconds=200)).isoformat(),
            "level": "ERROR",
            "message": "Database timeout",
            "thread_id": "db",
            "correlation_id": "req-hierarchy-001",
            "span_id": "span-003",
        },
        {
            "timestamp": (base_time + timedelta(milliseconds=250)).isoformat(),
            "level": "ERROR",
            "message": "Request failed",
            "thread_id": "main",
            "correlation_id": "req-hierarchy-001",
            "span_id": "span-001",
        },
    ]

    with open(log_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return log_file
