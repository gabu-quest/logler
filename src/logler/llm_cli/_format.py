"""Format management commands (M1.3): list, test, validate."""

import re
import sys
from pathlib import Path
from typing import Any

import click

from ..builtin_formats import get_builtin_format, get_builtin_formats
from ..config import FormatFileError, config_for_file, find_config, load_usable_config
from ..parser import read_lines
from ..safe_regex import RegexPatternTooLongError, RegexTimeoutError, safe_compile
from ._core import (
    EXIT_NO_RESULTS,
    EXIT_SUCCESS,
    EXIT_USER_ERROR,
    _error_json,
    _expand_globs,
    _output_json,
    command,
    llm,
)


@llm.group()
def format():
    """
    Manage log format definitions.

    List built-in formats, test regex patterns against log files,
    and validate .logler/formats.yaml config files.
    """
    pass


@command("list", group=format)
@click.option("--builtin/--no-builtin", default=True, help="Include built-in formats")
@click.option("--config-dir", help="Directory to search for .logler/formats.yaml")
def format_list(builtin: bool, config_dir: str | None, pretty: bool):
    """List available log format definitions.

    Shows built-in formats and any user-defined formats from
    .logler/formats.yaml config files.
    """
    output: dict[str, Any] = {
        "builtin_formats": {},
        "user_formats": {},
        "config_path": None,
    }

    # Built-in formats
    if builtin:
        for name, fmt in get_builtin_formats().items():
            output["builtin_formats"][name] = {
                "regex": fmt.regex,
                "timestamp_format": fmt.timestamp_format,
                "file_patterns": fmt.file_patterns,
            }

    # User config
    search_dir = Path(config_dir) if config_dir else Path.cwd()
    config_path = find_config(search_dir)
    if config_path:
        output["config_path"] = str(config_path)
        try:
            config = load_usable_config(config_path)
            for name, fmt in config.formats.items():
                output["user_formats"][name] = {
                    "regex": fmt.regex,
                    "timestamp_format": fmt.timestamp_format,
                    "file_patterns": fmt.file_patterns,
                }
        except FormatFileError as e:
            output["config_error"] = str(e)

    has_any = output["builtin_formats"] or output["user_formats"]
    _output_json(output, pretty)
    sys.exit(EXIT_SUCCESS if has_any else EXIT_NO_RESULTS)


@command("test", group=format)
@click.option("--files", "-f", multiple=True, required=True, help="Log files to test")
@click.option("--regex", "-r", help="Regex pattern to test (with named groups)")
@click.option("--name", "-n", help="Built-in or user format name to test")
@click.option("--limit", default=20, help="Max lines to show")
def format_test(
    files: tuple,
    regex: str | None,
    name: str | None,
    limit: int,
    pretty: bool,
):
    """Test a format regex against log files.

    Provide either --regex with a pattern, or --name for a built-in/user format.
    Shows which lines match and the extracted named groups.
    """
    file_list = _expand_globs(list(files))
    if not file_list:
        _error_json(f"No files found matching: {files}")

    # Resolve the regex to test
    test_regex = None
    format_source = None

    if regex:
        test_regex = regex
        format_source = "inline"
    elif name:
        # Try built-in first
        fmt = get_builtin_format(name)
        if fmt:
            test_regex = fmt.regex
            format_source = "builtin"
        else:
            # Try user config
            config = config_for_file(file_list[0])
            if config and name in config.formats:
                test_regex = config.formats[name].regex
                format_source = "user_config"

        if not test_regex:
            _error_json(f"Format '{name}' not found in built-in or user config")
    else:
        _error_json("Provide either --regex or --name")

    # Compile the regex
    try:
        compiled = safe_compile(test_regex)
    except (re.error, RegexTimeoutError, RegexPatternTooLongError) as e:
        _error_json(f"Invalid regex: {e}")

    if not compiled.groupindex:
        _error_json("Regex must have at least one named group (?P<name>...)")

    # Test against files
    results: list[dict[str, Any]] = []
    total_lines = 0
    matched_lines = 0

    for file_path in file_list:
        try:
            for number, line in read_lines(file_path):
                if not line:
                    continue
                total_lines += 1
                match = compiled.match(line)
                if match:
                    matched_lines += 1
                    if len(results) < limit:
                        results.append(
                            {
                                "file": file_path,
                                "line_number": number,
                                "matched": True,
                                "groups": match.groupdict(),
                                "raw": line[:500],
                            }
                        )
                elif len(results) < limit and total_lines <= limit * 2:
                    results.append(
                        {
                            "file": file_path,
                            "line_number": number,
                            "matched": False,
                            "groups": {},
                            "raw": line[:500],
                        }
                    )
        except OSError as e:
            results.append(
                {
                    "file": file_path,
                    "error": str(e),
                }
            )

    match_rate = (matched_lines / total_lines * 100) if total_lines > 0 else 0

    output = {
        "regex": test_regex,
        "format_source": format_source,
        "named_groups": list(compiled.groupindex.keys()),
        "files_tested": file_list,
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "match_rate_percent": round(match_rate, 1),
        "results": results,
    }

    _output_json(output, pretty)
    sys.exit(EXIT_SUCCESS if matched_lines > 0 else EXIT_NO_RESULTS)


@command("validate", group=format)
@click.option("--config-dir", help="Directory to search for .logler/formats.yaml")
@click.option("--regex", "-r", help="Validate a single regex pattern")
def format_validate(
    config_dir: str | None,
    regex: str | None,
    pretty: bool,
):
    """Validate format definitions.

    Without --regex, validates the .logler/formats.yaml config file.
    With --regex, validates a single regex pattern for use as a log format.
    """
    if regex:
        # Validate a single regex
        issues = []
        try:
            compiled = safe_compile(regex)
        except re.error as e:
            _output_json(
                {
                    "valid": False,
                    "regex": regex,
                    "issues": [f"Regex compilation error: {e}"],
                },
                pretty,
            )
            sys.exit(EXIT_USER_ERROR)
        except (RegexTimeoutError, RegexPatternTooLongError) as e:
            _output_json(
                {
                    "valid": False,
                    "regex": regex,
                    "issues": [f"Regex safety check failed: {e}"],
                },
                pretty,
            )
            sys.exit(EXIT_USER_ERROR)

        named_groups = list(compiled.groupindex.keys())
        if not named_groups:
            issues.append("Regex has no named groups. Use (?P<name>...) syntax.")

        # Check for recommended groups
        recommended = {"message", "timestamp", "level"}
        present = set(named_groups)
        missing_recommended = recommended - present
        if missing_recommended:
            issues.append(
                f"Missing recommended groups: {', '.join(sorted(missing_recommended))}. "
                f"Present: {', '.join(named_groups)}"
            )

        output = {
            "valid": len(issues) == 0 or all("Missing recommended" in i for i in issues),
            "regex": regex,
            "named_groups": named_groups,
            "issues": issues,
        }
        _output_json(output, pretty)
        sys.exit(EXIT_SUCCESS)

    # Validate config file
    search_dir = Path(config_dir) if config_dir else Path.cwd()
    config_path = find_config(search_dir)

    if not config_path:
        _output_json(
            {
                "valid": False,
                "config_path": None,
                "issues": [f"No .logler/formats.yaml found starting from {search_dir}"],
            },
            pretty,
        )
        sys.exit(EXIT_NO_RESULTS)

    issues = []
    formats_valid = {}

    try:
        config = load_usable_config(config_path)
    except FormatFileError as e:
        _output_json(
            {
                "valid": False,
                "config_path": str(config_path),
                "issues": [f"Config load error: {e}"],
            },
            pretty,
        )
        sys.exit(EXIT_USER_ERROR)

    for fmt_name, fmt in config.formats.items():
        fmt_issues = []
        compiled = safe_compile(fmt.regex)
        named_groups = list(compiled.groupindex.keys())

        if "message" not in named_groups:
            fmt_issues.append("Missing recommended 'message' group")
        if "timestamp" not in named_groups:
            fmt_issues.append("Missing recommended 'timestamp' group")
        if not fmt.file_patterns:
            fmt_issues.append("No file_patterns defined (format won't auto-match)")

        formats_valid[fmt_name] = {
            "valid": len(fmt_issues) == 0,
            "named_groups": named_groups,
            "file_patterns": fmt.file_patterns,
            "issues": fmt_issues,
        }
        issues.extend(f"{fmt_name}: {i}" for i in fmt_issues)

    all_valid = all(f["valid"] for f in formats_valid.values())

    output = {
        "valid": all_valid,
        "config_path": str(config_path),
        "format_count": len(config.formats),
        "formats": formats_valid,
        "issues": issues,
    }

    _output_json(output, pretty)
    sys.exit(EXIT_SUCCESS)
