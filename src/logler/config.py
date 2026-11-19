"""
Config file loader for user-defined log formats and correlation rules.

Reads .logler/formats.yaml and .logler/correlations.yaml from the current
directory or parent directories, letting users define custom regex patterns
for proprietary log formats and cross-file correlation rules.
"""

from __future__ import annotations

import fnmatch
import os
import re
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .safe_regex import RegexPatternTooLongError, RegexTimeoutError, safe_compile


class FormatConfig(BaseModel):
    """A single user-defined log format."""

    model_config = ConfigDict(extra="forbid")

    regex: str = Field(description="Regex with named capture groups for parsing log lines")
    timestamp_format: str | None = Field(
        None, description="strftime format for the timestamp capture group"
    )
    file_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns to auto-match files",
    )

    @field_validator("regex")
    @classmethod
    def validate_regex(cls, v: str) -> str:
        """Validate that the regex compiles safely and has at least one named group."""
        try:
            compiled = safe_compile(v)
        except (re.error, RegexTimeoutError, RegexPatternTooLongError) as exc:
            raise ValueError(f"Invalid regex pattern: {exc}") from exc
        if not compiled.groupindex:
            raise ValueError(
                f"Regex must contain at least one named group (?P<name>...), "
                f"got pattern with no named groups: {v!r}"
            )
        return v


class LoglerConfig(BaseModel):
    """Top-level config loaded from .logler/formats.yaml."""

    model_config = ConfigDict(extra="forbid")

    formats: dict[str, FormatConfig] = Field(
        default_factory=dict,
        description="Named log format definitions",
    )


# =============================================================================
# Correlation Config Models (M2.1)
# =============================================================================

_DURATION_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*(ms|s|m|h)$")


def parse_duration(value: str) -> timedelta:
    """Parse a human-readable duration string into a timedelta.

    Supported formats: '500ms', '5s', '1.5m', '2h'.

    Args:
        value: Duration string.

    Returns:
        Parsed timedelta.

    Raises:
        ValueError: If the format is invalid.
    """
    match = _DURATION_PATTERN.match(value.strip())
    if not match:
        raise ValueError(
            f"Invalid duration: {value!r}. Expected format like '500ms', '5s', '1m', '2h'."
        )
    amount = float(match.group(1))
    unit = match.group(2)
    if unit == "ms":
        return timedelta(milliseconds=amount)
    elif unit == "s":
        return timedelta(seconds=amount)
    elif unit == "m":
        return timedelta(minutes=amount)
    else:  # "h"
        return timedelta(hours=amount)


class FieldSelector(BaseModel):
    """Points to a named field in log entries from matching files."""

    model_config = ConfigDict(extra="forbid")

    file_pattern: str | None = Field(
        None, description="Glob pattern to match filenames (e.g. 'mes_*.log')"
    )
    field: str = Field(description="Field name in the log entry (e.g. 'batch_id')")


class EventCondition(BaseModel):
    """Defines when an anchor event fires for temporal correlation."""

    model_config = ConfigDict(extra="forbid")

    file_pattern: str | None = Field(
        None, description="Glob pattern to restrict which files to search"
    )
    field: str | None = Field(None, description="Field name to evaluate the condition against")
    condition: str | None = Field(
        None,
        description="Comparison expression for the field value (e.g. '< 2.0', '> 100')",
    )
    level: str | None = Field(None, description="Match entries at this log level (e.g. 'ERROR')")
    pattern: str | None = Field(None, description="Regex to match against the message text")

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                safe_compile(v)
            except (re.error, RegexTimeoutError, RegexPatternTooLongError) as exc:
                raise ValueError(f"Invalid anchor pattern: {exc}") from exc
        return v

    @model_validator(mode="after")
    def at_least_one_condition(self) -> EventCondition:
        has_any = self.field is not None or self.level is not None or self.pattern is not None
        if not has_any:
            raise ValueError(
                "EventCondition must specify at least one of: field+condition, level, pattern"
            )
        return self


class FieldMatchRule(BaseModel):
    """Link entries across files when field values match."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["field_match"]
    source: FieldSelector
    target: FieldSelector


class TemporalRule(BaseModel):
    """Collect entries within a time window around an anchor event."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["temporal"]
    anchor: EventCondition
    window: str = Field(description="Time window around the anchor (e.g. '5s', '1m')")

    @field_validator("window")
    @classmethod
    def validate_window(cls, v: str) -> str:
        parse_duration(v)
        return v


CorrelationRule = Annotated[
    FieldMatchRule | TemporalRule,
    Field(discriminator="type"),
]


class CorrelationGroup(BaseModel):
    """A named group of correlation rules."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(None, description="Human-readable description")
    rules: list[CorrelationRule] = Field(
        ..., min_length=1, description="Correlation rules in this group"
    )


class CorrelationsConfig(BaseModel):
    """Top-level config loaded from .logler/correlations.yaml."""

    model_config = ConfigDict(extra="forbid")

    correlations: dict[str, CorrelationGroup] = Field(
        default_factory=dict,
        description="Named correlation rule groups",
    )


# =============================================================================
# Config File Discovery and Loading
# =============================================================================

CONFIG_DIR = ".logler"
CONFIG_FILENAME = "formats.yaml"
CORRELATIONS_FILENAME = "correlations.yaml"


def _find_config_file(start_dir: str | Path, filename: str) -> Path | None:
    """Walk parent directories looking for .logler/<filename>.

    Args:
        start_dir: Directory to start searching from.
        filename: Config filename to look for inside .logler/.

    Returns:
        Path to the config file, or None if not found.
    """
    found = _walk_up(os.path.realpath(start_dir), filename)
    return Path(found) if found else None


def _walk_up(directory: str, filename: str) -> str | None:
    """The one walk: `.logler/<filename>` in `directory` (already resolved) or a parent."""
    while True:
        candidate = os.path.join(directory, CONFIG_DIR, filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def find_config(start_dir: str | Path) -> Path | None:
    """Walk parent directories looking for .logler/formats.yaml."""
    return _find_config_file(start_dir, CONFIG_FILENAME)


def find_correlations_config(start_dir: str | Path) -> Path | None:
    """Walk parent directories looking for .logler/correlations.yaml."""
    return _find_config_file(start_dir, CORRELATIONS_FILENAME)


def _read_mapping(path: Path) -> dict | None:
    """The top-level mapping of a YAML config file; ``None`` for an empty file."""
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not data:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping at top level, got {type(data).__name__}")
    return data


def config_problem(exc: Exception) -> str:
    """Why a config file cannot be used, as text for its user: a schema error is one
    ``key.path: what is wrong`` per error."""
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    return str(exc)


def load_config(path: str | Path) -> LoglerConfig:
    """Load and validate a .logler/formats.yaml config file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Validated LoglerConfig instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the YAML is invalid or cannot be parsed. The message does not name the
            file; the caller knows which one it asked for.
        pydantic.ValidationError: If the config fails schema validation.
    """
    data = _read_mapping(Path(path))
    return LoglerConfig() if data is None else LoglerConfig.model_validate(data)


def load_correlations_config(path: str | Path) -> CorrelationsConfig:
    """Load and validate a .logler/correlations.yaml config file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Validated CorrelationsConfig instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the YAML is invalid or cannot be parsed.
        pydantic.ValidationError: If the config fails schema validation.
    """
    data = _read_mapping(Path(path))
    return CorrelationsConfig() if data is None else CorrelationsConfig.model_validate(data)


def get_format_for_file(config: LoglerConfig, filepath: str | Path) -> FormatConfig | None:
    """Find the first format whose file_patterns match the given filename.

    Matching uses fnmatch (Unix shell-style wildcards) against the filename
    only (not the full path).

    Args:
        config: A loaded LoglerConfig.
        filepath: Path to a log file (only the filename part is matched).

    Returns:
        The first matching FormatConfig, or None if no format matches.
    """
    filename = Path(filepath).name

    for format_config in config.formats.values():
        for pattern in format_config.file_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return format_config

    return None


# =============================================================================
# Which format parses a file
# =============================================================================

# Per formats.yaml: (stamp, config, problem), valid while the file's (mtime, size) is
# unchanged. One of config and problem is None.
_config_cache: dict[str, tuple] = {}


def _stamp(path: Path) -> tuple:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def formats_stamp(file: str | Path) -> tuple | None:
    """What a change of the format that parses ``file`` would change: the formats.yaml
    found from the file's directory and its (mtime, size); ``None`` when there is none.

    A cheap check (a ``stat`` per directory up to the config, no parse) for caches of what a
    file reads as.
    """
    found = _walk_up(os.path.dirname(os.path.realpath(file)), CONFIG_FILENAME)
    if found is None:
        return None
    try:
        return (found, *_stamp(Path(found)))
    except OSError:
        return None


class FormatFileError(ValueError):
    """A ``.logler/formats.yaml`` that cannot be used: the message names the file and the
    problem. A ``ValueError`` because the explicit-regex path raises one for a regex the
    engine cannot compile, and callers catch that."""

    def __init__(self, path: str | Path, problem: str):
        super().__init__(f"{path}: {problem}")
        self.path = str(path)
        self.problem = problem


@lru_cache(maxsize=256)
def _rust_error(regex: str) -> str | None:
    """What the Rust engine, the only reader of a custom regex, says about a regex it cannot
    compile; ``None`` when it compiles."""
    import logler_rs

    try:
        logler_rs.PyLineParser(custom_regex=regex)
    except Exception as exc:
        return str(exc)
    return None


def load_usable_config(path: str | Path) -> LoglerConfig:
    """The one decision whether a formats.yaml can be used: ``load_config`` plus the Rust
    engine's compile of every format's regex, so the verdict is for the whole file.

    Raises:
        FormatFileError: naming the file and the problem (and the format, for a regex).
    """
    try:
        config = load_config(path)
    except (OSError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
        raise FormatFileError(path, config_problem(exc)) from exc
    for name, fmt in config.formats.items():
        error = _rust_error(fmt.regex)
        if error is not None:
            raise FormatFileError(
                path, f"format '{name}': the regex cannot be compiled by the Rust engine: {error}"
            )
    return config


def _load_cached(config_path: Path) -> LoglerConfig:
    """The usable config of a formats.yaml, loaded once per (mtime, size). A failure is kept
    the same way, as its text: each call raises a new error, because one error object raised
    again and again grows its traceback for the life of the process."""
    key = str(config_path)
    try:
        stamp = _stamp(config_path)
    except OSError as exc:
        raise FormatFileError(config_path, str(exc)) from exc
    cached = _config_cache.get(key)
    if cached is None or cached[0] != stamp:
        try:
            cached = (stamp, load_usable_config(config_path), None)
        except FormatFileError as exc:
            cached = (stamp, None, exc.problem)
        _config_cache[key] = cached
    if cached[2] is not None:
        raise FormatFileError(config_path, cached[2])
    return cached[1]


def config_for_file(path: str | Path) -> LoglerConfig | None:
    """The usable ``.logler/formats.yaml`` found from the file's own directory, ``None`` when
    there is none.

    Raises:
        FormatFileError: the file found cannot be used (see ``load_usable_config``).
    """
    config_path = find_config(Path(path).resolve().parent)
    return None if config_path is None else _load_cached(config_path)


def format_for_file(path: str | Path) -> FormatConfig | None:
    """The format that parses this file, or ``None`` for the built-in detection.

    This is the one place that decides which format a file gets: the first format of the
    ``.logler/formats.yaml`` found from the file's own directory whose ``file_patterns`` match
    the file's name. ``None`` when there is no config or no format names the file.

    Raises:
        FormatFileError: the config found cannot be used, whichever file is asked for.
    """
    config = config_for_file(path)
    return None if config is None else get_format_for_file(config, path)
