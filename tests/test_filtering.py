"""
Tests for filtering capabilities: multi-level, exclude-level, exclude-query,
tail, service filter, multi-value IDs, field projection, max-bytes.

Fixture: filtering_log_file
- 200 entries total
- 4 levels: INFO (50), DEBUG (50), WARN (50), ERROR (50)
- 2 services: svc-alpha (100), svc-beta (100)
- 4 threads: worker-0 through worker-3 (50 each)
- 10 correlations: corr-0 through corr-9 (20 each)
- Messages include "health" for entries divisible by 10 (20 entries total)

Entry i:
  level    = [INFO, DEBUG, WARN, ERROR][i % 4]
  thread   = worker-{i % 4}
  service  = svc-alpha if i < 100 else svc-beta
  corr     = corr-{i % 10}
  message  = "health check ok" if i % 10 == 0 else "Processing task {i}"
  timestamp = 2024-01-15T10:{mm}:{ss}Z  (incrementing)
"""

import json
import tempfile
import pytest
from pathlib import Path

try:
    from logler.investigate import search, RUST_AVAILABLE
except ImportError:
    RUST_AVAILABLE = False

pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust backend required")


@pytest.fixture
def filtering_log_file():
    """200 entries across 2 services, 4 levels, 4 threads, 10 correlations."""
    levels = ["INFO", "DEBUG", "WARN", "ERROR"]
    threads = ["worker-0", "worker-1", "worker-2", "worker-3"]

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        for i in range(200):
            mm = i // 60
            ss = i % 60
            msg = "health check ok" if i % 10 == 0 else f"Processing task {i}"
            entry = json.dumps(
                {
                    "timestamp": f"2024-01-15T10:{mm:02d}:{ss:02d}Z",
                    "level": levels[i % 4],
                    "message": msg,
                    "thread_id": threads[i % 4],
                    "correlation_id": f"corr-{i % 10}",
                    "service_name": "svc-alpha" if i < 100 else "svc-beta",
                }
            )
            f.write(entry + "\n")
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink()


class TestMultiLevelFilter:
    """Multi-level comma-separated filtering."""

    @pytest.mark.parametrize(
        "levels,expected",
        [
            ("ERROR,WARN", 100),
            ("INFO", 50),
            ("ERROR,WARN,INFO", 150),
            ("DEBUG", 50),
        ],
        ids=["error_warn_100", "info_50", "three_levels_150", "debug_50"],
    )
    def test_multi_level(self, filtering_log_file, levels, expected):
        result = search(files=[filtering_log_file], level=levels, limit=200)
        assert result["total_matches"] == expected
        assert len(result["results"]) == expected

        allowed = {lvl.strip().upper() for lvl in levels.split(",")}
        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["level"] in allowed


class TestExcludeLevel:
    """Exclude levels from results."""

    @pytest.mark.parametrize(
        "exclude,expected",
        [
            ("DEBUG", 150),
            ("DEBUG,INFO", 100),
            ("ERROR", 150),
        ],
        ids=["no_debug_150", "no_debug_info_100", "no_error_150"],
    )
    def test_exclude(self, filtering_log_file, exclude, expected):
        result = search(files=[filtering_log_file], exclude_level=exclude, limit=200)
        assert result["total_matches"] == expected

        excluded = {lvl.strip().upper() for lvl in exclude.split(",")}
        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["level"] not in excluded


class TestExcludeQuery:
    """Exclude entries matching a regex pattern."""

    def test_exclude_health_checks(self, filtering_log_file):
        # 20 out of 200 entries have "health check ok"
        result_all = search(files=[filtering_log_file], limit=200)
        result_no_health = search(files=[filtering_log_file], exclude_query="health", limit=200)
        assert result_all["total_matches"] == 200
        assert result_no_health["total_matches"] == 180

        for item in result_no_health["results"]:
            entry = item.get("entry", item)
            assert "health" not in entry["message"].lower()


class TestTail:
    """Tail returns last N entries by timestamp."""

    def test_tail_returns_last_n(self, filtering_log_file):
        result = search(files=[filtering_log_file], tail=10)
        assert len(result["results"]) == 10
        assert result["total_matches"] == 200

        # Verify they are the LAST 10 by timestamp value
        timestamps = [item["entry"]["timestamp"] for item in result["results"]]
        assert timestamps == sorted(timestamps)
        # Entries 190-199: mm=3, ss=10..19 → timestamps 10:03:10Z through 10:03:19Z
        assert timestamps[0] == "2024-01-15T10:03:10Z"
        assert timestamps[-1] == "2024-01-15T10:03:19Z"

    def test_tail_with_level_filter(self, filtering_log_file):
        result = search(files=[filtering_log_file], level="ERROR", tail=5)
        assert len(result["results"]) == 5
        assert result["total_matches"] == 50

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["level"] == "ERROR"


class TestServiceFilter:
    """Filter by service name."""

    def test_single_service(self, filtering_log_file):
        result = search(files=[filtering_log_file], service_name="svc-alpha", limit=200)
        assert result["total_matches"] == 100
        assert len(result["results"]) == 100

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry.get("service_name") == "svc-alpha"

    def test_other_service(self, filtering_log_file):
        result = search(files=[filtering_log_file], service_name="svc-beta", limit=200)
        assert result["total_matches"] == 100


class TestMultiValueIds:
    """Multi-value comma-separated thread/correlation/trace IDs."""

    def test_two_threads(self, filtering_log_file):
        result = search(
            files=[filtering_log_file],
            thread_id="worker-0,worker-1",
            limit=200,
        )
        assert result["total_matches"] == 100

        allowed_threads = {"worker-0", "worker-1"}
        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["thread_id"] in allowed_threads

    def test_two_correlations(self, filtering_log_file):
        result = search(
            files=[filtering_log_file],
            correlation_id="corr-0,corr-1",
            limit=200,
        )
        assert result["total_matches"] == 40

        allowed = {"corr-0", "corr-1"}
        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["correlation_id"] in allowed


class TestFieldProjection:
    """Fields parameter limits output keys."""

    def test_fields_limits_output(self, filtering_log_file):
        result = search(
            files=[filtering_log_file],
            level="ERROR",
            limit=5,
            fields=["timestamp", "level", "message"],
        )
        assert len(result["results"]) == 5

        for item in result["results"]:
            entry = item.get("entry", item)
            # Should have EXACTLY the requested fields — no more, no less
            assert set(entry.keys()) == {"timestamp", "level", "message"}


class TestMaxBytes:
    """Max bytes truncation."""

    def test_truncates_when_over_budget(self, filtering_log_file):
        from logler.llm_cli import _apply_max_bytes

        # Create a large result
        data = {
            "results": [{"entry": {"message": f"msg {i}"}} for i in range(100)],
            "total_matches": 100,
        }

        original_size = len(json.dumps(data, default=str).encode("utf-8"))
        assert original_size > 2000

        truncated = _apply_max_bytes(data, 2000)
        assert truncated["truncated"] is True
        assert truncated["original_count"] == 100
        # Must have fewer results but not zero
        assert 0 < truncated["truncated_at"] < 100
        assert len(truncated["results"]) == truncated["truncated_at"]
        # Actually verify the constraint: serialized output fits budget
        truncated_size = len(json.dumps(truncated, default=str).encode("utf-8"))
        assert truncated_size <= 2000

    def test_no_truncation_when_under(self, filtering_log_file):
        from logler.llm_cli import _apply_max_bytes

        data = {
            "results": [{"entry": {"message": "short"}}],
            "total_matches": 1,
        }
        result = _apply_max_bytes(data, 100000)
        # Should return data unchanged — same structure, same content
        assert result["results"] == [{"entry": {"message": "short"}}]
        assert result["total_matches"] == 1
        assert "truncated" not in result


class TestCombinedFilters:
    """Test combining multiple filters."""

    def test_level_and_service(self, filtering_log_file):
        result = search(
            files=[filtering_log_file],
            level="ERROR",
            service_name="svc-alpha",
            limit=200,
        )
        # svc-alpha has entries 0-99, ERROR at indices 3,7,11,...99 = 25 entries
        assert result["total_matches"] == 25

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["level"] == "ERROR"
            assert entry.get("service_name") == "svc-alpha"

    def test_exclude_level_and_tail(self, filtering_log_file):
        result = search(
            files=[filtering_log_file],
            exclude_level="DEBUG,INFO",
            tail=5,
        )
        assert len(result["results"]) == 5
        assert result["total_matches"] == 100  # WARN + ERROR = 100

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["level"] in ("WARN", "ERROR")

    def test_all_filters_combined(self, filtering_log_file):
        """Kitchen-sink: multiple filters compose correctly."""
        result = search(
            files=[filtering_log_file],
            level="ERROR,WARN",
            service_name="svc-alpha",
            thread_id="worker-2,worker-3",
            exclude_query="health",
            tail=5,
            fields=["timestamp", "level", "message", "service_name"],
        )
        # svc-alpha: entries 0-99
        # WARN|ERROR: i%4 in {2,3}, same indices as worker-2|worker-3
        # Within svc-alpha: entries 2,3,6,7,...,98,99 = 50 entries
        # Exclude "health": i%10==0 and i%4 in {2,3} → 10,30,50,70,90 = 5 entries
        # 50 - 5 = 45
        assert result["total_matches"] == 45
        assert len(result["results"]) == 5

        for item in result["results"]:
            entry = item.get("entry", item)
            assert entry["level"] in ("WARN", "ERROR")
            assert set(entry.keys()) == {"timestamp", "level", "message", "service_name"}
            assert "health" not in entry["message"].lower()
