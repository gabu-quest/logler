"""Log file reading and streaming module."""

import os
import time
from pathlib import Path
from typing import Iterator, Optional


class LogReader:
    """Efficient log file reader with support for tailing and large files."""

    def __init__(self, file_path: str, buffer_size: int = 8192):
        """
        Initialize the log reader.

        Args:
            file_path: Path to the log file
            buffer_size: Buffer size for reading (default 8KB)
        """
        self.file_path = Path(file_path)
        self.buffer_size = buffer_size

        if not self.file_path.exists():
            raise FileNotFoundError(f"Log file not found: {file_path}")

        if not self.file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")

    def read_lines(
        self, start_line: int = 0, max_lines: Optional[int] = None, reverse: bool = False
    ) -> Iterator[str]:
        """
        Read lines from the log file.

        Args:
            start_line: Line number to start from (0-indexed)
            max_lines: Maximum number of lines to read (None for all)
            reverse: Read lines in reverse order

        Yields:
            Log lines as strings
        """
        if reverse:
            yield from self._read_lines_reverse(start_line, max_lines)
        else:
            yield from self._read_lines_forward(start_line, max_lines)

    def _read_lines_forward(
        self, start_line: int = 0, max_lines: Optional[int] = None
    ) -> Iterator[str]:
        """Read lines forward from the file."""
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            line_num = 0
            lines_read = 0

            for line in f:
                if line_num >= start_line:
                    yield line.rstrip("\n\r")
                    lines_read += 1

                    if max_lines and lines_read >= max_lines:
                        break

                line_num += 1

    def _read_lines_reverse(
        self, start_line: int = 0, max_lines: Optional[int] = None
    ) -> Iterator[str]:
        """
        Read lines in reverse order using an efficient algorithm.

        This reads the file from the end in chunks to avoid loading
        the entire file into memory.
        """
        with open(self.file_path, "rb") as f:
            # Seek to end of file
            f.seek(0, os.SEEK_END)
            file_size = f.tell()

            # Read in chunks from the end
            buffer = b""
            position = file_size
            lines = []

            while position > 0:
                # Determine chunk size
                chunk_size = min(self.buffer_size, position)
                position -= chunk_size

                # Read chunk
                f.seek(position)
                chunk = f.read(chunk_size)

                # Combine with previous buffer
                buffer = chunk + buffer

                # Split into lines
                chunk_lines = buffer.split(b"\n")

                # Keep the first incomplete line in buffer
                buffer = chunk_lines[0]
                chunk_lines = chunk_lines[1:]

                # Add lines in reverse
                for line in reversed(chunk_lines):
                    if line or lines:  # Skip empty lines at the end
                        try:
                            decoded = line.decode("utf-8", errors="replace")
                            lines.append(decoded.rstrip("\r"))
                        except UnicodeDecodeError:
                            continue

            # Add the first line if buffer has content
            if buffer:
                try:
                    decoded = buffer.decode("utf-8", errors="replace")
                    lines.append(decoded.rstrip("\r"))
                except UnicodeDecodeError:
                    pass

            # Apply start_line and max_lines
            lines_to_yield = lines[start_line:]
            if max_lines:
                lines_to_yield = lines_to_yield[:max_lines]

            for line in lines_to_yield:
                yield line

    def tail(
        self, num_lines: int = 10, follow: bool = False, sleep_interval: float = 0.1
    ) -> Iterator[str]:
        """
        Tail the log file (like tail -f).

        Args:
            num_lines: Number of initial lines to show
            follow: If True, continue watching for new lines
            sleep_interval: How long to sleep between checks (seconds)

        Yields:
            Log lines as strings
        """
        # First, yield the last n lines
        for line in self._read_lines_reverse(max_lines=num_lines):
            pass  # Skip initial lines in non-follow mode if we just want to set position

        lines = list(self._read_lines_reverse(max_lines=num_lines))
        for line in reversed(lines):
            yield line

        if not follow:
            return

        # Follow mode: watch for new lines
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            # Seek to end
            f.seek(0, os.SEEK_END)

            while True:
                line = f.readline()
                if line:
                    yield line.rstrip("\n\r")
                else:
                    # Check if file was truncated (log rotation)
                    current_pos = f.tell()
                    f.seek(0, os.SEEK_END)
                    end_pos = f.tell()

                    if current_pos > end_pos:
                        # File was truncated, start from beginning
                        f.seek(0)
                    else:
                        # No new data, sleep
                        time.sleep(sleep_interval)

    def search(
        self,
        pattern: str,
        case_sensitive: bool = False,
        regex: bool = False,
        max_lines: Optional[int] = None,
    ) -> Iterator[tuple[int, str]]:
        """
        Search for lines matching a pattern.

        Args:
            pattern: Search pattern (string or regex)
            case_sensitive: Whether search is case-sensitive
            regex: Whether pattern is a regex
            max_lines: Maximum number of matching lines to return

        Yields:
            Tuples of (line_number, line_content)
        """
        import re as regex_module

        def make_regex_matcher(compiled):
            return lambda line: compiled.search(line)

        def make_case_insensitive_matcher(pat):
            return lambda line: pat in line.lower()

        def make_case_sensitive_matcher(pat):
            return lambda line: pat in line

        if regex:
            flags = 0 if case_sensitive else regex_module.IGNORECASE
            compiled_pattern = regex_module.compile(pattern, flags)
            match_func = make_regex_matcher(compiled_pattern)
        else:
            if not case_sensitive:
                pattern = pattern.lower()
                match_func = make_case_insensitive_matcher(pattern)
            else:
                match_func = make_case_sensitive_matcher(pattern)

        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            matches_found = 0

            for line_num, line in enumerate(f, 1):
                line = line.rstrip("\n\r")

                if match_func(line):
                    yield (line_num, line)
                    matches_found += 1

                    if max_lines and matches_found >= max_lines:
                        break

    def get_file_info(self) -> dict:
        """
        Get information about the log file.

        Returns:
            Dictionary with file metadata
        """
        stat = self.file_path.stat()

        return {
            "path": str(self.file_path.absolute()),
            "size": stat.st_size,
            "size_human": self._format_bytes(stat.st_size),
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
        }

    @staticmethod
    def _format_bytes(size: int) -> str:
        """Format bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def count_lines(self) -> int:
        """
        Count total number of lines in the file.

        Returns:
            Number of lines
        """
        count = 0
        with open(self.file_path, "rb") as f:
            for _ in f:
                count += 1
        return count
