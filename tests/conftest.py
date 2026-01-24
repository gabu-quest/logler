"""Test configuration for Logler.

Ensures the local `src` layout is importable without requiring an editable
install when running `pytest` from the repository root.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))


@dataclass
class RustBackendStatus:
    ready: bool
    skip_reason: str | None = None
    error: str | None = None


def _attempt_import_logler_rs() -> tuple[bool, Exception | None]:
    try:
        import logler_rs  # noqa: F401

        return True, None
    except Exception as exc:  # pragma: no cover - only hit when Rust missing
        return False, exc


def _ensure_rust_backend() -> RustBackendStatus:
    imported, import_err = _attempt_import_logler_rs()
    if imported:
        return RustBackendStatus(ready=True)

    maturin = shutil.which("maturin")
    cargo = shutil.which("cargo")
    missing = [name for name, path in (("maturin", maturin), ("cargo", cargo)) if not path]
    if missing:
        reason = f"Rust toolchain missing ({', '.join(missing)}); cannot build logler_rs"
        return RustBackendStatus(ready=False, skip_reason=reason, error=str(import_err))

    cmd = [
        maturin,
        "develop",
        "--release",
        "-m",
        str(ROOT / "crates" / "logler-py" / "Cargo.toml"),
        "--features",
        "sql",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return RustBackendStatus(
            ready=False,
            error=f"maturin develop failed ({proc.returncode}): {(proc.stderr or proc.stdout).strip()}",
        )

    imported, post_build_err = _attempt_import_logler_rs()
    if imported:
        return RustBackendStatus(ready=True)

    return RustBackendStatus(
        ready=False,
        error=f"logler_rs import failed after build: {post_build_err}",
    )


RUST_BACKEND_STATUS = _ensure_rust_backend()
RUST_READY = RUST_BACKEND_STATUS.ready


@pytest.fixture(scope="session")
def rust_backend():
    status = RUST_BACKEND_STATUS
    if status.skip_reason:
        pytest.skip(status.skip_reason)
    if not status.ready:
        pytest.fail(status.error or "Rust backend missing even though maturin is available")

    import logler_rs

    return logler_rs


@pytest.fixture(scope="session")
def investigate_module(rust_backend):
    import logler.investigate as investigate

    investigate = importlib.reload(investigate)
    assert getattr(
        investigate, "RUST_AVAILABLE", False
    ), "logler.investigate reports RUST_AVAILABLE=False"
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
