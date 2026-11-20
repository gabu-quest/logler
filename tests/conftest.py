"""Test configuration for Logler.

Ensures the local `src` layout is importable without requiring an editable
install when running `pytest` from the repository root.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

# The one owner of "which python" and "which logler" for every subprocess test:
# the interpreter running pytest, and the console script installed beside it.
PYTHON = sys.executable
LOGLER = str(
    Path(sysconfig.get_path("scripts")) / ("logler.exe" if sys.platform == "win32" else "logler")
)


def pytest_sessionstart(session):
    """Stop the whole session when the compiled extension cannot be imported.

    Tests never build it and never skip for its absence: a green run without
    the extension would prove nothing.
    """
    try:
        import logler_rs  # noqa: F401
    except Exception as exc:
        from logler._search_core import BUILD_HINT

        pytest.exit(
            f"logler_rs (the compiled extension) cannot be imported: {exc!r}. "
            f"Build it first: {BUILD_HINT}",
            returncode=3,
        )


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Give every test a home folder of its own.

    Both this process and every child process see it, so nothing a test runs
    can read or write the real ``~/.logler``.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture(autouse=True)
def _clear_investigator_cache():
    """Free cached PyInvestigator instances after every test.

    The cache module keeps parsed Rust objects alive across calls.  Stress
    tests create multiple large temp files and the accumulated Rust heap
    can exhaust swap, so we flush between tests.
    """
    yield
    try:
        from logler.cache import clear_cache

        clear_cache()
    except Exception:
        pass


@pytest.fixture(scope="session")
def rust_backend():
    import logler_rs

    return logler_rs


@pytest.fixture(scope="session")
def investigate_module(rust_backend):
    import logler.investigate as investigate

    investigate = importlib.reload(investigate)
    assert getattr(investigate, "RUST_AVAILABLE", False), (
        "logler.investigate reports RUST_AVAILABLE=False"
    )
    return investigate


# =============================================================================
# Deterministic Test Fixtures
# =============================================================================
# These fixtures have KNOWN, EXACT values so tests can assert exact outputs.
# When writing tests, use these fixtures and assert specific expected values.


@pytest.fixture
def deterministic_log_file():
    """100 log entries with predictable patterns.

    Structure:
    - Lines 0,4,8...96:  level=INFO,  thread=worker-0
    - Lines 1,5,9...97:  level=DEBUG, thread=worker-1
    - Lines 2,6,10...98: level=WARN,  thread=worker-2
    - Lines 3,7,11...99: level=ERROR, thread=worker-3

    Correlation IDs: req-{line_number % 10}
    Messages: "Log message number {line_number}"

    Expected counts:
    - Total entries: 100
    - Per level: 25 each (INFO, DEBUG, WARN, ERROR)
    - Per thread: 25 each (worker-0 through worker-3)
    - Per correlation: 10 each (req-0 through req-9)
    """
    levels = ["INFO", "DEBUG", "WARN", "ERROR"]
    threads = ["worker-0", "worker-1", "worker-2", "worker-3"]

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        for i in range(100):
            entry = json.dumps(
                {
                    "timestamp": f"2024-01-15T10:{i // 60:02d}:{i % 60:02d}Z",
                    "level": levels[i % 4],
                    "message": f"Log message number {i}",
                    "thread_id": threads[i % 4],
                    "correlation_id": f"req-{i % 10}",
                    "service": "test-service",
                    "line_index": i,  # For verification
                }
            )
            f.write(entry + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def deterministic_hierarchy():
    """Hierarchy with known durations for bottleneck testing.

    Structure:
    - root: 1000ms total
      - child-fast: 100ms (10%)
      - child-slow: 800ms (80%) ← THE BOTTLENECK
      - child-medium: 100ms (10%)

    Expected values:
    - total_duration_ms: 1000
    - bottleneck node: "child-slow"
    - bottleneck percentage: 80.0%
    """
    return {
        "roots": [
            {
                "id": "root",
                "node_type": "Span",
                "name": "Root Operation",
                "parent_id": None,
                "children": [
                    {
                        "id": "child-fast",
                        "node_type": "Span",
                        "name": "Fast Child",
                        "parent_id": "root",
                        "children": [],
                        "entry_ids": [1],
                        "start_time": "2024-01-15T10:00:00.000Z",
                        "end_time": "2024-01-15T10:00:00.100Z",
                        "duration_ms": 100,
                        "entry_count": 1,
                        "error_count": 0,
                        "level_counts": {"INFO": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                    {
                        "id": "child-slow",
                        "node_type": "Span",
                        "name": "Slow Database Query",
                        "parent_id": "root",
                        "children": [],
                        "entry_ids": [2, 3],
                        "start_time": "2024-01-15T10:00:00.100Z",
                        "end_time": "2024-01-15T10:00:00.900Z",
                        "duration_ms": 800,
                        "entry_count": 2,
                        "error_count": 0,
                        "level_counts": {"INFO": 2},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                    {
                        "id": "child-medium",
                        "node_type": "Span",
                        "name": "Medium Operation",
                        "parent_id": "root",
                        "children": [],
                        "entry_ids": [4],
                        "start_time": "2024-01-15T10:00:00.900Z",
                        "end_time": "2024-01-15T10:00:01.000Z",
                        "duration_ms": 100,
                        "entry_count": 1,
                        "error_count": 0,
                        "level_counts": {"INFO": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                ],
                "entry_ids": [0],
                "start_time": "2024-01-15T10:00:00.000Z",
                "end_time": "2024-01-15T10:00:01.000Z",
                "duration_ms": 1000,
                "entry_count": 5,
                "error_count": 0,
                "level_counts": {"INFO": 5},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 4,
        "max_depth": 1,
        "total_duration_ms": 1000,
        "concurrent_count": 1,
        "bottleneck": {
            "node_id": "child-slow",
            "duration_ms": 800,
            "percentage": 80.0,
            "depth": 1,
        },
        "error_nodes": [],
        "detection_method": "ExplicitParentId",
    }


@pytest.fixture
def multi_service_deterministic():
    """3 services, each with 30 entries, sharing correlation IDs.

    Structure:
    - api-gateway: entries 0-29, correlation req-{i % 5}
    - auth-service: entries 0-29, correlation req-{i % 5}
    - db-service: entries 0-29, correlation req-{i % 5}

    For correlation req-0:
    - api-gateway: entries 0, 5, 10, 15, 20, 25 = 6 entries
    - auth-service: entries 0, 5, 10, 15, 20, 25 = 6 entries
    - db-service: entries 0, 5, 10, 15, 20, 25 = 6 entries
    - Total for req-0: 18 entries

    Expected counts per correlation (req-0 through req-4):
    - Each correlation: 6 entries per service × 3 services = 18 total
    """
    services = ["api-gateway", "auth-service", "db-service"]
    files = {}

    for service in services:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            for i in range(30):
                entry = json.dumps(
                    {
                        "timestamp": f"2024-01-15T10:00:{i:02d}Z",
                        "level": "INFO" if i % 5 != 0 else "ERROR",
                        "message": f"{service} processing request {i}",
                        "correlation_id": f"req-{i % 5}",
                        "trace_id": "trace-main",
                        "service": service,
                        "thread_id": f"{service}-thread-{i % 3}",
                    }
                )
                f.write(entry + "\n")
            files[service] = [f.name]

    yield files

    for service_files in files.values():
        for path in service_files:
            Path(path).unlink()


@pytest.fixture
def hierarchy_with_names():
    """Hierarchy specifically for testing name extraction.

    Tests the priority order:
    1. operation_name (highest priority)
    2. name field
    3. message field
    4. service fallback
    5. "unknown" (lowest priority)
    """
    return {
        "roots": [
            {
                "id": "node-with-operation-name",
                "node_type": "Span",
                "name": "HTTP POST /checkout",  # This should be used
                "operation_name": "HTTP POST /checkout",
                "parent_id": None,
                "children": [
                    {
                        "id": "node-with-name-only",
                        "node_type": "Span",
                        "name": "Database Query",
                        "parent_id": "node-with-operation-name",
                        "children": [],
                        "entry_ids": [1],
                        "start_time": "2024-01-15T10:00:00.100Z",
                        "end_time": "2024-01-15T10:00:00.200Z",
                        "duration_ms": 100,
                        "entry_count": 1,
                        "error_count": 0,
                        "level_counts": {"INFO": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                    {
                        "id": "node-fallback-to-id",
                        "node_type": "Span",
                        # No name field - should fall back to id
                        "parent_id": "node-with-operation-name",
                        "children": [],
                        "entry_ids": [2],
                        "start_time": "2024-01-15T10:00:00.200Z",
                        "end_time": "2024-01-15T10:00:00.300Z",
                        "duration_ms": 100,
                        "entry_count": 1,
                        "error_count": 0,
                        "level_counts": {"INFO": 1},
                        "depth": 1,
                        "confidence": 1.0,
                        "relationship_evidence": [],
                    },
                ],
                "entry_ids": [0],
                "start_time": "2024-01-15T10:00:00.000Z",
                "end_time": "2024-01-15T10:00:00.500Z",
                "duration_ms": 500,
                "entry_count": 3,
                "error_count": 0,
                "level_counts": {"INFO": 3},
                "depth": 0,
                "confidence": 1.0,
                "relationship_evidence": [],
            }
        ],
        "total_nodes": 3,
        "max_depth": 1,
        "total_duration_ms": 500,
        "concurrent_count": 1,
        "bottleneck": None,
        "error_nodes": [],
        "detection_method": "ExplicitParentId",
    }


# Exit codes of `logler llm` (should match llm_cli.py)
EXIT_SUCCESS = 0
EXIT_NO_RESULTS = 1
EXIT_USER_ERROR = 2


def run_llm_command(args, timeout=60):
    """Run a logler llm command and return result."""
    cmd = [PYTHON, "-m", "logler.cli", "llm", *args]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=str(Path(__file__).parent.parent)
    )
    return result


@pytest.fixture
def sample_log_file():
    """Create a sample log file for testing."""
    content = """2024-01-15T10:00:00.000Z INFO [worker-1] correlation_id=req-abc123 Starting request processing
2024-01-15T10:00:00.050Z DEBUG [worker-1] correlation_id=req-abc123 Validating user token
2024-01-15T10:00:00.100Z INFO [worker-1] correlation_id=req-abc123 User validated successfully
2024-01-15T10:00:00.150Z INFO [worker-1] correlation_id=req-abc123 Querying database
2024-01-15T10:00:00.500Z WARN [worker-1] correlation_id=req-abc123 Query took 350ms
2024-01-15T10:00:01.000Z ERROR [worker-1] correlation_id=req-abc123 Database timeout after 500ms
2024-01-15T10:00:01.100Z INFO [worker-1] correlation_id=req-abc123 Retrying database query
2024-01-15T10:00:01.600Z ERROR [worker-1] correlation_id=req-abc123 Retry failed: connection pool exhausted
2024-01-15T10:00:01.700Z INFO [worker-1] correlation_id=req-abc123 Returning error response to client
2024-01-15T10:00:02.000Z INFO [worker-2] correlation_id=req-def456 Starting new request
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(content)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def json_log_file():
    """Create a JSON log file for testing."""
    entries = [
        {
            "timestamp": "2024-01-15T10:00:00Z",
            "level": "INFO",
            "message": "Starting",
            "thread_id": "main",
        },
        {
            "timestamp": "2024-01-15T10:00:01Z",
            "level": "ERROR",
            "message": "Database timeout",
            "thread_id": "worker-1",
        },
        {
            "timestamp": "2024-01-15T10:00:02Z",
            "level": "INFO",
            "message": "Recovered",
            "thread_id": "worker-1",
        },
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def filtering_cli_log():
    """Create a log file with known counts for CLI filter testing.

    80 entries: 4 levels × 2 services × 10 per combination.
    - Levels: INFO (20), DEBUG (20), WARN (20), ERROR (20)
    - Services: svc-x (40), svc-y (40)
    - Threads: t-0, t-1 (40 each)
    """
    entries = []
    idx = 0
    for svc in ["svc-x", "svc-y"]:
        for level in ["INFO", "DEBUG", "WARN", "ERROR"]:
            for j in range(10):
                entries.append(
                    json.dumps(
                        {
                            "timestamp": f"2024-01-15T10:{idx // 60:02d}:{idx % 60:02d}Z",
                            "level": level,
                            "message": "health ping" if j == 0 else f"operation {idx}",
                            "thread_id": f"t-{idx % 2}",
                            "service_name": svc,
                            "correlation_id": f"req-{idx % 5}",
                        }
                    )
                )
                idx += 1
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("\n".join(entries) + "\n")
        f.flush()
        yield f.name
    os.unlink(f.name)


def invoke(args):
    """Run an llm command in process: its exit code, stdout and stderr."""
    from click.testing import CliRunner

    from logler.llm_cli import llm

    result = CliRunner().invoke(llm, args)
    return result.exit_code, result.stdout, result.stderr


@pytest.fixture
def three_hour_log(tmp_path):
    """Three ERROR lines at 08:00, 10:00 and 12:00 on 2024-01-15 (lines 1, 2, 3)."""
    path = tmp_path / "app.log"
    path.write_text(
        "2024-01-15 08:00:00 ERROR early\n"
        "2024-01-15 10:00:00 ERROR middle\n"
        "2024-01-15 12:00:00 ERROR late\n"
    )
    return str(path)
