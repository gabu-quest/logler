"""Correlation context for structured logging integration.

Provides ContextVar-based correlation ID tracking that works with
asyncio, threading, and Python's stdlib logging. Emits JSON structured
logs that logler can parse natively.

Example::

    import logging
    from logler.context import correlation_context, CorrelationFilter, JsonHandler

    handler = JsonHandler(filename="app.log")
    handler.addFilter(CorrelationFilter())
    logging.root.addHandler(handler)

    with correlation_context("job-123"):
        logging.info("Processing started")
        # -> {"timestamp": "...", "correlation_id": "job-123", ...}
"""

from __future__ import annotations

import json
import logging
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

_correlation_id: ContextVar[Optional[str]] = ContextVar("_correlation_id", default=None)


@contextmanager
def correlation_context(correlation_id: str, otel_bridge: bool = False):
    """Set correlation_id for the duration of the context.

    Works correctly with asyncio (each task gets its own copy) and
    with nested contexts (inner overrides outer, restores on exit).

    Args:
        correlation_id: The correlation ID to set.
        otel_bridge: If True, also propagate correlation_id as
            OpenTelemetry baggage. Requires ``opentelemetry-api``
            (install with ``logler[otel]``). Silently ignored if
            the package is not installed.

    Yields:
        The correlation_id that was set.

    Example::

        with correlation_context("job-123"):
            logging.info("inside context")
            # get_correlation_id() returns "job-123"
        # get_correlation_id() returns None (or previous value)
    """
    token = _correlation_id.set(correlation_id)
    otel_token = None
    try:
        if otel_bridge:
            try:
                from opentelemetry import baggage, context  # type: ignore[import-untyped]

                ctx = baggage.set_baggage("correlation_id", correlation_id)
                otel_token = context.attach(ctx)
            except Exception:
                pass
        yield correlation_id
    finally:
        if otel_bridge and otel_token is not None:
            from opentelemetry import context  # type: ignore[import-untyped]

            context.detach(otel_token)
        _correlation_id.reset(token)


def get_correlation_id() -> Optional[str]:
    """Return the current correlation ID, or None if not set."""
    return _correlation_id.get()


class CorrelationFilter(logging.Filter):
    """Injects correlation_id from ContextVar into log records.

    Attach to any handler or logger to automatically add ``correlation_id``
    to every log record. Works with both JsonHandler and stdlib formatters.

    Example::

        handler = logging.StreamHandler()
        handler.addFilter(CorrelationFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()  # type: ignore[attr-defined]
        return True


class JsonHandler(logging.Handler):
    """Emits JSON structured logs that logler can parse.

    One JSON object per line with fields: timestamp, level, message,
    thread_id, logger, file, function, and optional correlation_id,
    trace_id, exception.

    Args:
        filename: Path to write log file. Mutually exclusive with stream.
        stream: Stream to write to. Mutually exclusive with filename.

    Example::

        handler = JsonHandler(filename="app.log")
        handler.addFilter(CorrelationFilter())
        logging.root.addHandler(handler)
        logging.root.setLevel(logging.DEBUG)
    """

    def __init__(
        self,
        filename: Optional[str] = None,
        stream=None,
        level: int = logging.NOTSET,
    ):
        super().__init__(level)
        if filename and stream:
            raise ValueError("Cannot specify both filename and stream")
        if filename:
            self._stream = open(filename, "a", encoding="utf-8")
            self._owns_stream = True
        elif stream:
            self._stream = stream
            self._owns_stream = False
        else:
            raise ValueError("Must specify either filename or stream")
        self._consecutive_errors = 0

    @property
    def degraded(self) -> bool:
        """True if the handler has experienced write errors."""
        return self._consecutive_errors > 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "thread_id": record.threadName,
                "logger": record.name,
                "file": f"{record.filename}:{record.lineno}",
                "function": record.funcName,
            }

            # Optional fields — only include when present
            correlation_id = getattr(record, "correlation_id", None)
            if correlation_id is not None:
                entry["correlation_id"] = correlation_id

            trace_id = getattr(record, "trace_id", None)
            if trace_id is not None:
                entry["trace_id"] = trace_id

            # Exception info
            if record.exc_info and record.exc_info[0] is not None:
                entry["exception"] = {
                    "type": record.exc_info[0].__name__,
                    "value": str(record.exc_info[1]),
                    "traceback": traceback.format_exception(*record.exc_info),
                }

            self._stream.write(json.dumps(entry) + "\n")
            self._stream.flush()
            self._consecutive_errors = 0
        except Exception:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                self.handleError(record)

    def close(self) -> None:
        if self._owns_stream:
            self._stream.close()
        super().close()

    def __del__(self) -> None:
        """Safety net: close file if handler is garbage collected."""
        try:
            if getattr(self, "_owns_stream", False) and getattr(self, "_stream", None):
                self._stream.close()
        except Exception:
            pass
