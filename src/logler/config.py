"""
Config file loader for user-defined log formats (BYOLF).

Reads .logler/formats.yaml from the current directory or parent directories,
letting users define custom regex patterns for proprietary log formats.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


CONFIG_DIR = ".logler"
CONFIG_FILENAME = "formats.yaml"


def find_config(start_dir: str | Path) -> Path | None:
    """Walk parent directories looking for .logler/formats.yaml.

    Follows the same resolution pattern as .gitignore: starts at start_dir
    and walks up to the filesystem root.

    Args:
        start_dir: Directory to start searching from.

    Returns:
        Path to the config file, or None if not found.
    """
    current = Path(start_dir).resolve()

    while True:
        candidate = current / CONFIG_DIR / CONFIG_FILENAME
        if candidate.is_file():
            return candidate

        parent = current.parent
        if parent == current:
            return None
        current = parent


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
