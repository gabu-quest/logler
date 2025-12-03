from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    import httpx  # noqa: F401
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency guard
    pytest.skip(f"fastapi TestClient deps missing: {exc}", allow_module_level=True)
else:
    from src.logler.web.app import app


HUGE_LOG = Path("examples/logs/huge/massive_incident.log")
GLOB_LOGS = [
    Path("examples/logs/2025-11-01.log"),
    Path("examples/logs/2025-11-02.log"),
    Path("examples/logs/2025-11-03.log"),
]
MICRO_TRACE = Path("examples/logs/microservices_trace.log")


client = TestClient(app)


def test_open_api_returns_service_names_and_totals():
    resp = client.post("/api/files/open", json={"path": str(HUGE_LOG)})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total"] == 10000
    assert len(data["entries"]) == 1000  # capped slice
    assert any(entry.get("service_name") for entry in data["entries"])
    assert any(entry.get("level") == "ERROR" for entry in data["entries"])


def test_open_many_interleaves_and_preserves_service_names():
    resp = client.post("/api/files/open_many", json={"paths": [str(p) for p in GLOB_LOGS]})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total"] == 597  # 199 lines per file across 3 files
    assert len(data["entries"]) == data["total"]
    assert set(data["files"]) == {str(p.resolve()) for p in GLOB_LOGS}

    # Ensure last entries correspond to expected last lines and keep service_name
    last_by_file = {}
    for entry in data["entries"]:
        last_by_file[entry["file"]] = entry
    assert last_by_file[str(GLOB_LOGS[0].resolve())]["message"].endswith("day 1")
    assert last_by_file[str(GLOB_LOGS[1].resolve())]["service_name"] == "worker"
    assert last_by_file[str(GLOB_LOGS[2].resolve())]["service_name"] == "api"


def test_cross_service_timeline_rust_path(investigate_module):
    inv = investigate_module
    timeline = inv.cross_service_timeline(
        files={"stack": [str(MICRO_TRACE)]},
        correlation_id="req-abc123",
        trace_id="trace-001",
    )

    assert timeline["total_entries"] > 0
    assert timeline["services"] == ["stack"]
    assert timeline["duration_ms"] is not None and timeline["duration_ms"] > 0
    assert any(entry["entry"].get("service_name") for entry in timeline["timeline"])

    relative_times = [entry["relative_time_ms"] for entry in timeline["timeline"] if entry["relative_time_ms"] is not None]
    assert relative_times == sorted(relative_times)

    # First failure in the microservices trace is inventory-service timeout
    failure_messages = [entry for entry in timeline["timeline"] if entry["entry"].get("level") in ("ERROR", "FATAL")]
    assert failure_messages, "no failure entries found in timeline"
    first_failure = failure_messages[0]["entry"]
    assert "timeout" in first_failure["message"].lower()
