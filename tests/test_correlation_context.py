"""Tests for logler.context — correlation context, filter, and JSON handler."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_exception_resets_context(self):
        """correlation_id is reset even if exception occurs inside context."""
        with pytest.raises(RuntimeError):
            with correlation_context("will-fail"):
                assert get_correlation_id() == "will-fail"
                raise RuntimeError("boom")
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


# ---------------------------------------------------------------------------
# IMP-2: JsonHandler robustness (consecutive error tracking)
# ---------------------------------------------------------------------------


class TestJsonHandlerRobustness:
    def _make_record(self, msg: str = "test") -> logging.LogRecord:
        return logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None,
        )

    def test_emit_resets_consecutive_errors(self):
        buf = io.StringIO()
        handler = JsonHandler(stream=buf)
        handler.emit(self._make_record())
        assert handler._consecutive_errors == 0
        assert handler.degraded is False

    def test_emit_tracks_consecutive_errors(self):
        """Broken stream increments error counter and sets degraded."""
        buf = MagicMock()
        buf.write = MagicMock(side_effect=OSError("disk full"))
        handler = JsonHandler(stream=buf)

        for _ in range(5):
            handler.emit(self._make_record())

        assert handler._consecutive_errors == 5
        assert handler.degraded is True

    def test_emit_stops_calling_handle_error_after_3(self):
        """handleError is called at most 3 times, then suppressed."""
        buf = MagicMock()
        buf.write = MagicMock(side_effect=OSError("broken pipe"))
        handler = JsonHandler(stream=buf)
        handler.handleError = MagicMock()

        for _ in range(5):
            handler.emit(self._make_record())

        assert handler.handleError.call_count == 3

    def test_degraded_resets_on_success(self):
        """Successful emit after failures resets degraded state."""
        buf = io.StringIO()
        handler = JsonHandler(stream=buf)

        # Force a failure
        handler._consecutive_errors = 2
        assert handler.degraded is True

        # Successful emit resets
        handler.emit(self._make_record())
        assert handler._consecutive_errors == 0
        assert handler.degraded is False

    def test_flush_failure_increments_errors(self):
        """flush() failure also triggers error tracking."""
        buf = MagicMock()
        buf.write = MagicMock(return_value=None)
        buf.flush = MagicMock(side_effect=BrokenPipeError("broken pipe"))
        handler = JsonHandler(stream=buf)
        handler.handleError = MagicMock()

        handler.emit(self._make_record())
        assert handler._consecutive_errors == 1
        assert handler.degraded is True
        assert handler.handleError.call_count == 1


# ---------------------------------------------------------------------------
# IMP-4: OTel bridge for correlation_context
# ---------------------------------------------------------------------------


class TestCorrelationFilterPreserveExplicit:
    """CorrelationFilter must not overwrite explicitly-set correlation_id."""

    def test_filter_preserves_explicit_correlation_id(self):
        filt = CorrelationFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.correlation_id = "explicit-id"  # type: ignore[attr-defined]
        with correlation_context("contextvar-id"):
            filt.filter(record)
        assert record.correlation_id == "explicit-id"  # type: ignore[attr-defined]

    def test_filter_fills_when_not_set(self):
        filt = CorrelationFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        with correlation_context("contextvar-id"):
            filt.filter(record)
        assert record.correlation_id == "contextvar-id"  # type: ignore[attr-defined]


class TestJsonHandlerExtraFields:
    """JsonHandler must forward extra fields to JSON output."""

    def _make_handler_and_logger(self, stream: io.StringIO) -> logging.Logger:
        handler = JsonHandler(stream=stream)
        handler.addFilter(CorrelationFilter())
        logger = logging.getLogger(f"test.extra.{id(stream)}")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        return logger

    def test_extra_fields_forwarded(self):
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        logger.info("lifecycle", extra={"event": "job.enqueued", "job_id": "abc123", "queue": "default"})

        entry = json.loads(buf.getvalue().strip())
        assert entry["event"] == "job.enqueued"
        assert entry["job_id"] == "abc123"
        assert entry["queue"] == "default"

    def test_non_serializable_extra_skipped(self):
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        logger.info("lifecycle", extra={"good": "value", "bad": object()})

        entry = json.loads(buf.getvalue().strip())
        assert entry["good"] == "value"
        assert "bad" not in entry

    def test_standard_attrs_not_duplicated(self):
        """Standard LogRecord attrs should not leak into JSON output."""
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        logger.info("test")

        entry = json.loads(buf.getvalue().strip())
        # These standard attrs should NOT be in the output
        assert "msg" not in entry
        assert "args" not in entry
        assert "lineno" not in entry
        assert "pathname" not in entry

    def test_extra_with_correlation_id(self):
        """Extra correlation_id should take precedence over ContextVar."""
        buf = io.StringIO()
        logger = self._make_handler_and_logger(buf)
        logger.info("lifecycle", extra={"correlation_id": "explicit", "event": "job.completed"})

        entry = json.loads(buf.getvalue().strip())
        assert entry["correlation_id"] == "explicit"
        assert entry["event"] == "job.completed"


class TestOtelBridge:
    def test_otel_bridge_false_default(self):
        """Default behavior unchanged — no OTel imports."""
        with correlation_context("job-123") as cid:
            assert cid == "job-123"
            assert get_correlation_id() == "job-123"
        assert get_correlation_id() is None

    def test_otel_bridge_without_otel_installed(self):
        """otel_bridge=True gracefully handles missing opentelemetry."""
        with patch.dict("sys.modules", {"opentelemetry": None}):
            with correlation_context("job-456", otel_bridge=True) as cid:
                assert cid == "job-456"
                assert get_correlation_id() == "job-456"
        assert get_correlation_id() is None

    def test_otel_bridge_with_mock_otel(self):
        """When opentelemetry is available, baggage is set and detached."""
        mock_baggage = MagicMock()
        mock_context = MagicMock()
        mock_ctx = MagicMock()
        mock_token = MagicMock()

        mock_baggage.set_baggage = MagicMock(return_value=mock_ctx)
        mock_context.attach = MagicMock(return_value=mock_token)

        # The production code does `from opentelemetry import baggage, context`
        # lazily inside the if-block, so patching sys.modules is sufficient.
        with patch.dict("sys.modules", {
            "opentelemetry": MagicMock(baggage=mock_baggage, context=mock_context),
            "opentelemetry.baggage": mock_baggage,
            "opentelemetry.context": mock_context,
        }):
            with correlation_context("job-789", otel_bridge=True) as cid:
                assert cid == "job-789"
                mock_baggage.set_baggage.assert_called_once_with(
                    "correlation_id", "job-789"
                )
                mock_context.attach.assert_called_once_with(mock_ctx)

            mock_context.detach.assert_called_once_with(mock_token)

    def test_otel_bridge_detaches_on_exception(self):
        """OTel context.detach() is called even when body raises."""
        mock_baggage = MagicMock()
        mock_context = MagicMock()
        mock_ctx = MagicMock()
        mock_token = MagicMock()

        mock_baggage.set_baggage = MagicMock(return_value=mock_ctx)
        mock_context.attach = MagicMock(return_value=mock_token)

        with patch.dict("sys.modules", {
            "opentelemetry": MagicMock(baggage=mock_baggage, context=mock_context),
            "opentelemetry.baggage": mock_baggage,
            "opentelemetry.context": mock_context,
        }):
            with pytest.raises(RuntimeError, match="boom"):
                with correlation_context("job-explode", otel_bridge=True):
                    raise RuntimeError("boom")

            # detach must still be called despite the exception
            mock_context.detach.assert_called_once_with(mock_token)
        # correlation_id must also be reset
        assert get_correlation_id() is None
