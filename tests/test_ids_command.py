"""
Tests for the ids extraction feature.

Uses a deterministic fixture with known ID counts:
- 100 entries
- 4 threads: worker-0..3 (25 each)
- 10 correlations: corr-0..9 (10 each)
- 2 services: svc-a (entries 0-49), svc-b (entries 50-99)
- Timestamps span 2024-01-15T10:00:00Z to 2024-01-15T10:01:39Z
"""

import json
import tempfile
import pytest
from pathlib import Path

try:
    from logler.investigate import extract_ids, RUST_AVAILABLE
except ImportError:
    RUST_AVAILABLE = False

pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required")


@pytest.fixture
def ids_log_file():
    """100 entries with known thread/correlation/service counts."""
    levels = ["INFO", "DEBUG", "WARN", "ERROR"]
    threads = ["worker-0", "worker-1", "worker-2", "worker-3"]

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        for i in range(100):
            mm = i // 60
            ss = i % 60
            entry = json.dumps(
                {
                    "timestamp": f"2024-01-15T10:{mm:02d}:{ss:02d}Z",
                    "level": levels[i % 4],
                    "message": f"Task {i}",
                    "thread_id": threads[i % 4],
                    "correlation_id": f"corr-{i % 10}",
                    "service_name": "svc-a" if i < 50 else "svc-b",
                }
            )
            f.write(entry + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


class TestIdsExtraction:
    """Test extract_ids returns correct counts."""

    def test_ids_counts(self, ids_log_file):
        result = extract_ids(files=[ids_log_file])
        assert result["total_entries"] == 100

        # 4 unique thread IDs
        thread_ids = {t["id"]: t["count"] for t in result["thread_ids"]}
        assert len(thread_ids) == 4
        for tid in ["worker-0", "worker-1", "worker-2", "worker-3"]:
            assert thread_ids[tid] == 25

        # 10 unique correlation IDs
        corr_ids = {c["id"]: c["count"] for c in result["correlation_ids"]}
        assert len(corr_ids) == 10
        for j in range(10):
            assert corr_ids[f"corr-{j}"] == 10

        # 2 services
        services = {s["id"]: s["count"] for s in result["services"]}
        assert len(services) == 2
        assert services["svc-a"] == 50
        assert services["svc-b"] == 50

    def test_ids_first_last_seen(self, ids_log_file):
        result = extract_ids(files=[ids_log_file])

        # worker-0 appears at entries 0, 4, 8, ..., 96
        # First seen = entry 0 = 10:00:00, last seen = entry 96 = 10:01:36
        worker0 = next(t for t in result["thread_ids"] if t["id"] == "worker-0")
        assert worker0["first_seen"] is not None
        assert worker0["last_seen"] is not None
        assert worker0["first_seen"] < worker0["last_seen"]

    def test_ids_with_time_filter(self, ids_log_file):
        # Only entries from first 30 seconds (entries 0-29)
        result = extract_ids(
            files=[ids_log_file],
            time_start="2024-01-15T10:00:00Z",
            time_end="2024-01-15T10:00:29Z",
        )
        # Entries 0-29: all in svc-a, all 4 threads, corr-0 through corr-9
        assert result["total_entries"] == 30

        thread_ids = {t["id"]: t["count"] for t in result["thread_ids"]}
        # 30 entries / 4 threads: workers 0-1 get 8 each (0,4,8,12,16,20,24,28 for w-0)
        # Actually: entries 0-29, i%4 pattern: w-0 at 0,4,8,12,16,20,24,28 = 8
        # w-1 at 1,5,9,13,17,21,25,29 = 8, w-2 at 2,6,10,14,18,22,26 = 7, w-3 at 3,7,11,15,19,23,27 = 7
        assert thread_ids["worker-0"] == 8
        assert thread_ids["worker-1"] == 8
        assert thread_ids["worker-2"] == 7
        assert thread_ids["worker-3"] == 7

        # All entries < 50, so only svc-a
        services = {s["id"]: s["count"] for s in result["services"]}
        assert len(services) == 1
        assert services["svc-a"] == 30


class TestIdsCLI:
    """Test ids command via CLI subprocess."""

    def test_ids_json_output(self, ids_log_file):
        import subprocess

        result = subprocess.run(
            ["python", "-m", "logler.cli", "llm", "ids", ids_log_file],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_entries"] == 100
        assert len(data["thread_ids"]) == 4
        assert len(data["correlation_ids"]) == 10
        assert len(data["services"]) == 2
