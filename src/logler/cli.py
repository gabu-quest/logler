"""Command-line interface for logler."""

import sys
import argparse
from typing import Optional, List
from pathlib import Path

from .log_reader import LogReader
from .log_parser import LogParser, LogFormat


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="logler",
        description="Cool local log viewing tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  logler app.log                          # View log file
  logler app.log -n 100                   # Show last 100 lines
  logler app.log -f                       # Follow log in real-time
  logler app.log -s ERROR                 # Search for ERROR level logs
  logler app.log --level ERROR            # Filter by ERROR level only
  logler app.log --grep "exception"       # Search for pattern
  logler app.log --no-color               # Disable colored output
  logler app.log --format json            # Force JSON format parsing
  logler app.log --reverse                # Show in reverse order
        """
    )

    parser.add_argument(
        "file",
        type=str,
        help="Path to the log file"
    )

    # Display options
    display_group = parser.add_argument_group("display options")
    display_group.add_argument(
        "-n", "--lines",
        type=int,
        metavar="N",
        help="Number of lines to show (from end of file)"
    )
    display_group.add_argument(
        "-f", "--follow",
        action="store_true",
        help="Follow log file in real-time (like tail -f)"
    )
    display_group.add_argument(
        "--head",
        type=int,
        metavar="N",
        help="Show first N lines (from beginning of file)"
    )
    display_group.add_argument(
        "--reverse",
        action="store_true",
        help="Show lines in reverse order"
    )
    display_group.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output"
    )
    display_group.add_argument(
        "--format",
        type=str,
        choices=["plain", "json", "syslog", "common"],
        help="Force specific log format (auto-detect by default)"
    )

    # Filtering options
    filter_group = parser.add_argument_group("filtering options")
    filter_group.add_argument(
        "-s", "--search",
        type=str,
        metavar="PATTERN",
        help="Search for pattern (case-insensitive by default)"
    )
    filter_group.add_argument(
        "--grep",
        type=str,
        metavar="PATTERN",
        help="Alias for --search"
    )
    filter_group.add_argument(
        "-i", "--case-sensitive",
        action="store_true",
        help="Make search case-sensitive"
    )
    filter_group.add_argument(
        "-r", "--regex",
        action="store_true",
        help="Treat search pattern as regex"
    )
    filter_group.add_argument(
        "--level",
        type=str,
        metavar="LEVEL",
        help="Filter by log level (DEBUG, INFO, WARN, ERROR, CRITICAL)"
    )

    # Info options
    info_group = parser.add_argument_group("info options")
    info_group.add_argument(
        "--info",
        action="store_true",
        help="Show file information and exit"
    )
    info_group.add_argument(
        "--count",
        action="store_true",
        help="Count total lines and exit"
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version="%(prog)s 0.1.0"
    )

    return parser.parse_args(args)


def filter_by_level(line: str, parser: LogParser, target_level: str) -> bool:
    """
    Check if a log line matches the target level.

    Args:
        line: Log line to check
        parser: Log parser instance
        target_level: Target log level (uppercase)

    Returns:
        True if line matches the level
    """
    level = parser.extract_level(line)
    return level == target_level.upper() if level else False


def main(args: Optional[List[str]] = None) -> int:
    """
    Main entry point for the CLI.

    Args:
        args: Command-line arguments (None to use sys.argv)

    Returns:
        Exit code (0 for success)
    """
    parsed_args = parse_args(args)

    try:
        reader = LogReader(parsed_args.file)

        # Info commands
        if parsed_args.info:
            info = reader.get_file_info()
            print(f"File: {info['path']}")
            print(f"Size: {info['size_human']} ({info['size']:,} bytes)")
            print(f"Modified: {info['modified']}")
            return 0

        if parsed_args.count:
            count = reader.count_lines()
            print(f"Total lines: {count:,}")
            return 0

        # Set up parser
        format_type = None
        if parsed_args.format:
            format_type = LogFormat(parsed_args.format)

        parser = LogParser(
            use_colors=not parsed_args.no_color,
            format_type=format_type
        )

        # Search pattern
        search_pattern = parsed_args.search or parsed_args.grep

        # Determine mode of operation
        if parsed_args.follow:
            # Follow mode (tail -f)
            num_lines = parsed_args.lines or 10

            try:
                for line in reader.tail(num_lines=num_lines, follow=True):
                    # Apply filters
                    if parsed_args.level and not filter_by_level(line, parser, parsed_args.level):
                        continue

                    if search_pattern:
                        import re
                        flags = 0 if parsed_args.case_sensitive else re.IGNORECASE
                        if parsed_args.regex:
                            if not re.search(search_pattern, line, flags):
                                continue
                        else:
                            pattern_check = search_pattern if parsed_args.case_sensitive else search_pattern.lower()
                            line_check = line if parsed_args.case_sensitive else line.lower()
                            if pattern_check not in line_check:
                                continue

                    # Output
                    formatted = parser.parse(line)
                    print(formatted, flush=True)

            except KeyboardInterrupt:
                return 0

        elif search_pattern:
            # Search mode
            for line_num, line in reader.search(
                pattern=search_pattern,
                case_sensitive=parsed_args.case_sensitive,
                regex=parsed_args.regex
            ):
                # Apply level filter
                if parsed_args.level and not filter_by_level(line, parser, parsed_args.level):
                    continue

                formatted = parser.parse(line)
                if parsed_args.no_color:
                    print(f"{line_num}: {formatted}")
                else:
                    print(f"\033[90m{line_num}:\033[0m {formatted}")

        else:
            # Normal read mode
            if parsed_args.head:
                # Read from beginning
                lines = reader.read_lines(max_lines=parsed_args.head)
            elif parsed_args.lines:
                # Read last N lines
                lines = list(reader.read_lines(reverse=True, max_lines=parsed_args.lines))
                lines = reversed(lines)
            elif parsed_args.reverse:
                # All lines in reverse
                lines = reader.read_lines(reverse=True)
            else:
                # All lines forward
                lines = reader.read_lines()

            for line in lines:
                # Apply filters
                if parsed_args.level and not filter_by_level(line, parser, parsed_args.level):
                    continue

                formatted = parser.parse(line)
                print(formatted)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
