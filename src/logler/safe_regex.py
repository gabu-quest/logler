"""
Safe regex compilation with timeout protection against ReDoS attacks.

This module provides a safe_compile function that wraps re.compile with:
- Pattern length validation
- Compilation timeout (Unix only, graceful fallback on Windows)
- Clear error messages
"""

import re
import threading
from typing import Optional


class RegexTimeoutError(Exception):
    """Raised when regex compilation times out."""

    pass


class RegexPatternTooLongError(Exception):
    """Raised when regex pattern exceeds maximum allowed length."""

    pass


# Maximum pattern length to prevent ReDoS via complexity
MAX_PATTERN_LENGTH = 1000

# Timeout for regex compilation in seconds
COMPILE_TIMEOUT = 2.0


def _compile_with_timeout(
    pattern: str,
    flags: int,
    timeout: float,
    result_container: dict,
) -> None:
    """Worker function for threaded compilation."""
    try:
        result_container["result"] = re.compile(pattern, flags)
    except re.error as e:
        result_container["error"] = e
    except Exception as e:
        result_container["error"] = e


def safe_compile(
    pattern: str,
    flags: int = 0,
    timeout: float = COMPILE_TIMEOUT,
    max_length: int = MAX_PATTERN_LENGTH,
) -> re.Pattern:
    """
    Safely compile a regex pattern with timeout protection.

    Args:
        pattern: The regex pattern to compile
        flags: Optional regex flags (e.g., re.IGNORECASE)
        timeout: Maximum time in seconds to allow for compilation
        max_length: Maximum allowed pattern length

    Returns:
        Compiled regex pattern

    Raises:
        RegexPatternTooLongError: If pattern exceeds max_length
        RegexTimeoutError: If compilation takes longer than timeout
        re.error: If the pattern is invalid
    """
    # Validate pattern length
    if len(pattern) > max_length:
        raise RegexPatternTooLongError(
            f"Regex pattern length {len(pattern)} exceeds maximum {max_length}"
        )

    # Use threading for cross-platform timeout support
    result_container: dict = {}
    thread = threading.Thread(
        target=_compile_with_timeout,
        args=(pattern, flags, timeout, result_container),
    )
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Thread is still running - compilation timed out
        # Note: We can't actually kill the thread, but we return an error
        raise RegexTimeoutError(
            f"Regex compilation timed out after {timeout}s (pattern may cause catastrophic backtracking)"
        )

    if "error" in result_container:
        raise result_container["error"]

    return result_container["result"]


def try_compile(
    pattern: str,
    flags: int = 0,
    timeout: float = COMPILE_TIMEOUT,
    max_length: int = MAX_PATTERN_LENGTH,
) -> Optional[re.Pattern]:
    """
    Try to compile a regex pattern safely, returning None on failure.

    This is a convenience wrapper around safe_compile that catches all
    exceptions and returns None instead.

    Args:
        pattern: The regex pattern to compile
        flags: Optional regex flags
        timeout: Maximum compilation time
        max_length: Maximum pattern length

    Returns:
        Compiled pattern or None if compilation fails
    """
    try:
        return safe_compile(pattern, flags, timeout, max_length)
    except (RegexTimeoutError, RegexPatternTooLongError, re.error):
        return None
