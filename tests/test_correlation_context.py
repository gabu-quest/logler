"""Tests for logler.context — correlation context, filter, and JSON handler."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from pathlib import Path

import pytest

from logler.context import (
    CorrelationFilter,
    JsonHandler,
    correlation_context,
    get_correlation_id,
)


# ---------------------------------------------------------------------------
# correlation_context / get_correlation_id
# ---------------------------------------------------------------------------


class TestCorrelationContext:
    def test_basic_context(self):
        assert get_correlation_id() is None
        with correlation_context("job-123") as cid:
            assert cid == "job-123"
            assert get_correlation_id() == "job-123"
        assert get_correlation_id() is None

    def test_nested_context(self):
        with correlation_context("outer"):
            assert get_correlation_id() == "outer"
            with correlation_context("inner"):
                assert get_correlation_id() == "inner"
            assert get_correlation_id() == "outer"
        assert get_correlation_id() is None

    def test_default_none(self):
        assert get_correlation_id() is None


# ---------------------------------------------------------------------------
# CorrelationFilter
# ---------------------------------------------------------------------------


class TestCorrelationFilter:
    def test_filter_injects_id(self):
        filt = CorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        with correlation_context("req-abc"):
            filt.filter(record)
        assert record.correlation_id == "req-abc"  # type: ignore[attr-defined]

    def test_filter_no_context(self):
        filt = CorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert record.correlation_id is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# JsonHandler
# ---------------------------------------------------------------------------


class TestJsonHandler:
    def _make_handler_and_logger(self, stream: io.StringIO) -> logging.Logger:
        handler = JsonHandler(stream=stream)
        handler.addFilter(CorrelationFilter())
        logger = logging.getLogger(f"test.json.{id(stream)}")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        return logger

    def test_json_handler_format(self):
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        logger.info("hello world")

        line = buf.getvalue().strip()
        entry = json.loads(line)
        assert entry["level"] == "INFO"
        assert entry["message"] == "hello world"
        assert "timestamp" in entry
        assert "thread_id" in entry
        assert "logger" in entry
        assert "file" in entry
        assert "function" in entry

    def test_json_handler_with_correlation(self):
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        with correlation_context("corr-456"):
            logger.info("tracked")

        entry = json.loads(buf.getvalue().strip())
        assert entry["correlation_id"] == "corr-456"

    def test_json_handler_without_correlation(self):
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        logger.info("untracked")

        entry = json.loads(buf.getvalue().strip())
        assert "correlation_id" not in entry

    def test_json_handler_exception(self):
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("caught error")

        entry = json.loads(buf.getvalue().strip())
        assert entry["exception"]["type"] == "ValueError"
        assert entry["exception"]["value"] == "boom"
        assert isinstance(entry["exception"]["traceback"], list)

    def test_json_handler_to_file(self, tmp_path: Path):
        log_file = str(tmp_path / "test.log")
        handler = JsonHandler(filename=log_file)
        handler.addFilter(CorrelationFilter())

        logger = logging.getLogger("test.file_handler")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        with correlation_context("file-test"):
            logger.warning("written to file")

        handler.close()

        with open(log_file) as f:
            entry = json.loads(f.readline())
        assert entry["correlation_id"] == "file-test"
        assert entry["level"] == "WARNING"

    def test_json_handler_requires_target(self):
        with pytest.raises(ValueError, match="Must specify"):
            JsonHandler()

    def test_json_handler_exclusive_target(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            JsonHandler(filename="x.log", stream=io.StringIO())


# ---------------------------------------------------------------------------
# Full roundtrip: write with context -> parse with logler -> search
# ---------------------------------------------------------------------------


class TestFullRoundtrip:
    def test_full_roundtrip(self, tmp_path: Path):
        """Write JSON logs with correlation context, then search them with logler."""
        log_file = str(tmp_path / "roundtrip.log")
        handler = JsonHandler(filename=log_file)
        handler.addFilter(CorrelationFilter())

        logger = logging.getLogger("test.roundtrip")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Write logs with different correlation IDs
        with correlation_context("job-001"):
            logger.info("Job started")
            logger.warning("Slow query detected")

        with correlation_context("job-002"):
            logger.info("Job started")
            logger.error("Connection refused")

        logger.info("No correlation")
        handler.close()

        # Parse with logler's Rust backend
        from logler.investigate import Investigator

        inv = Investigator()
        inv.load_files([log_file])

        # Search by correlation ID
        results = inv.search(correlation_id="job-001")
        entries = results.get("results", [])
        assert len(entries) == 2
        for item in entries:
            assert item["entry"].get("correlation_id") == "job-001"

        # Search by level
        results = inv.search(level="ERROR")
        entries = results.get("results", [])
        assert len(entries) >= 1
        assert any("Connection refused" in e["entry"].get("message", "") for e in entries)


# ---------------------------------------------------------------------------
# Async isolation
# ---------------------------------------------------------------------------


class TestAsyncIsolation:
    def test_async_isolation(self):
        """Two asyncio tasks don't interfere with each other's correlation ID."""
        results: dict[str, list[str | None]] = {"task_a": [], "task_b": []}

        async def task_a():
            with correlation_context("aaa"):
                results["task_a"].append(get_correlation_id())
                await asyncio.sleep(0.01)
                results["task_a"].append(get_correlation_id())

        async def task_b():
            with correlation_context("bbb"):
                results["task_b"].append(get_correlation_id())
                await asyncio.sleep(0.01)
                results["task_b"].append(get_correlation_id())

        async def main():
            await asyncio.gather(task_a(), task_b())

        asyncio.run(main())

        assert results["task_a"] == ["aaa", "aaa"]
        assert results["task_b"] == ["bbb", "bbb"]
