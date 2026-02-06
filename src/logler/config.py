"""
Config file loader for user-defined log formats and correlation rules.

Reads .logler/formats.yaml and .logler/correlations.yaml from the current
directory or parent directories, letting users define custom regex patterns
for proprietary log formats and cross-file correlation rules.
"""

from __future__ import annotations

import fnmatch
import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .safe_regex import RegexPatternTooLongError, RegexTimeoutError, safe_compile


class FormatConfig(BaseModel):
    """A single user-defined log format."""

    model_config = ConfigDict(extra="forbid")

    regex: str = Field(description="Regex with named capture groups for parsing log lines")
    timestamp_format: Optional[str] = Field(
        None, description="strftime format for the timestamp capture group"
    )
    file_patterns: List[str] = Field(
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

    formats: Dict[str, FormatConfig] = Field(
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
            f"Invalid duration: {value!r}. " f"Expected format like '500ms', '5s', '1m', '2h'."
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

    file_pattern: Optional[str] = Field(
        None, description="Glob pattern to match filenames (e.g. 'mes_*.log')"
    )
    field: str = Field(description="Field name in the log entry (e.g. 'batch_id')")


class EventCondition(BaseModel):
    """Defines when an anchor event fires for temporal correlation."""

    model_config = ConfigDict(extra="forbid")

    file_pattern: Optional[str] = Field(
        None, description="Glob pattern to restrict which files to search"
    )
    field: Optional[str] = Field(None, description="Field name to evaluate the condition against")
    condition: Optional[str] = Field(
        None,
        description="Comparison expression for the field value (e.g. '< 2.0', '> 100')",
    )
    level: Optional[str] = Field(None, description="Match entries at this log level (e.g. 'ERROR')")
    pattern: Optional[str] = Field(None, description="Regex to match against the message text")

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                safe_compile(v)
            except (re.error, RegexTimeoutError, RegexPatternTooLongError) as exc:
                raise ValueError(f"Invalid anchor pattern: {exc}") from exc
        return v

    @model_validator(mode="after")
    def at_least_one_condition(self) -> "EventCondition":
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
    Union[FieldMatchRule, TemporalRule],
    Field(discriminator="type"),
]


class CorrelationGroup(BaseModel):
    """A named group of correlation rules."""

    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(None, description="Human-readable description")
    rules: List[CorrelationRule] = Field(
        ..., min_length=1, description="Correlation rules in this group"
    )


class CorrelationsConfig(BaseModel):
    """Top-level config loaded from .logler/correlations.yaml."""

    model_config = ConfigDict(extra="forbid")

    correlations: Dict[str, CorrelationGroup] = Field(
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
    current = Path(start_dir).resolve()

    while True:
        candidate = current / CONFIG_DIR / filename
        if candidate.is_file():
            return candidate

        parent = current.parent
        if parent == current:
            return None
        current = parent


def find_config(start_dir: str | Path) -> Path | None:
    """Walk parent directories looking for .logler/formats.yaml."""
    return _find_config_file(start_dir, CONFIG_FILENAME)


def find_correlations_config(start_dir: str | Path) -> Path | None:
    """Walk parent directories looking for .logler/correlations.yaml."""
    return _find_config_file(start_dir, CORRELATIONS_FILENAME)


def load_config(path: str | Path) -> LoglerConfig:
    """Load and validate a .logler/formats.yaml config file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Validated LoglerConfig instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the YAML is invalid or cannot be parsed.
        pydantic.ValidationError: If the config fails schema validation.
    """
    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if not data:
        return LoglerConfig()

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping at top level in {path}, got {type(data).__name__}"
        )

    return LoglerConfig.model_validate(data)


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
    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if not data:
        return CorrelationsConfig()

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping at top level in {path}, got {type(data).__name__}"
        )

    return CorrelationsConfig.model_validate(data)


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
