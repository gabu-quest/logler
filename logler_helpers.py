"""
Logler Helper Functions
Optimized configurations for popular logging libraries to work seamlessly with Logler.

Installation:
    pip install logler loguru structlog python-json-logger

Quick Start:
    # Loguru (recommended)
    from loguru import logger
    from logler_helpers import configure_loguru_for_logler

    configure_loguru_for_logler(logger, "app.log")
    logger.info("Hello world", correlation_id="req-123")

    # Then view in Logler:
    # logler serve app.log --open

For full examples, see the bottom of this file.
"""

import sys
import json
import logging
from datetime import datetime


# ==================== LOGURU ====================


def configure_loguru_for_logler(logger, log_file: str = "app.log", console_level: str = "INFO"):
    """
    Configure Loguru to output logs in Logler's preferred JSON format.

    Preferred Format Features:
    - JSON for structured parsing
    - Thread tracking with thread_id
    - Correlation ID support (pass in extra context)
    - Timestamp in ISO 8601 format
    - All metadata in standard fields

    Args:
        logger: Loguru logger instance
        log_file: Path to log file (default: "app.log")
        console_level: Console output level (default: "INFO")

    Usage:
        from loguru import logger
        from logler_helpers import configure_loguru_for_logler

        configure_loguru_for_logler(logger, "myapp.log")
        logger.info("Hello world", correlation_id="req-123")

        # View in Logler:
        # logler serve myapp.log --open
    """
    # Remove default handler
    logger.remove()

    # Add Logler-optimized JSON handler
    logger.add(
        log_file,
        format="{message}",  # Raw message only, we'll structure it in serialize
        level="TRACE",
        serialize=True,  # JSON output - Logler's preferred format
        backtrace=True,
        diagnose=True,
        enqueue=True,  # Thread-safe
        rotation="500 MB",
        retention="10 days",
        compression="zip",
    )

    # Add console handler (plain text for humans)
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{thread.name}</cyan> | "
        "<level>{message}</level>",
        level=console_level,
        colorize=True,
    )

    return logger


def loguru_json_format():
    """
    Returns a custom formatter for Loguru that outputs Logler-compatible JSON.

    This gives you more control over the JSON structure than serialize=True.

    Usage:
        from loguru import logger

        logger.add("app.log", format=loguru_json_format())
        logger.info("Processing", user_id="alice", correlation_id="req-123")
    """

    def formatter(record):
        # Build Logler-optimized JSON structure
        log_entry = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "message": record["message"],
            "thread_id": record["thread"].name,
            "service_name": record.get("extra", {}).get("service_name", "app"),
            "file": f"{record['file'].name}:{record['line']}",
            "function": record["function"],
        }

        # Add optional fields from extra context
        extra_fields = ["correlation_id", "request_id", "trace_id", "span_id", "user_id"]
        for field in extra_fields:
            if field in record.get("extra", {}):
                log_entry[field] = record["extra"][field]

        # Add exception info if present
        if record["exception"]:
            log_entry["exception"] = {
                "type": record["exception"].type.__name__,
                "value": str(record["exception"].value),
            }

        # Add any other custom fields
        for key, value in record.get("extra", {}).items():
            if key not in extra_fields + ["service_name"]:
                log_entry[key] = value

        return json.dumps(log_entry)

    return formatter


# ==================== STRUCTLOG ====================


def configure_structlog_for_logler():
    """
    Configure structlog to output Logler-compatible JSON.

    Usage:
        import structlog
        from logler_helpers import configure_structlog_for_logler

        configure_structlog_for_logler()
        log = structlog.get_logger()
        log.info("hello", correlation_id="req-123", user_id="alice")
    """
    import structlog
    from structlog.processors import JSONRenderer

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            JSONRenderer(),  # JSON output for Logler
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ==================== PYTHON STDLIB LOGGING ====================


def get_logler_json_formatter():
    """
    Returns a JSON formatter for Python's stdlib logging.

    Usage:
        import logging
        from logler_helpers import get_logler_json_formatter

        handler = logging.FileHandler("app.log")
        handler.setFormatter(get_logler_json_formatter())

        logger = logging.getLogger(__name__)
        logger.addHandler(handler)
        logger.info("Processing request", extra={"correlation_id": "req-123"})
    """

    class LoglerJSONFormatter(logging.Formatter):
        def format(self, record):
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "thread_id": record.threadName,
                "service_name": getattr(record, "service_name", "app"),
                "file": f"{record.filename}:{record.lineno}",
                "function": record.funcName,
                "logger": record.name,
            }

            # Add custom fields from extra dict
            for key in ["correlation_id", "request_id", "trace_id", "span_id", "user_id"]:
                if hasattr(record, key):
                    log_entry[key] = getattr(record, key)

            # Add exception info
            if record.exc_info:
                log_entry["exception"] = self.formatException(record.exc_info)

            return json.dumps(log_entry)

    return LoglerJSONFormatter()


def get_logler_plaintext_formatter():
    """
    Returns a plain text formatter that Logler parses excellently.

    Logler's regex patterns will extract:
    - Timestamp (ISO 8601)
    - Log level
    - Thread ID
    - Correlation ID
    - Message

    Usage:
        import logging

        handler = logging.FileHandler("app.log")
        handler.setFormatter(get_logler_plaintext_formatter())

        logger = logging.getLogger(__name__)
        logger.addHandler(handler)
        logger.info("Processing", extra={"correlation_id": "req-123"})
    """

    class LoglerPlainTextFormatter(logging.Formatter):
        def format(self, record):
            # Build plain text in Logler-friendly format
            parts = [
                datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                record.levelname.ljust(8),
                f"[{record.threadName}]",
            ]

            # Add correlation ID if present
            if hasattr(record, "correlation_id"):
                parts.append(f"correlation_id={record.correlation_id}")

            if hasattr(record, "trace_id"):
                parts.append(f"trace_id={record.trace_id}")

            # Add message
            parts.append(record.getMessage())

            # Add exception if present
            if record.exc_info:
                parts.append("\n" + self.formatException(record.exc_info))

            return " ".join(parts)

    return LoglerPlainTextFormatter()


# ==================== FLASK ====================


def configure_flask_logging_for_logler(app, log_file: str = "flask.log", use_json: bool = True):
    """
    Configure Flask's app.logger for Logler.

    Args:
        app: Flask application instance
        log_file: Path to log file (default: "flask.log")
        use_json: Use JSON format (recommended) or plain text

    Usage:
        from flask import Flask
        from logler_helpers import configure_flask_logging_for_logler

        app = Flask(__name__)
        configure_flask_logging_for_logler(app, "myapp.log")

        @app.route('/')
        def index():
            app.logger.info("Request", extra={"correlation_id": "req-123"})
            return "OK"
    """
    from logging.handlers import RotatingFileHandler

    # Remove existing handlers
    app.logger.handlers.clear()

    # Add file handler with JSON or plain text
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=10)  # 10MB

    if use_json:
        file_handler.setFormatter(get_logler_json_formatter())
    else:
        file_handler.setFormatter(get_logler_plaintext_formatter())

    file_handler.setLevel(logging.DEBUG)
    app.logger.addHandler(file_handler)

    # Add console handler (always plain text)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s [%(threadName)s] %(message)s")
    )
    console_handler.setLevel(logging.INFO)
    app.logger.addHandler(console_handler)

    app.logger.setLevel(logging.DEBUG)


# ==================== FASTAPI ====================


def configure_fastapi_logging_for_logler(log_file: str = "fastapi.log", use_json: bool = True):
    """
    Configure FastAPI/Uvicorn logging for Logler.

    Args:
        log_file: Path to log file
        use_json: Use JSON format (recommended) or plain text

    Usage:
        from logler_helpers import configure_fastapi_logging_for_logler

        configure_fastapi_logging_for_logler("api.log")

        # Then in your FastAPI app:
        from fastapi import FastAPI
        import logging

        app = FastAPI()
        logger = logging.getLogger("uvicorn")

        @app.get("/")
        def read_root():
            logger.info("Request received", extra={"correlation_id": "req-123"})
            return {"status": "ok"}
    """
    from logging.handlers import RotatingFileHandler

    # Configure uvicorn logger
    logger = logging.getLogger("uvicorn")
    logger.handlers.clear()

    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=10)

    if use_json:
        file_handler.setFormatter(get_logler_json_formatter())
    else:
        file_handler.setFormatter(get_logler_plaintext_formatter())

    logger.addHandler(file_handler)

    # Also configure uvicorn.access
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.addHandler(file_handler)


# ==================== CORRELATION ID MIDDLEWARE ====================


def add_correlation_id_to_flask(app):
    """
    Flask middleware to add correlation IDs to all logs.

    Usage:
        from flask import Flask
        from logler_helpers import configure_flask_logging_for_logler, add_correlation_id_to_flask

        app = Flask(__name__)
        configure_flask_logging_for_logler(app)
        add_correlation_id_to_flask(app)
    """
    import uuid
    from flask import g, request

    @app.before_request
    def assign_correlation_id():
        g.correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Patch logger methods to include correlation_id
    original_info = app.logger.info
    original_error = app.logger.error
    original_warning = app.logger.warning
    original_debug = app.logger.debug

    def add_correlation(log_fn):
        def wrapper(msg, *args, **kwargs):
            if hasattr(g, "correlation_id"):
                if "extra" not in kwargs:
                    kwargs["extra"] = {}
                kwargs["extra"]["correlation_id"] = g.correlation_id
            return log_fn(msg, *args, **kwargs)

        return wrapper

    app.logger.info = add_correlation(original_info)
    app.logger.error = add_correlation(original_error)
    app.logger.warning = add_correlation(original_warning)
    app.logger.debug = add_correlation(original_debug)


# ==================== EXAMPLE USAGE ====================


def example_loguru():
    """Example: Loguru configuration"""
    print("\n" + "=" * 60)
    print("EXAMPLE 1: Loguru with Logler")
    print("=" * 60)
    print(
        """
from loguru import logger
from logler_helpers import configure_loguru_for_logler

# Configure for Logler
configure_loguru_for_logler(logger, "app.log")

# Log with correlation tracking
logger.info("User login", correlation_id="req-123", user_id="alice")
logger.error("Database timeout", correlation_id="req-123", table="users")

# View in Logler
# $ logler serve app.log --open

# Filter by correlation ID in the web UI to see the full request flow!
    """
    )


def example_flask():
    """Example: Flask application"""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Flask with Correlation Tracking")
    print("=" * 60)
    print(
        """
from flask import Flask
from logler_helpers import configure_flask_logging_for_logler, add_correlation_id_to_flask

app = Flask(__name__)
configure_flask_logging_for_logler(app, "flask.log")
add_correlation_id_to_flask(app)

@app.route('/api/data')
def get_data():
    # correlation_id automatically added!
    app.logger.info("Fetching data")
    app.logger.debug("Cache hit", extra={"cache_key": "user:123"})
    return {"data": "example"}

# Run app
# $ python app.py

# View logs
# $ logler serve flask.log --open

# The web UI will show all logs grouped by correlation_id!
    """
    )


def example_plain_text():
    """Example: Plain text format (still works great!)"""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Plain Text (Human-Friendly)")
    print("=" * 60)
    print(
        """
from loguru import logger

# Plain text format - Logler's regex extracts everything!
logger.add(
    "app.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} {level: <8} [{thread.name}] correlation_id={extra[correlation_id]} {message}"
)

logger.info("Request started", correlation_id="req-456")
logger.info("Processing...", correlation_id="req-456")
logger.info("Request completed", correlation_id="req-456")

# Logler automatically:
# - Parses timestamp
# - Extracts log level
# - Finds thread ID
# - Detects correlation_id
# - Groups logs by correlation_id

# $ logler serve app.log
    """
    )


if __name__ == "__main__":
    print("\n" + "🪵" * 30)
    print("Logler Helper Functions - Examples")
    print("🪵" * 30)

    example_loguru()
    example_flask()
    example_plain_text()

    print("\n" + "=" * 60)
    print("📚 Documentation")
    print("=" * 60)
    print(
        """
For more information:
- Logler Docs: https://github.com/gabu-quest/logler
- See handoff.md for complete format guide
- Run: logler --help

Happy logging! ✨
    """
    )
